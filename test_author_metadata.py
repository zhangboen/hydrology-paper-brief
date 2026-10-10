import copy
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
import author_metadata as am
from wechat_article_builder import build_wechat_html


def paper(**kwargs):
    data = dict(title='Flood test', authors='A One', journal='Journal of Hydrology',
                publication_date='2026-10-10', doi='10.1234/example', url='https://doi.org/10.1234/example',
                topic='flood', topic_rank=1, abstract='Flood abstract.')
    data.update(kwargs)
    return main.Paper(**data)


def metadata():
    return {'authors': [
        {'name': 'A One', 'affiliations': ['First University, Water Institute'], 'is_corresponding': False},
        {'name': 'B Two', 'affiliations': ['Second University, Science College'], 'is_corresponding': True,
         'email': 'two@second.edu', 'name_zh': '张乙', 'title_zh': '教授'},
        {'name': 'C Three', 'affiliations': ['Third Institute'], 'is_corresponding': True,
         'name_zh': '李丙', 'title_zh': '研究员'},
    ], 'first_affiliation': 'First University, Water Institute', 'first_affiliation_source': 'https://publisher.org/paper',
    'affiliation_translations': {'First University, Water Institute': '甲大学水文研究所',
                                 'Second University, Science College': '乙大学科学学院', 'Third Institute': '丙研究所'},
    'evidence': []}


class SelectionTests(unittest.TestCase):
    def test_hydrology_cap_uses_keyword_ranking_and_fills_global_limit(self):
        joh = [paper(doi=f'10.1/j{i}', topic_rank=20-i) for i in range(20)]
        other = [paper(doi=f'10.1/o{i}', journal='HESS', topic_rank=50) for i in range(8)]
        selected = main.select_papers(joh+other, set(), 15)
        self.assertEqual(len(selected), 15)
        self.assertEqual([p.topic_rank for p in selected if p.journal == 'Journal of Hydrology'], list(range(1, 11)))
        self.assertEqual(sum(p.journal == 'HESS' for p in selected), 5)

    def test_exact_ten_kept_and_regional_studies_not_capped(self):
        joh = [paper(doi=f'10.1/j{i}') for i in range(10)]
        regional = [paper(doi=f'10.1/r{i}', journal='Journal of Hydrology: Regional Studies') for i in range(12)]
        self.assertEqual(len(main.select_papers(joh+regional, set())), 22)

    def test_sent_excluded_before_cap_and_priority_unchanged(self):
        joh = [paper(doi=f'10.1/j{i}', journal=' Journal of HYDROLOGY ', topic_rank=i) for i in range(15)]
        priority = paper(journal='Nature', doi='10.1/nature', topic_rank=99)
        selected = main.select_papers(joh+[priority], {p.doi for p in joh[:4]})
        self.assertEqual(selected[0], priority)
        self.assertEqual(len(selected), 11)
        self.assertEqual(selected[-1].topic_rank, 13)
        self.assertEqual(main.select_papers(joh, set(), 0), [])


