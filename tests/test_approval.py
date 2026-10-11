import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        for name in ('video.mp4', 'script.json', 'sources.json', 'publication.json'):
            (self.folder / name).write_bytes(b'original')
        self.state = {'status': 'APPROVED', 'demo': False, 'approved_hash': agent.digest(self.folder)}
        agent.save(self.folder / 'state.json', self.state)

    def test_approved_unchanged(self):
        self.assertEqual(agent.require_approved(self.folder)['status'], 'APPROVED')

    def test_every_content_change_blocks_upload(self):
        for name in ('video.mp4', 'script.json', 'sources.json', 'publication.json'):
            with self.subTest(name=name):
                (self.folder / name).write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    agent.require_approved(self.folder)
                (self.folder / name).write_bytes(b'original')

    def test_unapproved_rejected_uncertain_and_uploaded_blocked(self):
        for status in ('REVIEW', 'REJECTED', 'UPLOADING', 'UPLOADED'):
            with self.subTest(status=status):
                agent.save(self.folder / 'state.json', dict(self.state, status=status))
                with self.assertRaises(ValueError):
                    agent.require_approved(self.folder)

    def test_demo_blocked(self):
        agent.save(self.folder / 'state.json', dict(self.state, demo=True))
        with self.assertRaises(ValueError):
            agent.require_approved(self.folder)

    def test_parallel_operation_blocked(self):
        with agent.lock(self.folder):
            with self.assertRaises(ValueError):
                with agent.lock(self.folder):
                    pass


if __name__ == '__main__':
    unittest.main()
