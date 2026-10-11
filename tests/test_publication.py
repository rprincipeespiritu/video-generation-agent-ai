from unittest.mock import Mock, patch
from fixtures import agent, JobTestCase


class PublicationTests(JobTestCase):
    def service(self):
        service = Mock()
        service.channels.return_value.list.return_value.execute.return_value = {
            'items': [{'id': 'UC_TEST', 'snippet': {'title': 'Canal simulado'}}]}
        return service

    def test_unapproved_never_connects(self):
        with patch.object(agent, 'youtube') as connect, self.assertRaises(ValueError):
            agent.publish(self.folder)
        connect.assert_not_called()

    def test_channel_mismatch_never_uploads(self):
        self.mark_approved()
        service = self.service()
        service.channels.return_value.list.return_value.execute.return_value = {
            'items': [{'id': 'WRONG', 'snippet': {'title': 'Otro'}}]}
        with patch.object(agent, 'youtube', return_value=service), self.assertRaises(ValueError):
            agent.publish(self.folder)
        service.videos.assert_not_called()

    def test_upload_success_uses_approved_metadata(self):
        self.mark_approved()
        service = self.service()
        request = service.videos.return_value.insert.return_value
        request.next_chunk.return_value = (None, {'id': 'fake-id', 'status': {'privacyStatus': 'private'}})
        with patch.object(agent, 'youtube', return_value=service), patch('googleapiclient.http.MediaFileUpload'):
            agent.publish(self.folder)
        self.assertEqual(self.state()['status'], 'UPLOADED')
        self.assertEqual(self.state()['youtube_id'], 'fake-id')
        body = service.videos.return_value.insert.call_args.kwargs['body']
        self.assertEqual(body['status']['privacyStatus'], 'private')
        self.assertEqual(body['snippet']['description'],
                         'Ejemplo local.\n\nFuentes:\nFuente A: https://example.com/a\nFuente B: https://example.com/b')
        self.assertFalse(body['status']['containsSyntheticMedia'])
        request.next_chunk.assert_called_once_with(num_retries=0)

    def test_upload_failure_stays_uncertain_and_blocks_retry(self):
        self.mark_approved()
        service = self.service()
        service.videos.return_value.insert.return_value.next_chunk.side_effect = ConnectionError('secret')
        with patch.object(agent, 'youtube', return_value=service), patch('googleapiclient.http.MediaFileUpload'):
            with self.assertRaises(ConnectionError):
                agent.publish(self.folder)
        self.assertEqual(self.state()['status'], 'UPLOADING')
        self.assertEqual(self.state()['last_error']['phase'], 'UPLOADING')
        with patch.object(agent, 'youtube') as connect, self.assertRaises(ValueError):
            agent.publish(self.folder)
        connect.assert_not_called()
