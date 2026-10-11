import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
from test_author_metadata import paper


def response(decisions):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=json.dumps({'decisions': decisions})))])


def decision(index=0, relevant=True, reason='Direct analysis of runoff'):
    return dict(index=index, relevant=relevant, reason=reason)


class RelevanceAuditTests(unittest.TestCase):
    def run_review(self, papers, responses, batch_size=20):
        client = Mock()
        client.chat.completions.create.side_effect = responses
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(main.os.environ, {'OPENAI_API_KEY': 'test'}), \
             patch.object(main, 'OpenAI', return_value=client), \
             patch.object(main, 'OPENAI_RELEVANCE_BATCH_SIZE', batch_size):
            error = None
            try:
                kept = main.filter_hydroclimate_relevant_papers(papers, Path(directory))
            except RuntimeError as exc:
                kept, error = [], exc
            audit = json.loads(next(Path(directory).glob('relevance-review-*.json')).read_text(encoding='utf-8'))
        client.close.assert_called_once()
        return kept, audit, client, error

    def test_audits_both_decisions_and_title_only_evidence(self):
        yes = paper(doi='10.1/yes', abstract='Runoff observations')
        no = paper(doi='10.1/no', abstract=main.ABSTRACT_NOT_AVAILABLE)
        kept, audit, _, error = self.run_review([yes, no], [response([
            decision(), decision(1, False, 'Title-only: membrane design')])])
        self.assertIsNone(error)
        self.assertEqual(kept, [yes])
        self.assertEqual(audit['status'], 'complete')
        self.assertEqual(audit['kept_count'], 1)
        self.assertEqual(audit['candidate_count'], 2)
        self.assertEqual(audit['rule_version'], main.RELEVANCE_RULE_VERSION)
        self.assertEqual(audit['prompt'], main.RELEVANCE_SYSTEM_PROMPT)
        self.assertEqual([d['relevant'] for d in audit['decisions']], [True, False])
        self.assertEqual(audit['decisions'][0]['abstract'], yes.abstract)
        self.assertEqual(audit['decisions'][1]['evidence_basis'], 'title_only')
        self.assertEqual(audit['decisions'][1]['abstract'], '')
        self.assertEqual(audit['decisions'][1]['reason'], 'Title-only: membrane design')

    def test_retries_missing_reason_and_wrong_index(self):
        p = paper()
        kept, audit, client, error = self.run_review([p], [
            response([decision(reason=' ')]), response([decision(index=1)]),
            response([decision()])])
        self.assertIsNone(error)
        self.assertEqual(kept, [p])
        self.assertEqual(client.chat.completions.create.call_count, 3)
        self.assertEqual(len(audit['decisions']), 1)

    def test_preserves_decisions_across_batches(self):
        papers = [paper(doi=f'10.1/{i}') for i in range(2)]
        kept, audit, _, error = self.run_review(papers, [
            response([decision()]), response([decision(relevant=False)])], batch_size=1)
        self.assertIsNone(error)
        self.assertEqual(kept, papers[:1])
        self.assertEqual([d['doi'] for d in audit['decisions']], [p.doi for p in papers])

    def test_failed_batch_preserves_prior_audit_without_keyword_fallback(self):
        papers = [paper(doi=f'10.1/{i}', journal='Journal of Hydrology', title='Flood runoff') for i in range(2)]
        _, audit, _, error = self.run_review(papers, [response([decision()])] +
            [RuntimeError('offline')] * main.OPENAI_RELEVANCE_MAX_ATTEMPTS, batch_size=1)
        self.assertIn('GPT relevance review is required', str(error))
        self.assertEqual(audit['status'], 'failed')
        self.assertEqual(audit['failed_batch_dois'], [papers[1].doi])
        self.assertEqual([d['doi'] for d in audit['decisions']], [papers[0].doi])

    def test_missing_key_stops_ordinary_journal_screening(self):
        with patch.dict(main.os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'GPT relevance review is required'):
                main.filter_hydroclimate_relevant_papers([paper(journal='Journal of Hydrology')])


if __name__ == '__main__':
    unittest.main()
