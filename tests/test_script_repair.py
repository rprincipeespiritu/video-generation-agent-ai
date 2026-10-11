import json
from unittest.mock import Mock, patch
from fixtures import agent, JobTestCase, script


def draft(words=74):
    item = script()
    item['scenes'] = [dict(item['scenes'][0], heading=f'Parte {i + 1}',
                           narration=' '.join(['dato'] * words)) for i in range(14)]
    return item


def revision(words=105):
    return Mock(status='completed', output_text=json.dumps({
        'narrations': [' '.join(['explicación'] * words) for _ in range(14)]}))


class ScriptRepairTests(JobTestCase):
    def setUp(self):
        super().setUp()
        self.original = draft()
        agent.save(self.folder / 'script.json', self.original)
        state = self.state()
        state['target_seconds'] = 600
        agent.save(self.folder / 'state.json', state)
        self.api = Mock()
        self.api.responses.create.return_value = revision()

    def test_short_draft_repaired_preserving_title_scenes_sources_and_original(self):
        agent.repair_script_length(self.folder, api=self.api)
        saved = agent.load(self.folder / 'script.json')
        agent.validate_long_script(saved)
        self.assertEqual(saved['title'], self.original['title'])
        self.assertEqual(saved['description'], self.original['description'])
        for before, after in zip(self.original['scenes'], saved['scenes']):
            for field in ('heading', 'bullets', 'sources'):
                self.assertEqual(before[field], after[field])
        backup = next((self.folder / 'script_repairs').glob('*/original.json'))
        self.assertEqual(agent.load(backup), self.original)
        self.api.responses.create.assert_called_once()

    def test_long_draft_also_repaired(self):
        agent.save(self.folder / 'script.json', draft(125))
        agent.repair_script_length(self.folder, api=self.api)
        agent.validate_long_script(agent.load(self.folder / 'script.json'))

    def test_valid_script_makes_no_extra_calls(self):
        item = draft(105)
        agent.save(self.folder / 'script.json', item)
        agent.repair_script_length(self.folder, api=self.api)
        self.api.responses.create.assert_not_called()
        self.assertFalse((self.folder / 'script_repairs').exists())
        self.assertEqual(agent.load(self.folder / 'script.json'), item)

    def test_two_unsuccessful_corrections_stop_before_audio_and_keep_original(self):
        self.api.responses.create.return_value = revision(70)
        with patch.object(agent, 'client', return_value=self.api), patch.object(agent, 'render') as render:
            with self.assertRaisesRegex(agent.ScriptError, 'tras 2 correcciones'):
                agent.generate(self.folder, use_script=True, repair_script=True)
        self.assertEqual(self.api.responses.create.call_count, 2)
        render.assert_not_called()
        self.assertEqual(agent.load(self.folder / 'script.json'), self.original)
        self.assertEqual(self.state()['status'], 'ERROR')
        self.assertIn('correcciones', self.state()['last_error']['message'])

    def test_wrong_scene_count_then_valid_response_does_not_truncate_scenes(self):
        self.api.responses.create.side_effect = [
            Mock(status='completed', output_text='{"narrations":["incompleta"]}'), revision()]
        agent.repair_script_length(self.folder, api=self.api)
        self.assertEqual(len(agent.load(self.folder / 'script.json')['scenes']), 14)
        self.assertEqual(self.api.responses.create.call_count, 2)

    def test_concurrent_edit_during_request_is_preserved(self):
        edited = draft()
        edited['title'] = 'Edición del usuario durante la solicitud'

        def respond(**kwargs):
            agent.save(self.folder / 'script.json', edited)
            return revision()
        self.api.responses.create.side_effect = respond
        with self.assertRaisesRegex(agent.ScriptError, 'cambió durante'):
            agent.repair_script_length(self.folder, api=self.api)
        self.assertEqual(agent.load(self.folder / 'script.json'), edited)
        self.api.responses.create.assert_called_once()

    def test_new_script_is_automatically_repaired_before_generation(self):
        self.api.responses.create.side_effect = [
            Mock(status='completed', output_text=json.dumps(self.original)), revision()]
        with patch.object(agent, 'client', return_value=self.api):
            agent.make_script(self.folder, 'Tema elegido')
        agent.validate_long_script(agent.load(self.folder / 'script.json'))
        self.assertEqual(self.api.responses.create.call_count, 2)

    def test_reusing_manual_script_does_not_rewrite_it_without_repair_option(self):
        with patch.object(agent, 'repair_script_length') as repair, patch.object(agent, 'render',
                side_effect=agent.ScriptError('Guion corto')), self.assertRaises(agent.ScriptError):
            agent.generate(self.folder, use_script=True)
        repair.assert_not_called()
        self.assertEqual(agent.load(self.folder / 'script.json'), self.original)

    def test_recovery_invalidates_approval_and_finishes_at_review(self):
        self.mark_approved()
        with patch.object(agent, 'client', return_value=self.api), patch.object(agent, 'render',
                return_value={'duration_seconds': 600}), patch.object(agent, 'publish') as publish:
            agent.generate(self.folder, use_script=True, repair_script=True)
        self.assertEqual(self.state()['status'], 'REVIEW')
        self.assertNotIn('approved_hash', self.state())
        publish.assert_not_called()
