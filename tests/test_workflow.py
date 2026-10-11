from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch
import tempfile
from pathlib import Path
from fixtures import agent, JobTestCase, PUBLICATION, script


class WorkflowTests(JobTestCase):
    def test_provider_json_error_is_actionable_without_saving_private_body(self):
        import httpx
        from openai import BadRequestError
        message = ("Response input messages must contain the word 'json' in some form to use "
                   "'text.format' of type 'json_object'. private-provider-text sk-private-test")
        error = BadRequestError(message, response=httpx.Response(400, request=httpx.Request('POST', 'https://api.openai.com/v1/responses')),
                                body={'message': message, 'private': 'private-provider-text'})
        with patch.object(agent, 'render', side_effect=error), self.assertRaises(BadRequestError):
            agent.generate(self.folder, use_script=True)
        details = self.state()['last_error']
        self.assertEqual(details['http_status'], 400)
        self.assertEqual(details['reason'], 'json_input_required')
        self.assertIn('investigación', details['message'])
        saved = (self.folder / 'state.json').read_text()
        self.assertNotIn('private-provider-text', saved)
        self.assertNotIn('sk-private-test', saved)

    def test_unknown_provider_error_does_not_save_its_message(self):
        import httpx
        from openai import BadRequestError
        error = BadRequestError('private-provider-text',
                                response=httpx.Response(400, request=httpx.Request('POST', 'https://api.openai.com/v1/responses')),
                                body={'message': 'private-provider-text'})
        details = agent.error_details(error)
        self.assertEqual(details['http_status'], 400)
        self.assertIn('parámetros', details['message'])
        self.assertNotIn('private-provider-text', str(details))

    def test_generation_failure_invalidates_approval_and_can_retry(self):
        self.mark_approved()
        with patch.object(agent, 'render', side_effect=RuntimeError('private provider text')):
            with self.assertRaises(RuntimeError):
                agent.generate(self.folder, use_script=True)
        state = self.state()
        self.assertEqual(state['status'], 'ERROR')
        self.assertEqual(state['last_error']['phase'], 'GENERATING')
        self.assertNotIn('approved_hash', state)
        self.assertNotIn('private provider text', (self.folder / 'state.json').read_text())
        with patch.object(agent, 'render', return_value={'duration_seconds': 150}):
            agent.generate(self.folder, use_script=True)
        self.assertEqual(self.state()['status'], 'REVIEW')
        self.assertNotIn('last_error', self.state())

    def test_keyboard_interrupt_is_recorded(self):
        with patch.object(agent, 'render', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            agent.generate(self.folder, use_script=True)
        self.assertEqual(self.state()['status'], 'ERROR')
        self.assertEqual(self.state()['last_error']['type'], 'KeyboardInterrupt')

    def test_upload_states_cannot_generate(self):
        for status in ('UPLOADING', 'UPLOADED'):
            state = self.state()
            state['status'] = status
            agent.save(self.folder / 'state.json', state)
            with patch.object(agent, 'render') as render, self.assertRaises(ValueError):
                agent.generate(self.folder)
            render.assert_not_called()
            self.assertEqual(self.state()['status'], status)

    def test_cancelled_reapproval_clears_previous_approval(self):
        self.mark_approved()
        with patch('builtins.input', return_value='no'), self.assertRaises(ValueError):
            agent.approve(self.folder, PUBLICATION)
        self.assertEqual(self.state()['status'], 'REVIEW')
        self.assertNotIn('approved_hash', self.state())

    def test_script_edited_after_render_cannot_be_approved(self):
        item = script()
        item['scenes'][0]['narration'] = 'Narración modificada.'
        agent.save(self.folder / 'script.json', item)
        with patch('builtins.input') as prompt, self.assertRaisesRegex(ValueError, 'montaje'):
            agent.approve(self.folder, PUBLICATION)
        prompt.assert_not_called()

    def test_approval_and_change_during_prompt(self):
        with patch('builtins.input', return_value='APROBAR'):
            agent.approve(self.folder, PUBLICATION)
        self.assertEqual(agent.require_approved(self.folder)['status'], 'APPROVED')

        def edit(_):
            (self.folder / 'video.mp4').write_bytes(b'changed')
            return 'APROBAR'
        with patch('builtins.input', side_effect=edit), self.assertRaisesRegex(ValueError, 'durante'):
            agent.approve(self.folder, PUBLICATION)
        self.assertEqual(self.state()['status'], 'REVIEW')

    def test_failed_research_preserves_evidence_and_retries(self):
        with tempfile.TemporaryDirectory() as root, patch.object(agent, 'DATA', Path(root)):
            api = Mock()
            response = api.responses.create.return_value
            response.output_text = 'Evidencia insuficiente'
            response.model_dump.return_value = {'output': []}
            with patch.object(agent, 'client', return_value=api), self.assertRaises(ValueError):
                agent.investigate('Ciencia')
            folder = next(Path(root).iterdir())
            self.assertTrue((folder / 'research_response.json').exists())
            self.assertEqual(agent.load(folder / 'state.json')['status'], 'ERROR')
            self.assertFalse((folder / '.lock').exists())
            with self.assertRaisesRegex(ValueError, 'reanudar'):
                agent.generate(folder)
            self.assertEqual(agent.load(folder / 'state.json')['last_error']['phase'], 'RESEARCHING')
            response.model_dump.return_value = {'output': [{'content': [{'annotations': [
                {'type': 'url_citation', 'url': 'https://example.com/a', 'title': 'A'},
                {'type': 'url_citation', 'url': 'https://example.com/b', 'title': 'B'}]}]}]}
            with patch.object(agent, 'client', return_value=api):
                agent.investigate(resume=folder.name)
            self.assertEqual(agent.load(folder / 'state.json')['status'], 'RESEARCHED')
            self.assertIn('Ciencia', api.responses.create.call_args.kwargs['input'])
            self.assertEqual(len(list(Path(root).iterdir())), 1)

    def test_list_includes_orphan_and_malformed_folders(self):
        with tempfile.TemporaryDirectory() as root, patch.object(agent, 'DATA', Path(root)):
            (Path(root) / 'orphan').mkdir()
            broken = Path(root) / 'broken'
            broken.mkdir()
            (broken / 'state.json').write_text('{')
            output = StringIO()
            with redirect_stdout(output):
                agent.main(['listar'])
            self.assertIn('orphan ESTADO AUSENTE', output.getvalue())
            self.assertIn('broken ESTADO AUSENTE', output.getvalue())
