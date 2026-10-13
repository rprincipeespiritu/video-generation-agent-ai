import base64
import io
import math
import struct
import wave
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image
from fixtures import agent, JobTestCase, script
import production


def wav_bytes(seconds=0.4):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b''.join(struct.pack('<h', int(1000 * math.sin(i / 20)))
                                 for i in range(round(24000 * seconds))))
    return stream.getvalue()


class ProductionTests(JobTestCase):
    def setUp(self):
        super().setUp()
        self.opts = production.settings({})
        self.api = Mock()
        speech = self.api.audio.speech.with_streaming_response.create.return_value.__enter__ = Mock()
        speech.return_value.stream_to_file.side_effect = lambda path: path.write_bytes(wav_bytes())
        self.api.audio.speech.with_streaming_response.create.return_value.__exit__ = Mock(return_value=False)
        image = io.BytesIO()
        Image.new('RGB', (1536, 864), '#305a70').save(image, format='PNG')
        self.api.with_options.return_value.images.generate.return_value.data = [
            Mock(b64_json=base64.b64encode(image.getvalue()).decode())]

    def test_audio_reuse_and_voice_change(self):
        scene = script()['scenes'][0]
        first, duration = production.speech_asset(self.folder, scene, self.opts, self.api)
        second, _ = production.speech_asset(self.folder, scene, self.opts, self.api)
        self.assertEqual(first, second)
        self.assertAlmostEqual(duration, 0.4)
        self.api.audio.speech.with_streaming_response.create.assert_called_once()
        changed, _ = production.speech_asset(self.folder, scene, dict(self.opts, voice='marin'), self.api)
        self.assertNotEqual(changed, first)
        self.assertEqual(self.api.audio.speech.with_streaming_response.create.call_count, 2)

    def test_streamed_wav_with_provisional_size_is_normalized(self):
        raw = bytearray(wav_bytes())
        raw[4:8] = b'\xff' * 4
        raw[40:44] = b'\xff' * 4
        self.api.audio.speech.with_streaming_response.create.return_value.__enter__.return_value.stream_to_file.side_effect = (
            lambda path: path.write_bytes(raw))
        path, seconds = production.speech_asset(self.folder, script()['scenes'][0], self.opts, self.api)
        self.assertAlmostEqual(seconds, 0.4)
        with wave.open(str(path), 'rb') as wav:
            self.assertEqual(wav.getnframes(), 9600)

    def test_image_cache_invalidation_and_no_text_prompt(self):
        item = script()
        first = production.image_asset(self.folder, item, item['scenes'][0], self.opts, self.api)
        again = production.image_asset(self.folder, item, item['scenes'][0], self.opts, self.api)
        self.assertEqual(first, again)
        image_call = self.api.with_options.return_value.images.generate
        image_call.assert_called_once()
        self.assertIn('Sin texto', image_call.call_args.kwargs['prompt'])
        item['scenes'][0]['narration'] += ' Cambió la escena.'
        changed = production.image_asset(self.folder, item, item['scenes'][0], self.opts, self.api)
        self.assertNotEqual(changed, first)
        self.assertEqual(image_call.call_count, 2)

    def test_corrupted_cached_asset_is_recreated(self):
        scene = script()['scenes'][0]
        first, _ = production.speech_asset(self.folder, scene, self.opts, self.api)
        first.write_bytes(b'corrupted')
        production.speech_asset(self.folder, scene, self.opts, self.api)
        self.assertEqual(self.api.audio.speech.with_streaming_response.create.call_count, 2)
        production.wav_data(first)

    def test_exact_frame_budget_without_drifting_per_scene(self):
        counts, ratio = production.scene_frames([45.7] * 14, 600)
        self.assertEqual(sum(counts), 600 * production.FPS)
        self.assertAlmostEqual(ratio, 45.7 * 14 / 600)
        for seconds in ([20] * 14, [100] * 14, [0], [float('nan')]):
            with self.assertRaises(ValueError):
                production.scene_frames(seconds, 600)

    def test_failed_images_preserve_existing_video(self):
        self.api.with_options.return_value.images.generate.side_effect = ValueError('Sin imagen')
        before = (self.folder / 'video.mp4').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Sin imagen'):
            production.render(self.folder, script(), self.opts, self.api, agent.ffmpeg_executable(),
                              agent.run, agent.inspect_video, agent.draw_slide)
        self.assertEqual((self.folder / 'video.mp4').read_bytes(), before)
        self.assertTrue(list((self.folder / 'assets').glob('voice-*.wav')))
        self.assertFalse(list(self.folder.glob('.render-*')))

    def test_fifth_image_failure_keeps_assets_and_explicit_retry_only_requests_missing_ones(self):
        import httpx
        from openai import BadRequestError
        item = script()
        item['scenes'] = [dict(item['scenes'][0], heading=f'Escena {i}',
                               narration=f'Contenido educativo diferente para la escena {i}.') for i in range(6)]
        agent.save(self.folder / 'script.json', item)
        self.mark_approved()
        original_video = (self.folder / 'video.mp4').read_bytes()
        images = self.api.with_options.return_value.images.generate
        result = images.return_value
        error = BadRequestError('private-provider-text', response=httpx.Response(
            400, request=httpx.Request('POST', 'https://api.openai.com/v1/images/generations')),
            body={'code': 'moderation_blocked', 'type': 'image_generation_user_error'})

        def image_response(**kwargs):
            if images.call_count == 5:
                raise error
            return result

        images.side_effect = image_response
        output = io.StringIO()
        # Se prueban persistencia y recuperación; FFmpeg ya tiene una prueba real independiente.
        with patch.object(agent, 'client', return_value=self.api), \
                patch.object(production, 'settings', return_value=self.opts), \
                patch.object(agent, 'ffmpeg_executable', return_value='ffmpeg'), \
                patch.object(production.subprocess, 'run', return_value=Mock(stdout='')), \
                patch.object(agent, 'run', side_effect=lambda *args: Path(args[-1]).write_bytes(b'mp4')), \
                patch.object(agent, 'inspect_video', return_value=58 / production.FPS), \
                redirect_stdout(output), redirect_stderr(output):
            with self.assertRaises(BadRequestError):
                agent.generate(self.folder, use_script=True)
            self.assertEqual(images.call_count, 5)  # Ningún reintento automático del rechazo.
            details = self.state()['last_error']
            self.assertEqual((details['stage'], details['scene'], details['scene_count']), ('image', 5, 6))
            self.assertEqual(details['reason'], 'content_rejected')
            self.assertNotIn('approved_hash', self.state())
            self.assertEqual((self.folder / 'video.mp4').read_bytes(), original_video)
            self.assertEqual(len(list((self.folder / 'assets').glob('voice-*.wav'))), 6)
            self.assertEqual(len(list((self.folder / 'assets').glob('image-*.png'))), 4)
            self.assertFalse(list(self.folder.glob('.render-*')))
            # Simula que el problema externo se resolvió y el usuario decide reintentar.
            agent.generate(self.folder, use_script=True)
        self.assertEqual(images.call_count, 7)  # Solo escenas 5 y 6 en el segundo intento.
        self.assertEqual(self.api.audio.speech.with_streaming_response.create.call_count, 6)
        self.api.with_options.assert_called_with(timeout=300, max_retries=0)
        self.assertEqual(self.state()['status'], 'REVIEW')
        self.assertNotIn('last_error', self.state())
        self.assertNotIn('approved_hash', self.state())
        self.assertIn('Ilustración · escena 5/6', output.getvalue())
        self.assertIn('Imagen guardada: reutilizada sin llamada', output.getvalue())
        self.assertIn('Audio guardado: reutilizado sin llamada', output.getvalue())
        self.assertNotIn('private-provider-text', output.getvalue())

    def test_voice_failure_records_scene_before_image_requests(self):
        self.api.audio.speech.with_streaming_response.create.side_effect = RuntimeError('private text')
        with self.assertRaises(RuntimeError) as caught:
            production.render(self.folder, script(), self.opts, self.api, agent.ffmpeg_executable(),
                              agent.run, agent.inspect_video, agent.draw_slide)
        details = agent.error_details(caught.exception)
        self.assertEqual((details['stage'], details['scene'], details['scene_count']), ('voice', 1, 3))
        self.assertNotIn('private text', str(details))
        self.api.with_options.return_value.images.generate.assert_not_called()

    def test_invalid_image_response_keeps_scene_context_in_saved_job(self):
        self.api.with_options.return_value.images.generate.return_value.data = []
        with patch.object(agent, 'client', return_value=self.api), \
                patch.object(production, 'settings', return_value=self.opts), \
                self.assertRaises(agent.ScriptError):
            agent.generate(self.folder, use_script=True)
        details = self.state()['last_error']
        self.assertEqual(details['stage'], 'image')
        self.assertEqual(details['scene'], 1)
        self.assertIn('No se recibió una imagen', details['message'])

    def test_real_ffmpeg_preview_and_exact_duration_assembly_without_apis(self):
        before_video = (self.folder / 'video.mp4').read_bytes()
        before_state = self.state()
        report = production.render(self.folder, script(), self.opts, self.api, agent.ffmpeg_executable(),
                                   agent.run, agent.inspect_video, agent.draw_slide, preview=True)
        self.assertEqual(report['audio_processing'], 'original')
        self.assertEqual(report['voice'], 'cedar')
        self.assertTrue((self.folder / 'preview.mp4').is_file())
        self.assertEqual((self.folder / 'video.mp4').read_bytes(), before_video)
        self.assertEqual(self.state(), before_state)
        run_calls = []

        def run(*args):
            run_calls.append(args)
            agent.run(*args)
        report = production.render(self.folder, script(), self.opts, self.api, agent.ffmpeg_executable(),
                                   run, agent.inspect_video, agent.draw_slide, target=1.125)
        self.assertEqual(report['status'], 'VERIFIED')
        self.assertLess(abs(report['duration_seconds'] - 1.125), 0.15)
        audio_calls = [args for args in run_calls if '-c:a' in args]
        self.assertEqual(len(audio_calls), 1)
        self.assertTrue(any('rubberband=' in part and 'formant=preserved' in part for part in audio_calls[0]))
        self.assertFalse(any('atempo=' in part for args in run_calls for part in args))

    def test_preview_uses_current_preferences_without_changing_approval(self):
        self.mark_approved()
        before = self.state()
        with patch.object(agent, 'client', return_value=self.api), patch.object(production, 'render') as render:
            agent.preview(self.folder)
        self.assertTrue(render.call_args.kwargs['preview'])
        self.assertEqual(self.state(), before)
