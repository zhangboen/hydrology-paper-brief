import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import joh_selection as js
from test_author_metadata import paper


class ExpertSelectionTests(unittest.TestCase):
    def setUp(self):
        self.papers = [paper(doi=f'10.1/{i}', title=f'Hydrology finding {i}', topic_rank=i)
                       for i in range(14)]

    def response(self, decisions):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({'selected': decisions})))])

    def choices(self):
        return [{'doi': p.doi, 'reason': '新的水文过程认识'} for p in self.papers[-10:][::-1]]

    def test_expert_order_beats_keyword_ranking_and_records_reasons(self):
        client = Mock()
        client.chat.completions.create.return_value = self.response(self.choices())
        with tempfile.TemporaryDirectory() as directory, patch.dict(js.os.environ, {'OPENAI_API_KEY': 'test'}, clear=True), patch.object(js, 'OpenAI', return_value=client):
            selected = js.choose_interesting_joh(self.papers, directory)
            audit = json.loads(next(Path(directory).glob('joh-selection-*.json')).read_text(encoding='utf8'))
        self.assertEqual(selected, self.papers[-10:][::-1])
        self.assertEqual(audit['candidate_count'], 14)
        self.assertEqual(audit['selected'], self.choices())
        kw = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kw['model'], 'gpt-5')
        self.assertNotIn('temperature', kw)
        payload = json.loads(kw['messages'][1]['content'])['papers']
        self.assertEqual(len(payload), 14)
        self.assertTrue(all(set(p) == {'doi', 'title', 'abstract'} for p in payload))
        client.close.assert_called_once()

    def test_ten_or_fewer_does_not_call_gpt(self):
        with patch.object(js, 'OpenAI') as client:
            self.assertEqual(js.choose_interesting_joh(self.papers[:10]), self.papers[:10])
        client.assert_not_called()

    def test_invalid_choices_retry_without_keyword_fallback(self):
        for bad in [self.choices()[:9], [self.choices()[0]]*10,
                    [{'doi': 'unknown', 'reason': 'interesting'}]*10,
                    [{'doi': p.doi, 'reason': ''} for p in self.papers[:10]]]:
            with self.subTest(bad=bad):
                client = Mock()
                client.chat.completions.create.side_effect = [self.response(bad), self.response(self.choices())]
                with patch.dict(js.os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(js, 'OpenAI', return_value=client):
                    selected = js.choose_interesting_joh(self.papers)
                self.assertEqual(selected, self.papers[-10:][::-1])
                self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_exhausted_api_failure_stops_instead_of_using_keywords(self):
        client = Mock()
        client.chat.completions.create.side_effect = RuntimeError('API unavailable')
        with patch.dict(js.os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(js, 'OpenAI', return_value=client):
            with self.assertRaisesRegex(RuntimeError, 'three attempts'):
                js.choose_interesting_joh(self.papers)
        self.assertEqual(client.chat.completions.create.call_count, 3)
        client.close.assert_called_once()

    def test_no_key_does_not_silently_use_keyword_selection(self):
        with patch.dict(js.os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'OPENAI_API_KEY'):
                js.choose_interesting_joh(self.papers)


if __name__ == '__main__':
    unittest.main()
