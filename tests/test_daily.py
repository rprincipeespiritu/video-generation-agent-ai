from contextlib import redirect_stdout
from datetime import datetime as real_datetime
from io import StringIO
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
from fixtures import agent, JobTestCase, script, sources


def long_script():
    item = script()
    item['scenes'] = [dict(item['scenes'][0], heading=f'Sección {i}',
                           narration=' '.join(['información'] * 100)) for i in range(14)]
    return item


class LongVideoTests(JobTestCase):
    def test_script_uses_strict_schema_with_only_researched_urls(self):
        import json
        api = Mock()

        def provider_validation(**kwargs):
            # Validar el contrato de salida y los datos que recibe el proveedor.
            fmt = kwargs['text']['format']
            self.assertEqual(fmt['type'], 'json_schema')
            self.assertTrue(fmt['strict'])
            scene = fmt['schema']['properties']['scenes']['items']
            self.assertEqual(set(scene['properties']['sources']['items']['enum']),
                             {source['url'] for source in sources()})
            self.assertFalse(scene['additionalProperties'])
            self.assertIn('json', kwargs['input'].lower())
            return Mock(output_text=json.dumps(script()))

        api.responses.create.side_effect = provider_validation
        with patch.object(agent, 'client', return_value=api):
            agent.make_script(self.folder, 'Seres mitológicos')
        self.assertEqual(agent.load(self.folder / 'script.json'), script())

    def test_invalid_script_response_is_preserved_without_replacing_valid_script(self):
        import json
        api = Mock()
        invalid = script()
        invalid['scenes'][0]['sources'] = ['https://example.com/inventada']
        api.responses.create.return_value.output_text = json.dumps(invalid)
        with patch.object(agent, 'client', return_value=api), self.assertRaises(agent.ScriptError):
            agent.make_script(self.folder, '')
        self.assertEqual(agent.load(self.folder / 'script.json'), script())
        self.assertIn('inventada', (self.folder / 'script_response.txt').read_text())

    def test_incomplete_script_response_is_preserved_and_not_rendered(self):
        api = Mock()
        api.responses.create.return_value = Mock(output_text='{"title":', status='incomplete')
        with patch.object(agent, 'client', return_value=api), self.assertRaisesRegex(agent.ScriptError, 'no terminó'):
            agent.make_script(self.folder, '')
        self.assertEqual((self.folder / 'script_response.txt').read_text(), '{"title":')

    def test_long_script_limits(self):
        item = long_script()
        agent.validate_script(item, sources())
        agent.validate_long_script(item)
        item['scenes'] = item['scenes'][:11]
        with self.assertRaisesRegex(ValueError, '12 a 20'):
            agent.validate_long_script(item)
        item = long_script()
        for scene in item['scenes']:
            scene['narration'] = 'demasiado breve'
        with self.assertRaisesRegex(ValueError, 'palabras'):
            agent.validate_long_script(item)

    def test_ten_minute_script_requested_and_invalid_result_saved_for_editing(self):
        state = self.state()
        state.update(target_seconds=600, requested_topic='Computación cuántica')
        agent.save(self.folder / 'state.json', state)
        api = Mock()
        import json
        api.responses.create.return_value.output_text = json.dumps(script())
        with patch.object(agent, 'client', return_value=api), self.assertRaisesRegex(ValueError, '10 minutos'):
            agent.make_script(self.folder, '')
        args = api.responses.create.call_args.kwargs
        self.assertIn('10 minutos', args['instructions'])
        self.assertIn('Computación cuántica', args['input'])
        self.assertEqual(agent.load(self.folder / 'script.json'), script())

    def test_extreme_duration_never_stretched(self):
        for duration in (9, 300, 800):
            with patch.object(agent, 'run') as run, self.assertRaisesRegex(ValueError, 'narración dura'):
                agent.fit_duration(self.folder, self.folder / 'video.mp4', duration, 600)
            run.assert_not_called()

    def test_duration_adjustment_preserves_both_streams(self):
        with patch.object(agent, 'run') as run, patch.object(agent, 'inspect_video', return_value=600):
            _, actual, ratio = agent.fit_duration(self.folder, self.folder / 'video.mp4', 660, 600)
        self.assertEqual(actual, 600)
        self.assertAlmostEqual(ratio, 1.1)
        args = run.call_args.args
        self.assertIn('atempo=1.10000000,apad', args)
        self.assertIn('600', args)

    def test_bad_duration_adjustment_fails(self):
        with patch.object(agent, 'run'), patch.object(agent, 'inspect_video', return_value=580):
            with self.assertRaisesRegex(ValueError, 'ajustar'):
                agent.fit_duration(self.folder, self.folder / 'video.mp4', 660, 600)

    def test_custom_topic_research_does_not_request_five_news_topics(self):
        state = self.state()
        state['requested_topic'] = 'Historia de la computación'
        agent.save(self.folder / 'state.json', state)
        api = Mock()
        response = api.responses.create.return_value
        response.output_text = 'Evidencia'
        response.model_dump.return_value = {'output': [{'content': [{'annotations': [
            dict(source, type='url_citation') for source in sources()]}]}]}
        with patch.object(agent, 'client', return_value=api):
            agent.research(self.folder, agent.DEFAULT_FOCUS)
        prompt = api.responses.create.call_args.kwargs['input']
        self.assertIn('Historia de la computación', prompt)
        self.assertNotIn('Investiga cinco temas', prompt)


