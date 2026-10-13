import copy
import unittest
from fixtures import agent, script, sources


class ValidationTests(unittest.TestCase):
    def test_valid_script(self):
        agent.validate_script(script(), sources())

    def test_optional_visual_description_is_bounded_text(self):
        for value in ('', ' ', 'Río amazónico y bosque al atardecer.', 'x' * 1200):
            item = script()
            item['scenes'][0]['visual_description'] = value
            agent.validate_script(item, sources())
        for value in (None, 42, [], {}, 'x' * 1201):
            item = script()
            item['scenes'][0]['visual_description'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                agent.validate_script(item, sources())

    def test_invalid_root_and_required_fields(self):
        for value in (None, [], '', {}, {'title': None}, dict(script(), scenes='abc')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                agent.validate_script(value, sources())

    def test_scene_types_and_limits(self):
        invalid = {'heading': [None, 42, ' ', 'x' * 91],
                   'bullets': [None, 'abc', [], ['x'] * 4, [None], ['x' * 121], [' ']],
                   'narration': [None, [], ' ', 'x' * 1801],
                   'sources': [None, 'https://example.com/a', [], [{}], ['https://unlisted.example']]}
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    item = copy.deepcopy(script())
                    item['scenes'][0][key] = value
                    with self.assertRaises(ValueError):
                        agent.validate_script(item, sources())

    def test_missing_scene_fields(self):
        for key in script()['scenes'][0]:
            item = script()
            del item['scenes'][0][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                agent.validate_script(item, sources())

    def test_invalid_scene_count(self):
        for count in (0, 2, 25):
            item = script()
            item['scenes'] = [item['scenes'][0]] * count
            with self.subTest(count=count), self.assertRaises(ValueError):
                agent.validate_script(item, sources())

    def test_sources_must_be_http_catalog(self):
        for value in (None, {}, [], [None], [{}], [{'title': 'A', 'url': 'file:///secret'}],
                      [{'title': 'A', 'url': 'https://'}], [{'title': 'A', 'url': 'https://a b.com'}]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                agent.validate_script(script(), value)
