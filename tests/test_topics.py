import json
from unittest.mock import Mock, patch
from fixtures import agent, JobTestCase, sources


def topics():
    return [{'title': f'Tema {i + 1}', 'category': category, 'summary': 'Resumen contrastado.',
             'reason': 'Valor educativo para Perú.', 'event_date': 'Fecha documentada en las fuentes',
             'sources': [s['url'] for s in sources()]}
            for i, category in enumerate(('actualidad', 'actualidad', 'historia'))]


class TopicTests(JobTestCase):
    def setUp(self):
        super().setUp()
        agent.save(self.folder / 'state.json', {'status': 'TOPICS_REVIEW', 'kind': 'topic_proposals', 'demo': False})
        agent.save(self.folder / 'topics.json', topics())
        patcher = patch.object(agent, 'DATA', self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_proposals_stop_before_script_voice_images_or_publication(self):
        api = Mock()
        api.responses.create.return_value = Mock(output_text=json.dumps({'topics': topics()}), status='completed')
        with patch.object(agent, 'client', return_value=api), patch.object(agent, 'research') as research:
            with patch.object(agent, 'generate') as generate, patch.object(agent, 'publish') as publish:
                agent.propose_topics(self.folder)
        research.assert_called_once_with(self.folder, agent.DEFAULT_FOCUS, proposals=True)
        schema = api.responses.create.call_args.kwargs['text']['format']['schema']
        fields = schema['properties']['topics']['items']['properties']
        self.assertEqual(fields['reason']['maxLength'], 500)
        self.assertEqual(fields['summary']['maxLength'], 1200)
        self.assertEqual(self.state()['status'], 'TOPICS_REVIEW')
        self.assertNotIn('approved_hash', self.state())
        generate.assert_not_called()
        publish.assert_not_called()
        api.audio.speech.with_streaming_response.create.assert_not_called()
        api.images.generate.assert_not_called()

    def test_proposal_research_failure_is_recorded_without_generation(self):
        with patch.object(agent, 'research', side_effect=ValueError('Sin fuentes')):
            with patch.object(agent, 'generate') as generate, self.assertRaises(ValueError):
                agent.propose_topics(self.folder)
        self.assertEqual(self.state()['status'], 'ERROR')
        self.assertEqual(self.state()['last_error']['phase'], 'TOPIC_RESEARCHING')
        generate.assert_not_called()
        self.assertTrue((self.folder / 'research.md').exists())

    def test_validation_requires_both_categories_and_supported_distinct_sources(self):
        agent.validate_topics(topics(), sources())
        for variant in ('category', 'one-category', 'unknown-url', 'duplicate-url', 'wrong-type', 'empty'):
            items = topics()
            if variant == 'category':
                items[0]['category'] = 'otro'
            elif variant == 'one-category':
                for item in items:
                    item['category'] = 'historia'
            elif variant == 'unknown-url':
                items[0]['sources'][0] = 'https://inventada.example'
            elif variant == 'duplicate-url':
                items[0]['sources'] = [sources()[0]['url']] * 2
            elif variant == 'wrong-type':
                items[0]['sources'] = [{}]
            else:
                items = []
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                agent.validate_topics(items, sources())

    def test_approval_requires_confirmation_valid_number_and_current_proposals(self):
        for kwargs in ({}, {'confirmation': False}, {'confirmation': True, 'expected_hash': 'stale'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                agent.reserve_topic(self.folder, 1, **kwargs)
        for number in (0, 9, True, '1'):
            with self.subTest(number=number), self.assertRaises(ValueError):
                agent.reserve_topic(self.folder, number, confirmation=True)
        self.assertEqual(list(self.folder.glob('*-tema-*')), [])

    def test_choice_records_consent_without_approving_video_and_blocks_duplicates(self):
        fingerprint = agent.topics_hash(self.folder)
        with agent.lock(self.folder), patch.object(agent, 'client') as client:
            child = agent.reserve_topic(self.folder, 2, confirmation=True, expected_hash=fingerprint)
            with self.assertRaisesRegex(ValueError, 'ya tiene un trabajo'):
                agent.reserve_topic(self.folder, 2, confirmation=True, expected_hash=fingerprint)
        client.assert_not_called()
        state = agent.load(child / 'state.json')
        self.assertEqual(state['status'], 'TOPIC_APPROVED')
        self.assertEqual(state['requested_topic'], 'Tema 2')
        self.assertEqual(state['topic_approval']['proposals_hash'], fingerprint)
        self.assertNotIn('approved_hash', state)
        with self.assertRaises(ValueError):
            agent.require_approved(child)
        self.assertEqual(self.state()['selections']['2'], child.name)

    def test_generate_cannot_bypass_topic_selection(self):
        with patch.object(agent, 'client') as client, self.assertRaisesRegex(ValueError, 'aprueba un tema'):
            agent.generate(self.folder, use_script=True)
        client.assert_not_called()

    def test_only_confirmed_topic_can_start_and_it_stops_at_review(self):
        with self.assertRaises(ValueError):
            agent.continue_topic(self.folder)
        child = agent.reserve_topic(self.folder, 1, confirmation=True)

        def researched(**kwargs):
            state = agent.load(child / 'state.json')
            self.assertEqual(state['requested_topic'], 'Tema 1')
            state['status'] = 'RESEARCHED'
            agent.save(child / 'state.json', state)

        def generated(folder):
            state = agent.load(folder / 'state.json')
            state['status'] = 'REVIEW'
            agent.save(folder / 'state.json', state)

        with patch.object(agent, 'investigate', side_effect=researched) as investigate:
            with patch.object(agent, 'generate', side_effect=generated) as generate:
                with patch.object(agent, 'approve') as approve, patch.object(agent, 'publish') as publish:
                    agent.continue_topic(child)
                    with self.assertRaises(ValueError):
                        agent.continue_topic(child)
        investigate.assert_called_once_with(resume=child.name)
        generate.assert_called_once_with(child)
        approve.assert_not_called()
        publish.assert_not_called()
        self.assertEqual(agent.load(child / 'state.json')['status'], 'REVIEW')

    def test_simulation_cannot_be_approved(self):
        state = self.state()
        state['demo'] = True
        agent.save(self.folder / 'state.json', state)
        with self.assertRaises(ValueError):
            agent.reserve_topic(self.folder, 1, confirmation=True)
