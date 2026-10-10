import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

import main


class RSEDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.until = datetime(2026, 10, 10, tzinfo=timezone.utc)
        self.start = datetime(2026, 10, 8, tzinfo=timezone.utc)

    def response(self, items, total=None, cursor=None):
        r = Mock(status_code=200)
        r.json.return_value = {'message': {'items': items, 'total-results': len(items) if total is None else total,
                                          'next-cursor': cursor}}
        return r

    def item(self, doi, date):
        return {'DOI': doi, 'published-print': {'date-parts': [date]}, 'title': ['Soil moisture retrieval']}

    def fetch(self, session, journal='Remote Sensing of Environment'):
        return main.fetch_recent_journal_articles(session, journal, main.JOURNALS[journal],
                                                 self.start, self.until, 'test@example.org')

    def test_correct_issn_created_date_and_recovery_window(self):
        session = Mock()
        records = [self.item('10.1/future', [2027, 1]), self.item('10.1/late-deposit', [2026, 9, 1])]
        session.get.return_value = self.response(records)
        self.assertEqual(self.fetch(session), records)
        args, kw = session.get.call_args
        self.assertTrue(args[0].endswith('/0034-4257/works'))
        self.assertEqual(kw['params']['filter'], 'from-created-date:2026-09-26,until-created-date:2026-10-10,type:journal-article')
        self.assertEqual(kw['params']['sort'], 'created')

    def test_empty_result_tries_global_then_electronic_fallback(self):
        session = Mock()
        item = self.item('10.1/found', [2027, 1])
        session.get.side_effect = [self.response([]), self.response([]), self.response([item])]
        self.assertEqual(self.fetch(session), [item])
        calls = session.get.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1].args[0], main.CROSSREF_WORKS_API)
        self.assertIn('issn:0034-4257', calls[1].kwargs['params']['filter'])
        self.assertTrue(calls[2].args[0].endswith('/1879-0704/works'))

    def test_all_sources_empty_returns_empty(self):
        session = Mock()
        session.get.return_value = self.response([])
        self.assertEqual(self.fetch(session), [])
        self.assertEqual(session.get.call_count, 4)

    def test_cursor_pages_are_combined(self):
        session = Mock()
        a, b = self.item('10.1/a', [2027, 1]), self.item('10.1/b', [2027, 1])
        session.get.side_effect = [self.response([a], total=2, cursor='page2'), self.response([b], total=2)]
        self.assertEqual(self.fetch(session), [a, b])
        self.assertEqual(session.get.call_args.kwargs['params']['cursor'], 'page2')

    def test_other_journals_keep_publication_window(self):
        session = Mock()
        a = self.item('10.1/a', [2026, 10, 9])
        session.get.return_value = self.response([a])
        self.assertEqual(self.fetch(session, 'Journal of Hydrology'), [a])
        params = session.get.call_args.kwargs['params']
        self.assertEqual(params['filter'], 'from-pub-date:2026-10-08,until-pub-date:2026-10-10,type:journal-article')
        self.assertEqual(params['sort'], 'published')
        self.assertNotIn('cursor', params)


if __name__ == '__main__':
    unittest.main()