class DailyTests(JobTestCase):
    def test_daily_runs_once_and_never_publishes(self):
        with tempfile.TemporaryDirectory() as root, patch.object(agent, 'DATA', Path(root)):
            def produce(**kwargs):
                folder = kwargs['folder']
                agent.save(folder / 'state.json', {'status': 'REVIEW', 'demo': False})
                return folder
            with patch.object(agent, 'client'), patch.object(agent, 'create_video', side_effect=produce) as create:
                with patch.object(agent, 'publish', side_effect=AssertionError('No publicar')):
                    first = agent.daily()
                    second = agent.daily()
            self.assertEqual(first, second)
            create.assert_called_once()
            self.assertEqual(agent.load(first / 'state.json')['status'], 'REVIEW')

    def test_missing_key_does_not_reserve_day(self):
        with tempfile.TemporaryDirectory() as root, patch.object(agent, 'DATA', Path(root)):
            with patch.object(agent, 'client', side_effect=ValueError('Falta clave')), self.assertRaises(ValueError):
                agent.daily()
            self.assertEqual(list(Path(root).glob('diario-*')), [])

    def test_simulation_does_not_consume_real_day(self):
        with tempfile.TemporaryDirectory() as root, patch.object(agent, 'DATA', Path(root)):
            def fake_demo(**kwargs):
                agent.save(kwargs['folder'] / 'state.json', {'status': 'REVIEW', 'demo': True})
                return kwargs['folder']
            with patch.object(agent, 'client', side_effect=AssertionError('Sin API')):
                with patch.object(agent, 'demo', side_effect=fake_demo):
                    folder = agent.daily(simulate=True)
            self.assertTrue(folder.name.startswith('demo-diario-'))
            self.assertEqual(list(Path(root).glob('diario-*')), [])

    def test_failed_day_is_not_automatically_recharged(self):
        with tempfile.TemporaryDirectory() as root, patch.object(agent, 'DATA', Path(root)):
            def fail(**kwargs):
                agent.save(kwargs['folder'] / 'state.json', {'status': 'ERROR', 'demo': False})
                raise RuntimeError('fallo')
            with patch.object(agent, 'client'), patch.object(agent, 'create_video', side_effect=fail) as create:
                with self.assertRaises(RuntimeError):
                    agent.daily()
                folder = agent.daily()
            create.assert_called_once()
            self.assertEqual(agent.load(folder / 'state.json')['status'], 'ERROR')

    def test_date_uses_lima_even_before_utc_midnight_boundary(self):
        with tempfile.TemporaryDirectory() as root, patch.object(agent, 'DATA', Path(root)):
            with patch.object(agent, 'datetime') as clock:
                clock.now.return_value = real_datetime.fromisoformat('2026-10-10T23:30:00-05:00')
                with patch.object(agent, 'client'), patch.object(agent, 'create_video') as create:
                    agent.daily()
                self.assertEqual(str(clock.now.call_args.args[0]), 'America/Lima')
                self.assertEqual(create.call_args.kwargs['folder'].name, 'diario-2026-10-10')

    def test_create_finishes_at_review_without_approval(self):
        def generated(folder, **kwargs):
            state = self.state()
            state['status'] = 'REVIEW'
            agent.save(folder / 'state.json', state)
        with patch.object(agent, 'investigate', return_value=self.folder) as investigate:
            with patch.object(agent, 'generate', side_effect=generated):
                with patch.object(agent, 'approve') as approve, patch.object(agent, 'publish') as publish:
                    agent.create_video(topic='Tema indicado')
        self.assertEqual(investigate.call_args.kwargs['topic'], 'Tema indicado')
        approve.assert_not_called()
        publish.assert_not_called()
        self.assertEqual(self.state()['status'], 'REVIEW')

    def test_pending_filter(self):
        with tempfile.TemporaryDirectory() as root, patch.object(agent, 'DATA', Path(root)):
            for status in ('REVIEW', 'ERROR', 'APPROVED'):
                folder = Path(root) / status
                folder.mkdir()
                agent.save(folder / 'state.json', {'status': status})
            output = StringIO()
            with redirect_stdout(output):
                agent.main(['listar', '--pendientes'])
            self.assertIn('REVIEW', output.getvalue())
            self.assertNotIn('ERROR', output.getvalue())
            self.assertNotIn('APPROVED', output.getvalue())
