import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


def sources():
    return [{'title': 'Fuente A', 'url': 'https://example.com/a'},
            {'title': 'Fuente B', 'url': 'https://example.com/b'}]


def script():
    return {'title': 'Noticia de prueba', 'description': 'Ejemplo local.', 'scenes': [
        {'heading': f'Escena {i}', 'bullets': ['Un dato comprobado'],
         'narration': 'Narración de prueba sobre un dato comprobado.',
         'sources': ['https://example.com/a']} for i in range(3)]}


PUBLICATION = {'channel_id': 'UC_TEST', 'privacy': 'private', 'made_for_kids': False, 'synthetic_media': False}


class JobTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        agent.save(self.folder / 'sources.json', sources())
        agent.save(self.folder / 'script.json', script())
        agent.save(self.folder / 'publication.json', PUBLICATION)
        (self.folder / 'research.md').write_text('Evidencia local.', encoding='utf-8')
        (self.folder / 'video.mp4').write_bytes(b'video simulado')
        agent.save(self.folder / 'state.json', {'status': 'REVIEW', 'demo': False,
                                               'render_hash': agent.render_digest(self.folder)})

    def state(self):
        return agent.load(self.folder / 'state.json')

    def mark_approved(self):
        state = self.state()
        state.update(status='APPROVED', approved_hash=agent.digest(self.folder), approved_at=agent.now())
        agent.save(self.folder / 'state.json', state)
