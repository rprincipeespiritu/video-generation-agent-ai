import os
from unittest.mock import patch
from fixtures import agent, JobTestCase, script


class RenderTests(JobTestCase):
    def test_failed_assembly_preserves_previous_video(self):
        before = (self.folder / 'video.mp4').read_bytes()
        # Los comandos se simulan: este caso comprueba el fallo antes de reemplazar el MP4.
        with patch.object(agent, 'run'), patch.object(agent, 'inspect_video', side_effect=ValueError('MP4 roto')):
            with patch.object(agent, 'client', side_effect=AssertionError('No debe llamar a OpenAI')):
                with self.assertRaisesRegex(ValueError, 'MP4 roto'):
                    agent.render(self.folder, demo=True)
        self.assertEqual((self.folder / 'video.mp4').read_bytes(), before)

    def test_missing_custom_ffmpeg_fails_clearly(self):
        with patch.dict(os.environ, {'FFMPEG_PATH': str(self.folder / 'missing.exe')}):
            with self.assertRaisesRegex(ValueError, 'FFMPEG_PATH'):
                agent.render(self.folder, demo=True)

    def test_concurrent_script_edit_does_not_produce_reviewable_job(self):
        def edit(_folder, demo):
            item = script()
            item['title'] = 'Cambio durante montaje'
            agent.save(self.folder / 'script.json', item)
            return {'duration_seconds': 150}
        with patch.object(agent, 'render', side_effect=edit), self.assertRaisesRegex(ValueError, 'durante'):
            agent.generate(self.folder, use_script=True)
        self.assertEqual(self.state()['status'], 'ERROR')
        with self.assertRaises(ValueError):
            agent.require_approved(self.folder)

    def test_demo_failure_can_retry_without_openai(self):
        state = self.state()
        state.update(demo=True, status='ERROR', last_error={'phase': 'GENERATING'})
        agent.save(self.folder / 'state.json', state)
        with patch.object(agent, 'make_script', side_effect=AssertionError('No debe crear guion con API')):
            with patch.object(agent, 'render', return_value={'duration_seconds': 9}) as render:
                agent.generate(self.folder)
        render.assert_called_once_with(self.folder, demo=True)
        self.assertEqual(self.state()['status'], 'REVIEW')
        with self.assertRaises(ValueError):
            agent.require_approved(self.folder)