class AuthorTests(unittest.TestCase):
    def test_short_byline_all_long_first_two_plus_all_correspondents(self):
        authors = [{'name': f'Author {i}', 'is_corresponding': i in (1, 8, 11)} for i in range(12)]
        self.assertEqual(am.display_authors(authors), 'Author 0, Author 1, Author 8, Author 11, et al.')
        self.assertEqual(am.display_authors(authors[:8]), ', '.join(f'Author {i}' for i in range(8)))
        for a in authors:
            a['is_corresponding'] = True
        self.assertNotIn('et al.', am.display_authors(authors))

    def test_unknown_correspondence_never_infers_last_author(self):
        authors = [{'given': 'Person', 'family': str(i)} for i in range(12)]
        p = main.paper_from_crossref_item({'DOI': '10.1/a', 'author': authors}, 'HESS', 1, 'flood')
        self.assertEqual(len(p.author_details), 12)
        self.assertEqual(p.authors, 'Person 0, Person 1, et al.')

    def test_jats_copernicus_rid_xref_and_first_numbered_unit(self):
        xml = '''<article><front><article-meta><contrib-group>
        <contrib contrib-type="author" rid="aff2"><name><given-names>First</given-names><surname>Author</surname></name></contrib>
        <contrib contrib-type="author" corresp="yes" rid="aff2 aff1"><name><given-names>Second</given-names><surname>Author</surname></name><email>s@uni.edu</email><ext-link>https://orcid.org/0000-0001</ext-link></contrib>
        <contrib contrib-type="author"><name><given-names>Third</given-names><surname>Author</surname></name><xref ref-type="aff" rid="aff1"/><xref ref-type="corresp" rid="c1"/></contrib>
        <aff id="aff1"><label>1</label>First Institute</aff><aff id="aff2"><label>2</label>Second Institute</aff>
        </contrib-group><author-notes><corresp id="c1"><email>third@uni.edu</email></corresp></author-notes>
        </article-meta></front><back><aff id="ref">Unrelated Institute</aff></back></article>'''
        m = am.parse_jats(xml, 'https://publisher.org/article.xml')
        self.assertEqual(m['first_affiliation'], 'First Institute')
        self.assertEqual(m['authors'][1]['affiliations'], ['Second Institute', 'First Institute'])
        self.assertEqual(m['authors'][2]['email'], 'third@uni.edu')
        self.assertTrue(m['authors'][2]['is_corresponding'])
        self.assertEqual(m['authors'][1]['orcid'], 'https://orcid.org/0000-0001')

    def test_joint_teams_and_different_first_affiliation(self):
        self.assertEqual(am.format_author_info(metadata()), '乙大学科学学院张乙教授团队联合丙研究所李丙研究员团队；第一单位是甲大学水文研究所。')
        m = metadata()
        m['authors'][1]['affiliations'].append(m['first_affiliation'])
        self.assertNotIn('第一单位是', am.format_author_info(m))
        m['authors'] = []
        self.assertNotIn('团队', am.format_author_info(m))

    def test_email_html_author_info_immediately_after_authors_and_escaped(self):
        p = paper(author_info=am.format_author_info(metadata())+'<script>')
        email = main.build_email_body([p])
        self.assertIn(f'Authors: {p.authors}\n作者信息：', email)
        _, _, body = build_wechat_html([p], [{'chinese_title': '洪水', 'chinese_abstract': '摘要正文'}], date(2026, 10, 10))
        self.assertLess(body.index('Authors'), body.index('作者信息'))
        self.assertLess(body.index('作者信息'), body.index('文章链接'))
        self.assertNotIn('<script>', body)
        self.assertIn('&lt;script&gt;', body)

    def test_lookup_failure_keeps_metadata_and_does_not_abort(self):
        p = paper(author_details=[{'name': f'A {i}'} for i in range(10)])
        with tempfile.TemporaryDirectory() as directory, patch.dict(am.os.environ, {}, clear=True), patch.object(am, 'lookup_metadata', side_effect=ValueError()):
            result = am.enrich_selected_papers([p], 'test@example.org', Path(directory))
        self.assertEqual(result[0].authors, 'A 0, A 1, et al.')
        self.assertIn('暂未核实', result[0].author_info)


