"""Pruebas HTTP locales: nunca ejecutar proveedores ni guardar credenciales reales."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fixtures import agent, script, sources
import ui


class PanelTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.folder = self.root / 'data' / 'video-test'
        self.folder.mkdir(parents=True)
        for name, value in [('ROOT', self.root), ('DATA', self.root / 'data')]:
            patcher = patch.object(agent, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {'OPENAI_API_KEY': '', 'CODEX_HOME': str(self.root / 'codex')})
        env.start()
        self.addCleanup(env.stop)
        agent.save(self.folder / 'script.json', script())
        agent.save(self.folder / 'sources.json', sources())
        (self.folder / 'video.mp4').write_bytes(b'0123456789')
        agent.save(self.folder / 'state.json', {'status': 'REVIEW', 'demo': False,
                   'render_hash': agent.render_digest(self.folder)})
        self.server = ui.LocalServer(0)
        worker = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        worker.start()

        def close():
            self.server.shutdown()
            self.server.server_close()
            worker.join(timeout=3)
        self.addCleanup(close)

    def request(self, path, data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        opts = {'Content-Type': 'application/json', 'X-Local-Token': self.server.token}
        opts.update(headers or {})
        try:
            connection.request('GET' if data is None else 'POST', path,
                               body=None if data is None else json.dumps(data), headers=opts)
            response = connection.getresponse()
            body = response.read()
            if response.getheader('Content-Type', '').startswith('application/json'):
                body = json.loads(body)
            return response.status, body, dict(response.getheaders())
        finally:
            connection.close()

    def state(self, **changes):
        state = agent.load(self.folder / 'state.json')
        if changes:
            state.update(changes)
            agent.save(self.folder / 'state.json', state)
        return state

    def action(self, name, data):
        return self.request('/api/jobs/video-test/' + name, data)

    def approval(self):
        return {'reviewed': True, 'confirmation': 'APROBAR',
                'review_hash': agent.render_digest(self.folder),
                'publication': {'channel_id': 'UC' + 'a' * 22, 'privacy': 'private',
                                'made_for_kids': False, 'synthetic_media': False}}

    def test_library_detail_and_static_assets(self):
        for path in ('/', '/app.js', '/style.css', '/icon.svg'):
            with self.subTest(path=path):
                code, body, headers = self.request(path)
                self.assertEqual(code, 200)
                self.assertTrue(body)
                self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(self.request('/api/jobs')[1]['jobs'][0]['id'], 'video-test')
        details = self.request('/api/jobs/video-test')[1]
        self.assertTrue(details['render_current'])
        self.assertEqual(details['script_hash'], ui.script_hash(self.folder))

    def test_origin_host_and_session_protection(self):
        for headers in ({'Host': 'attacker.test'}, {'Origin': 'https://attacker.test'},
                        {'Sec-Fetch-Site': 'cross-site'}, {'X-Local-Token': ''}):
            with self.subTest(headers=headers):
                with patch.object(self.server.activity, 'start') as start:
                    self.assertEqual(self.request('/api/create', {'mode': 'demo'}, headers)[0], 403)
                    start.assert_not_called()
        self.assertEqual(self.request('/api/session', headers={'Host': 'attacker.test'})[0], 403)
        self.assertEqual(self.request('/api/session')[1]['token'], self.server.token)

    def test_files_outside_allowed_routes_are_not_served(self):
        (self.root / '.env').write_text('OPENAI_API_KEY=private-test-value\n')
        for path in ('/.env', '/agent.py', '/media/video-test/state.json',
                     '/media/%2e%2e/video', '/api/jobs/%2e%2e', '/media/video-test/../../.env'):
            with self.subTest(path=path):
                code, body, _ = self.request(path)
                self.assertIn(code, (400, 404))
                self.assertNotIn('private-test-value', str(body))

    def test_video_ranges_support_playback_and_seek(self):
        code, body, headers = self.request('/media/video-test/video', headers={'Range': 'bytes=2-5'})
        self.assertEqual((code, body), (206, b'2345'))
        self.assertEqual(headers['Content-Range'], 'bytes 2-5/10')
        self.assertEqual(self.request('/media/video-test/video', headers={'Range': 'bytes=-3'})[:2],
                         (206, b'789'))
        self.assertEqual(self.request('/media/video-test/video', headers={'Range': 'bytes=50-'})[0], 416)

    def test_configuration_never_returns_saved_secret(self):
        (self.root / '.env').write_text('OPENAI_MODEL=custom-model\n')
        self.assertEqual(self.request('/api/config', {'openai_key': 'fake-test-key'})[:2], (200, {'saved': True}))
        code, body, _ = self.request('/api/status')
        self.assertEqual(code, 200)
        self.assertTrue(body['configuration']['openai_configured'])
        self.assertNotIn('fake-test-key', json.dumps(body))
        self.assertIn('OPENAI_MODEL=custom-model', (self.root / '.env').read_text())

    def test_create_requires_key_and_passes_topic_as_one_argument(self):
        with patch.object(self.server.activity, 'start', return_value={'status': 'RUNNING'}) as start:
            self.assertEqual(self.request('/api/create', {'mode': 'topic', 'topic': 'Ciencia'})[0], 400)
            start.assert_not_called()
            (self.root / '.env').write_text('OPENAI_API_KEY=fake-test-key\n')
            topic = 'Ciencia & "Perú"; echo prueba'
            self.assertEqual(self.request('/api/create', {'mode': 'topic', 'topic': topic})[0], 200)
            self.assertEqual(start.call_args.args[1], [['crear', '--tema', topic]])

    def test_production_preferences_and_preview_preserve_existing_approval(self):
        self.action('approve', self.approval())
        before = self.state()
        self.assertEqual(self.request('/api/production', {'voice': 'cedar', 'visual_mode': 'images'})[0], 200)
        config = self.request('/api/status')[1]['configuration']['production']
        self.assertEqual((config['voice'], config['visual_mode']), ('cedar', 'images'))
        self.assertEqual(self.request('/api/production', {'voice': '../secret', 'visual_mode': 'images'})[0], 400)
        with patch.object(self.server.activity, 'start', return_value={'status': 'RUNNING'}) as start:
            self.assertEqual(self.action('preview', {})[0], 200)
            self.assertEqual(start.call_args.args[1], [['muestra', 'video-test']])
            self.assertEqual(self.state(), before)
            self.state(demo=True)
            self.assertEqual(self.action('preview', {})[0], 400)
        (self.folder / 'preview.mp4').write_bytes(b'0123456789')
        self.assertEqual(self.request('/media/video-test/preview', headers={'Range': 'bytes=1-4'})[:2], (206, b'1234'))

    def test_approval_requires_explicit_review_and_never_uploads(self):
        data = self.approval()
        with patch.object(self.server.activity, 'start') as start, patch('builtins.input') as prompt:
            self.assertEqual(self.action('approve', dict(data, reviewed=False))[0], 400)
            self.assertEqual(self.action('approve', dict(data, confirmation=''))[0], 400)
            self.assertEqual(self.action('approve', data)[0], 200)
            self.assertEqual(agent.require_approved(self.folder)['status'], 'APPROVED')
            prompt.assert_not_called()
            start.assert_not_called()

    def test_selected_scene_preview_and_visual_edit_require_new_approval(self):
        self.action('approve', self.approval())
        item = script()
        item['scenes'][1]['visual_description'] = 'Río y bosque amazónico al atardecer.'
        with patch.object(self.server.activity, 'start', return_value={'status': 'RUNNING'}) as start:
            self.assertEqual(self.action('save-script', {'script': item, 'script_hash': ui.script_hash(self.folder)})[0], 200)
            start.assert_not_called()  # Guardar una imagen distinta no consume API.
            self.assertNotIn('approved_hash', self.state())
            self.assertNotIn('render_hash', self.state())
            self.assertEqual(self.action('approve', self.approval())[0], 400)
            saved = self.request('/api/jobs/video-test')[1]['script']
            self.assertEqual(saved['scenes'][1], item['scenes'][1])
            self.assertEqual(self.action('preview', {'scene': 2})[0], 200)
            self.assertEqual(start.call_args.args[1], [['muestra', 'video-test', '--escena', '2']])
            for number in (True, 0, 4, -1, '2', [], None):
                start.reset_mock()
                self.assertEqual(self.action('preview', {'scene': number})[0], 400)
                start.assert_not_called()

    def test_demo_and_stale_review_cannot_be_approved(self):
        data = self.approval()
        self.state(demo=True)
        self.assertEqual(self.action('approve', data)[0], 400)
        self.state(demo=False)
        (self.folder / 'video.mp4').write_bytes(b'new video')
        self.state(render_hash=agent.render_digest(self.folder))
        self.assertEqual(self.action('approve', data)[0], 400)
        self.assertNotIn('approved_hash', self.state())

    def test_publish_requires_approval_confirmation_and_approved_version(self):
        with patch.object(self.server.activity, 'start', return_value={'status': 'RUNNING'}) as start:
            self.assertEqual(self.action('publish', {'confirmation': 'SUBIR'})[0], 400)
            self.action('approve', self.approval())
            data = {'confirmation': 'SUBIR', 'approved_hash': self.state()['approved_hash']}
            self.assertEqual(self.action('publish', dict(data, confirmation=''))[0], 400)
            self.assertEqual(self.action('publish', dict(data, approved_hash='old'))[0], 400)
            start.assert_not_called()
            self.assertEqual(self.action('publish', data)[0], 200)
            self.assertEqual(start.call_args.args[1], [['publicar', 'video-test']])
            self.assertFalse((self.folder / '.lock').exists())

    def test_edit_invalidates_approval_and_rejects_concurrent_edit(self):
        self.action('approve', self.approval())
        edit = script()
        edit['title'] = 'Título corregido'
        data = {'script': edit, 'script_hash': ui.script_hash(self.folder)}
        self.assertEqual(self.action('save-script', data)[0], 200)
        state = self.state()
        self.assertEqual(state['status'], 'RESEARCHED')
        self.assertNotIn('approved_hash', state)
        self.assertNotIn('render_hash', state)
        self.assertEqual(self.action('save-script', data)[0], 400)
        self.assertEqual(self.action('approve', self.approval())[0], 400)

    def test_active_and_uploaded_jobs_cannot_be_changed(self):
        for state in ('UPLOADING', 'UPLOADED', 'RESEARCHING', 'GENERATING'):
            self.state(status=state)
            for action in ('approve', 'reject', 'save-script'):
                with self.subTest(state=state, action=action):
                    self.assertEqual(self.action(action, self.approval())[0], 400)
                    self.assertEqual(self.state()['status'], state)

    def test_existing_operation_blocks_mutations(self):
        self.server.activity.value = {'status': 'RUNNING'}
        self.assertEqual(self.action('reject', {})[0], 400)
        self.assertEqual(self.state()['status'], 'REVIEW')
        self.assertEqual(self.request('/api/create', {'mode': 'demo'})[0], 400)

    def test_failed_research_retries_in_same_folder(self):
        self.state(status='ERROR', last_error={'phase': 'RESEARCHING'})
        with patch.object(self.server.activity, 'start', return_value={'status': 'RUNNING'}) as start:
            self.assertEqual(self.action('retry', {})[0], 200)
            self.assertEqual(start.call_args.args[1], [['investigar', '--reanudar', 'video-test'],
                                                      ['generar', 'video-test']])

    def test_retry_allows_length_repair_but_regenerate_preserves_manual_script(self):
        self.state(status='ERROR', last_error={'phase': 'GENERATING'})
        with patch.object(self.server.activity, 'start', return_value={'status': 'RUNNING'}) as start:
            self.assertEqual(self.action('retry', {})[0], 200)
            self.assertEqual(start.call_args.args[1], [['generar', 'video-test', '--usar-guion', '--corregir-guion']])
            self.assertEqual(self.action('regenerate', {})[0], 200)
            self.assertEqual(start.call_args.args[1], [['generar', 'video-test', '--usar-guion']])
            self.state(demo=True)
            self.assertEqual(self.action('retry', {})[0], 200)
            self.assertEqual(start.call_args.args[1], [['generar', 'video-test', '--usar-guion']])

    def test_broken_job_does_not_hide_other_jobs(self):
        broken = agent.DATA / 'broken'
        broken.mkdir()
        agent.save(broken / 'state.json', [])
        code, body, _ = self.request('/api/jobs')
        self.assertEqual(code, 200)
        self.assertEqual(len(body['jobs']), 2)
        self.assertEqual(self.request('/api/jobs/broken')[0], 400)

    def proposal_job(self):
        from test_topics import topics
        self.state(status='TOPICS_REVIEW', kind='topic_proposals')
        agent.save(self.folder / 'topics.json', topics())
        (self.folder / 'research.md').write_text('Investigación para elegir un tema.', encoding='utf-8')

    def test_proposals_require_confirmation_and_create_only_one_selected_job(self):
        self.proposal_job()
        detail = self.request('/api/jobs/video-test')[1]
        self.assertEqual(len(detail['topics']), 3)
        payload = {'number': 1, 'confirmed': True, 'topics_hash': detail['topics_hash']}
        with patch.object(self.server.activity, 'start', return_value={'status': 'RUNNING'}) as start:
            self.assertEqual(self.action('select-topic', {**payload, 'confirmed': False})[0], 400)
            self.assertEqual(self.action('select-topic', {**payload, 'topics_hash': 'old'})[0], 400)
            start.assert_not_called()
            code, result, _ = self.action('select-topic', payload)
            self.assertEqual(code, 200)
            self.assertEqual(result['job_id'], 'video-test-tema-1')
            self.assertEqual(start.call_args.args[1], [['continuar-tema', 'video-test-tema-1']])
            self.assertEqual(self.action('select-topic', payload)[0], 400)
            start.assert_called_once()
        state = agent.load(agent.DATA / result['job_id'] / 'state.json')
        self.assertEqual(state['status'], 'TOPIC_APPROVED')
        self.assertNotIn('approved_hash', state)

    def test_proposal_actions_cannot_generate_or_publish_and_retry_only_researches(self):
        self.proposal_job()
        with patch.object(self.server.activity, 'start', return_value={'status': 'RUNNING'}) as start:
            for action in ('regenerate', 'preview', 'approve', 'publish', 'save-script'):
                with self.subTest(action=action):
                    self.assertEqual(self.action(action, {})[0], 400)
            start.assert_not_called()
            self.state(status='ERROR', last_error={'phase': 'TOPIC_RESEARCHING'})
            self.assertEqual(self.action('retry', {})[0], 200)
            self.assertEqual(start.call_args.args[1], [['proponer', '--reanudar', 'video-test']])


if __name__ == '__main__':
    unittest.main()
