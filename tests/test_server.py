"""Contrato del despliegue: autenticación, persistencia y dos aprobaciones humanas."""
import base64
from datetime import datetime
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from fixtures import agent, script, sources
import server
import ui


class ProductionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        values = {'APP_ENV': 'production', 'ADMIN_PASSWORD': 'test-only-password-123456789',
                  'PUBLIC_URL': 'https://studio.example.test', 'OPENAI_API_KEY': '',
                  'VIDEO_DATA_DIR': str(self.root / 'data'), 'VIDEO_CONFIG_DIR': str(self.root / 'config')}
        for patcher in (patch.dict(os.environ, values, clear=True), patch.object(agent, 'DATA', self.root / 'data')):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = server.create_app()
        self.client = self.app.test_client()
        self.runtime = self.app.extensions['video_runtime']
        self.auth = 'Basic ' + base64.b64encode(b'admin:test-only-password-123456789').decode()

    def request(self, path, data=None, headers=None, auth=True):
        opts = {'X-Local-Token': self.runtime.token}
        if auth:
            opts['Authorization'] = self.auth
        opts.update(headers or {})
        response = self.client.open(path, method='GET' if data is None else 'POST', json=data,
                                    base_url='https://studio.example.test', headers=opts)
        self.addCleanup(response.close)
        return response

    def video(self):
        folder = agent.DATA / 'video-test'
        folder.mkdir()
        agent.save(folder / 'script.json', script())
        agent.save(folder / 'sources.json', sources())
        (folder / 'video.mp4').write_bytes(b'0123456789')
        agent.save(folder / 'state.json', {'status': 'REVIEW', 'render_hash': agent.render_digest(folder)})
        return folder

    def test_health_public_but_every_private_surface_requires_auth(self):
        self.assertEqual(self.request('/healthz', auth=False, headers={'Host': 'healthcheck.railway.app'}).status_code, 200)
        for path in ('/', '/app.js', '/api/session', '/api/jobs', '/api/status', '/media/video-test/video'):
            with self.subTest(path=path):
                response = self.request(path, auth=False)
                self.assertEqual(response.status_code, 401)
                self.assertIn('Basic', response.headers['WWW-Authenticate'])
        self.assertEqual(self.request('/').status_code, 200)
        self.assertEqual(self.request('/api/session').json['token'], self.runtime.token)
        self.assertEqual(self.request('/api/session', headers={'Authorization': 'Basic broken'}).status_code, 401)

    def test_host_https_origin_and_csrf_reject_before_any_action(self):
        with patch.object(self.runtime.activity, 'start') as start:
            for headers in ({'Host': 'evil.test'}, {'X-Forwarded-Proto': 'http'},
                            {'Origin': 'https://evil.test'}, {'Sec-Fetch-Site': 'cross-site'},
                            {'X-Local-Token': ''}, {'X-Local-Token': 'stale-session'}):
                with self.subTest(headers=headers):
                    self.assertEqual(self.request('/api/create', {'mode': 'demo'}, headers).status_code, 403)
            start.assert_not_called()
        self.assertEqual(self.request('/api/session', headers={'X-Forwarded-Host': 'evil.test'}).status_code, 200)

    def test_config_blocks_secret_changes_and_persists_preferences(self):
        self.assertEqual(self.request('/api/config', {'openai_key': 'not-a-real-key'}).status_code, 400)
        self.assertEqual(self.request('/api/production', {'voice': 'onyx', 'visual_mode': 'slides'}).status_code, 200)
        with patch.dict(os.environ, {'TTS_VOICE': 'cedar'}):
            restarted = server.create_app()
            self.assertEqual(agent.production.settings()['voice'], 'onyx')
        self.assertIsNotNone(restarted)
        response = self.request('/api/status')
        self.assertTrue(response.json['configuration']['cloud'])
        self.assertNotIn('test-only-password', response.get_data(as_text=True))

    def test_files_and_media_ranges(self):
        self.video()
        for path in ('/.env', '/server.py', '/config/youtube_token.json', '/media/video-test/state.json',
                     '/media/%2e%2e/video', '/api/jobs/%2e%2e'):
            with self.subTest(path=path):
                self.assertIn(self.request(path).status_code, (400, 404))
        response = self.request('/media/video-test/video', headers={'Range': 'bytes=2-5'})
        self.assertEqual((response.status_code, response.data), (206, b'2345'))
        self.assertEqual(response.headers['Content-Range'], 'bytes 2-5/10')
        self.assertEqual(self.request('/media/video-test/video', headers={'Range': 'bytes=50-'}).status_code, 416)

    def test_approval_and_upload_remain_separate_in_production(self):
        folder = self.video()
        with patch.object(self.runtime.activity, 'start', return_value={'status': 'RUNNING'}) as start:
            self.assertEqual(self.request('/api/jobs/video-test/publish', {'confirmation': 'SUBIR'}).status_code, 400)
            approval = {'reviewed': True, 'confirmation': 'APROBAR', 'review_hash': agent.render_digest(folder),
                        'publication': {'channel_id': 'UC' + 'a' * 22, 'privacy': 'private',
                                        'made_for_kids': False, 'synthetic_media': True}}
            self.assertEqual(self.request('/api/jobs/video-test/approve', approval).status_code, 200)
            start.assert_not_called()
            state = agent.load(folder / 'state.json')
            self.assertEqual(state['status'], 'APPROVED')
            payload = {'confirmation': 'SUBIR', 'approved_hash': state['approved_hash']}
            self.assertEqual(self.request('/api/jobs/video-test/publish', payload).status_code, 200)
            self.assertEqual(start.call_args.args[1], [['publicar', 'video-test']])

    def test_proposal_selection_cannot_be_skipped_in_cloud(self):
        from test_topics import topics
        folder = self.video()
        agent.save(folder / 'state.json', {'kind': 'topic_proposals', 'status': 'TOPICS_REVIEW'})
        agent.save(folder / 'topics.json', topics())
        (folder / 'research.md').write_text('Research', encoding='utf-8')
        with patch.object(self.runtime.activity, 'start', return_value={'status': 'RUNNING'}) as start:
            self.assertEqual(self.request('/api/jobs/video-test/regenerate', {}).status_code, 400)
            payload = {'confirmed': False, 'number': 1, 'topics_hash': agent.topics_hash(folder)}
            self.assertEqual(self.request('/api/jobs/video-test/select-topic', payload).status_code, 400)
            start.assert_not_called()
            payload['confirmed'] = True
            response = self.request('/api/jobs/video-test/select-topic', payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(start.call_args.args[1], [['continuar-tema', 'video-test-tema-1']])

    def test_fail_closed_for_missing_password_https_and_volume(self):
        for changes in ({'ADMIN_PASSWORD': ''}, {'PUBLIC_URL': 'http://studio.test'},
                        {'PUBLIC_URL': 'https://studio.test/path'}, {'VIDEO_DATA_DIR': 'relative'},
                        {'VIDEO_CONFIG_DIR': str(agent.DATA / 'config')}, {'RAILWAY_ENVIRONMENT_ID': 'test'},
                        {'DAILY_RESEARCH_ENABLED': 'typo'}, {'RAILWAY_VOLUME_MOUNT_PATH': str(self.root / 'absent')}):
            with self.subTest(changes=changes), patch.dict(os.environ, changes), self.assertRaises(ValueError):
                server.create_app()

    def test_daily_clock_reservation_survives_restarts_and_does_not_generate(self):
        timezone = ZoneInfo('America/Lima')
        before = datetime(2026, 10, 12, 5, 59, tzinfo=timezone)
        due = datetime(2026, 10, 12, 6, 0, tzinfo=timezone)
        scheduler = server.DailyResearch(self.runtime)
        with patch.object(self.runtime.activity, 'start', return_value={}) as start:
            scheduler.tick(due)
            start.assert_not_called()  # Desactivado por defecto.
            with patch.dict(os.environ, {'DAILY_RESEARCH_ENABLED': 'true'}):
                scheduler.tick(before)
                start.assert_not_called()
                self.runtime.activity.value = {'status': 'RUNNING'}
                scheduler.tick(due)
                start.assert_not_called()
                self.runtime.activity.value = None
                scheduler.tick(due)
                self.assertEqual(start.call_args.args[1], [['diario']])
                scheduler.tick(due)
                server.DailyResearch(self.runtime).tick(due)
                start.assert_called_once()
                (agent.DATA / 'propuestas-2026-10-13').mkdir()
                scheduler.tick(datetime(2026, 10, 13, 7, tzinfo=timezone))
                start.assert_called_once()

    def test_restart_keeps_jobs_and_reports_interruption_without_paid_retry(self):
        self.video()
        path = agent.private_file('activity.json')
        agent.save(path, {'status': 'RUNNING', 'lines': ['Working']})
        with patch('subprocess.Popen') as process:
            recreated = server.create_app()
            state = recreated.extensions['video_runtime'].activity.snapshot()
            self.assertEqual(state['status'], 'ERROR')
            process.assert_not_called()
        self.assertEqual(agent.load(agent.DATA / 'video-test' / 'state.json')['status'], 'REVIEW')
        self.assertEqual(agent.load(path)['status'], 'ERROR')

    def test_shutdown_prevents_starting_the_next_paid_command(self):
        self.runtime.activity.value = {'status': 'RUNNING', 'lines': []}
        self.runtime.activity.stop()
        with patch('subprocess.Popen') as process:
            self.runtime.activity._run([['investigar'], ['generar', 'video-test']])
            process.assert_not_called()
            self.assertEqual(self.runtime.activity.snapshot()['status'], 'ERROR')
            with self.assertRaises(ValueError):
                self.runtime.activity.start('Generar', [['generar', 'video-test']])

    def test_cloud_oauth_never_opens_local_browser_and_rotates_provisioned_token(self):
        with patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file') as flow:
            with self.assertRaisesRegex(ValueError, 'YOUTUBE_TOKEN_JSON'):
                agent.youtube()
            with patch.dict(os.environ, {'YOUTUBE_TOKEN_JSON': 'malformed'}), self.assertRaises(ValueError):
                agent.youtube()
            flow.assert_not_called()
        credentials = Mock(valid=True)
        credentials.to_json.return_value = '{"token":"fake"}'
        with patch.dict(os.environ, {'YOUTUBE_TOKEN_JSON': '{"refresh_token":"test-1"}'}), \
                patch('google.oauth2.credentials.Credentials.from_authorized_user_info', return_value=credentials) as fresh, \
                patch('google.oauth2.credentials.Credentials.from_authorized_user_file', return_value=credentials) as saved, \
                patch('googleapiclient.discovery.build'):
            agent.youtube()
            agent.youtube()
            fresh.assert_called_once()
            saved.assert_called_once()
            with patch.dict(os.environ, {'YOUTUBE_TOKEN_JSON': '{"refresh_token":"test-2"}'}):
                agent.youtube()
            self.assertEqual(fresh.call_count, 2)

    def test_waitress_handles_proxy_headers_and_healthcheck(self):
        from waitress import create_server
        http_server = create_server(self.app, host='127.0.0.1', port=0, threads=2, clear_untrusted_proxy_headers=False)
        thread = threading.Thread(target=http_server.run, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection('127.0.0.1', http_server.effective_port, timeout=5)
        try:
            connection.request('GET', '/api/session', headers={'Host': 'studio.example.test',
                               'X-Forwarded-Proto': 'https', 'Authorization': self.auth})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())['token'], self.runtime.token)
        finally:
            connection.close()
            http_server.close()
            http_server.task_dispatcher.shutdown()
            thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
