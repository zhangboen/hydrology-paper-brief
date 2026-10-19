import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import requests
import abstract_sources as a

class AbstractSourceTests(unittest.TestCase):
    def setUp(self):
        a._cache_path = None
        a._cache = {}
        a._results = {}
        a._disabled = set()

    def test_exact_doi_required_and_explicit_abstract_preferred(self):
        doc='<meta name="citation_doi" content="10.1038/test"><meta name="dc.description" content="'+('Short overview. '*8)+'"><div id="Abs1-content"><p>'+('Full abstract evidence. '*10)+'</p></div>'
        result=a.parse_publisher_html(doc,'10.1038/test','https://www.nature.com/articles/test')
        self.assertEqual(result.kind,'abstract')
        self.assertTrue(result.text.startswith('Full abstract evidence.'))
        self.assertFalse(a.parse_publisher_html(doc,'10.1038/other','https://www.nature.com/articles/test').text)

    def test_summary_is_labeled_and_social_snippets_are_not_abstracts(self):
        doc='<meta name="citation_doi" content="10.1038/test"><meta name="dc.description" content="'+('Official briefing text. '*8)+'">'
        result=a.parse_publisher_html(doc,'10.1038/test','https://www.nature.com/articles/test')
        self.assertEqual(result.kind,'publisher_summary')
        doc=doc.replace('dc.description','og:description')
        self.assertFalse(a.parse_publisher_html(doc,'10.1038/test','https://www.nature.com/articles/test').text)

    def test_europe_pmc_rejects_wrong_doi(self):
        session=Mock();session.get.return_value.json.return_value={'resultList':{'result':[
            {'doi':'10.1/other','abstractText':'Wrong abstract'},
            {'doi':'10.1/right','abstractText':'<p>Correct abstract.</p>','source':'MED','id':'123'}]}}
        result=a.fetch_europe_pmc(session,'10.1/right',15)
        self.assertEqual(result.text,'Correct abstract.')
        self.assertEqual(result.source,'Europe PMC')

    def test_positive_cache_survives_reload_and_prevents_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'cache.json';a.configure_cache(path)
            a.remember('10.1/a',a.AbstractResult('Verified abstract','Publisher','abstract','https://example.org'))
            a.configure_cache(path)
            session=Mock()
            self.assertEqual(a.recover(session,'10.1/a',{},[]).text,'Verified abstract')
            session.get.assert_not_called()
        a._cache_path=None

    def test_429_disables_provider_for_run_and_other_source_can_succeed(self):
        response=Mock(status_code=429)
        error=requests.HTTPError(response=response)
        with patch.object(a,'fetch_publisher',return_value=a.AbstractResult()), \
             patch.object(a,'fetch_europe_pmc',side_effect=error) as europe, \
             patch.object(a.time,'sleep') as sleep:
            fallback=Mock(return_value='Recovered from another database')
            a.recover(Mock(),'10.1/a',{},[('OpenAlex',fallback)])
            a.recover(Mock(),'10.1/b',{},[('OpenAlex',fallback)])
            self.assertEqual(europe.call_count,1)
            self.assertEqual(fallback.call_count,2)
            sleep.assert_not_called()

    def test_archived_missing_text_recovers_with_provenance_without_overwriting_existing(self):
        import main
        empty=main.Paper('Title', '', 'Nature', '', '10.1/a', '', '', 0, '')
        existing=main.Paper('Existing', '', 'Nature', '', '10.1/b', '', '', 0, 'Original abstract')
        a._results['10.1/a']=a.AbstractResult('Official overview', 'Publisher', 'publisher_summary', 'https://example.org')
        with patch.object(main, 'resolve_crossref_abstract', return_value='Official overview') as lookup:
            result=main.recover_missing_paper_abstracts([empty, existing], '')
        self.assertEqual(result[0].abstract_kind,'publisher_summary')
        self.assertEqual(result[0].abstract,'Official overview')
        self.assertIs(result[1],existing)
        lookup.assert_called_once()

    def test_empty_responses_not_retried_but_timeouts_are(self):
        with patch.object(a,'fetch_publisher',side_effect=[requests.Timeout(),a.AbstractResult()]) as pub, \
             patch.object(a,'fetch_europe_pmc',return_value=a.AbstractResult()) as epmc, \
             patch.object(a.time,'sleep'):
            self.assertFalse(a.recover(Mock(),'10.1038/a',{},[],attempts=3).text)
            self.assertEqual(pub.call_count,2)
            self.assertEqual(epmc.call_count,1)

if __name__=='__main__':
    unittest.main()