class EvidenceTests(unittest.TestCase):
    url = 'https://second.edu/people/two'

    def fact(self, value, quote, identity='two@second.edu'):
        return {'value': value, 'url': self.url, 'quote': quote, 'identity': identity}

    def test_requires_consulted_source_verbatim_quote_and_matching_identity(self):
        a = metadata()['authors'][1]
        documents = {self.url: '张乙 教授 two@second.edu'}
        fact = self.fact('张乙', '张乙 教授')
        self.assertIsNotNone(am.verify_fact(fact, {self.url}, Mock(), documents, author=a))
        self.assertIsNone(am.verify_fact(fact, set(), Mock(), documents, author=a))
        self.assertIsNone(am.verify_fact(self.fact('张甲', '张甲 教授'), {self.url}, Mock(), documents, author=a))
        self.assertIsNone(am.verify_fact(self.fact('张乙', '张乙 教授', 'other@second.edu'), {self.url}, Mock(), documents, author=a))

    def test_unverified_chinese_name_and_promoted_title_are_rejected(self):
        m = metadata()
        m['authors'][1].pop('name_zh')
        m['authors'][1].pop('title_zh')
        documents = {self.url: '张乙 副教授 two@second.edu Associate Professor'}
        result = {'authors': [{'index': 1, 'name_zh': self.fact('张假', '张乙 副教授'),
                               'title_zh': self.fact('教授', '张乙 副教授')}]}
        got = am.apply_search_results(m, result, {self.url}, Mock(), paper(), documents)
        self.assertNotIn('name_zh', got['authors'][1])
        self.assertNotIn('title_zh', got['authors'][1])
        result['authors'][0]['name_zh'] = self.fact('张乙', '张乙 副教授')
        result['authors'][0]['title_zh'] = self.fact('副教授', '张乙 副教授')
        got = am.apply_search_results(m, result, {self.url}, Mock(), paper(), documents)
        self.assertEqual(got['authors'][1]['name_zh'], '张乙')
        self.assertEqual(got['authors'][1]['title_zh'], '副教授')

    def test_source_list_is_taken_from_search_not_generated_json(self):
        response = Mock()
        response.model_dump.return_value = {'output': [
            {'type': 'web_search_call', 'action': {'sources': [{'url': self.url}]}},
            {'type': 'message', 'content': [{'text': '{"url":"https://fake.edu"}', 'annotations': []}]},
        ]}
        self.assertEqual(am.source_urls(response), {self.url})

    def test_tracking_parameters_do_not_reject_real_source(self):
        fact = self.fact('张乙', '张乙 教授')
        result = am.verify_fact(fact, {self.url+'?utm_source=openai'}, Mock(),
                                {self.url: '张乙 教授 two@second.edu'}, author=metadata()['authors'][1])
        self.assertIsNotNone(result)
        self.assertNotEqual(am.canonical_url(self.url+'?id=1'), am.canonical_url(self.url+'?id=2'))

    def test_official_profile_requires_matching_email_and_title_name(self):
        m = metadata()
        a = m['authors'][1]
        a.pop('name_zh')
        a.pop('title_zh')
        url = 'https://science.second.edu/people/two'
        page = '<title>张乙-乙大学科学学院</title><h1>张乙</h1><p>职称：副教授 邮箱：two@second.edu</p>'
        with patch.object(am, 'get_document', return_value=page):
            am.extract_official_profiles(m, {url}, Mock())
        self.assertEqual(a['name_zh'], '张乙')
        self.assertEqual(a['title_zh'], '副教授')
        a.pop('name_zh')
        a.pop('title_zh')
        with patch.object(am, 'get_document', return_value=page.replace('two@', 'other@')):
            am.extract_official_profiles(m, {url}, Mock())
        self.assertNotIn('name_zh', a)

    def test_profile_pages_prioritized_over_campus_homepages(self):
        m = metadata()
        a = m['authors'][1]
        a.pop('name_zh')
        a.pop('title_zh')
        url = 'https://zscience.second.edu/info/10/20.htm'
        consulted = {f'https://a{i}.second.edu/' for i in range(8)} | {url}
        page = '<title>张乙-乙大学科学学院</title><p>张乙 职称：研究员 邮箱：two@second.edu</p>'
        with patch.object(am, 'get_document', side_effect=lambda session, u: page if u == url else '<title>大学首页</title>'):
            am.extract_official_profiles(m, consulted, Mock())
        self.assertEqual(a['name_zh'], '张乙')
        self.assertEqual(a['title_zh'], '研究员')

    def test_websearch_request_and_malformed_response_fallback(self):
        client = Mock()
        searched = Mock(output_text='not JSON, but search evidence')
        searched.model_dump.return_value = {'output': []}
        client.responses.create.side_effect = [searched, SimpleNamespace(output_text='not JSON')]
        with self.assertRaises(ValueError):
            am.search_author_information(client, 'request')
        search_kw = client.responses.create.call_args_list[0].kwargs
        self.assertEqual(search_kw['tools'], [{'type': 'web_search'}])
        self.assertEqual(search_kw['tool_choice'], 'required')
        self.assertNotIn('text', search_kw)
        extract_kw = client.responses.create.call_args_list[1].kwargs
        self.assertNotIn('tools', extract_kw)
        self.assertTrue(extract_kw['text']['format']['strict'])
        self.assertNotIn('temperature', search_kw)


if __name__ == '__main__':
    unittest.main()
