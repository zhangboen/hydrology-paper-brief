import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
from test_author_metadata import paper


class DirectInclusionTests(unittest.TestCase):
    def test_all_configured_portfolio_and_pnas_bypass_keyword_gate(self):
        journals = {name: issn for name, issn in main.JOURNALS.items() if main.journal_priority(name) == 0}
        self.assertIn('PNAS', journals)
        self.assertIn('Science Advances', journals)
        # This title/metadata intentionally contains none of the configured keywords.
        item = {'DOI': '10.1/test', 'title': ['A changing balance'], 'container-title': ['Nature']}
        self.assertIsNone(main.match_ranked_topic(item))
        for journal in journals:
            with self.subTest(journal=journal), patch.object(main, 'JOURNALS', {journal: journals[journal]}), \
                 patch.object(main, 'fetch_arxiv_candidate_papers', return_value=[]), \
                 patch.object(main, 'fetch_recent_journal_articles', return_value=[{**item, 'container-title': [journal]}]), \
                 patch.object(main, 'resolve_crossref_abstract', return_value='Water exchanged between plants and the air.') as abstract, \
                 patch.object(main, 'match_ranked_topic') as match, patch.object(main.time, 'sleep'):
                result = main.fetch_candidate_papers('test@example.org')
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].topic, 'journal-based relevance review')
            match.assert_not_called()
            abstract.assert_called_once()

    def test_other_journals_still_require_keyword_match(self):
        with patch.object(main, 'JOURNALS', {'Remote Sensing of Environment': '0034-4257'}), \
             patch.object(main, 'fetch_arxiv_candidate_papers', return_value=[]), \
             patch.object(main, 'fetch_recent_journal_articles', return_value=[{'DOI': '10.1/x', 'title': ['Protein structures']}]), \
             patch.object(main, 'resolve_crossref_abstract') as abstract, patch.object(main.time, 'sleep'):
            self.assertEqual(main.fetch_candidate_papers('test@example.org'), [])
        abstract.assert_not_called()

    def test_semantic_review_keeps_keyword_free_related_paper_and_rejects_unrelated(self):
        related = paper(journal='Nature', title='A changing balance', abstract='Water exchanged between plants and the air.', topic='journal-based relevance review', topic_rank=0)
        unrelated = replace(related, doi='10.1/unrelated', title='Protein structures', abstract='An enzyme and its substrate.')
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'decisions': [
            {'index': 0, 'relevant': True, 'reason': 'Plant water exchange'},
            {'index': 1, 'relevant': False, 'reason': 'Biochemistry'}]})))])
        with patch.dict(main.os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(main, 'OpenAI', return_value=client):
            self.assertEqual(main.filter_hydroclimate_relevant_papers([related, unrelated]), [related])

    def test_relevant_direct_papers_survive_cap_but_sent_papers_do_not(self):
        direct = [paper(journal=j, doi=f'10.1/{i}', topic_rank=0) for i, j in enumerate([
            'Nature', 'Science', 'Proceedings of the National Academy of Sciences'])]
        ordinary = paper(journal='HESS', doi='10.1/other')
        self.assertEqual(main.select_papers(direct+[ordinary], {direct[0].doi}, limit=1), direct[1:])
        self.assertEqual(main.select_papers(direct, set(), limit=0), [])

    def test_pnas_aliases_recognized_without_loose_science_prefix(self):
        for name in ['PNAS', ' Proceedings of the National Academy of Sciences ',
                     'Proceedings of the National Academy of Sciences of the United States of America']:
            self.assertEqual(main.journal_priority(name), 0)
        self.assertEqual(main.journal_priority('Science of The Total Environment'), 1)

    def test_missing_or_failed_gpt_does_not_reintroduce_keyword_gate(self):
        p = paper(journal='PNAS', title='A changing balance', topic='journal-based relevance review')
        with patch.dict(main.os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'GPT relevance review is required'):
                main.filter_hydroclimate_relevant_papers([p])
        client = Mock()
        client.chat.completions.create.side_effect = RuntimeError('offline')
        with patch.dict(main.os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(main, 'OpenAI', return_value=client):
            with self.assertRaisesRegex(RuntimeError, 'GPT relevance review is required'):
                main.filter_hydroclimate_relevant_papers([p])


if __name__ == '__main__':
    unittest.main()
