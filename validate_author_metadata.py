"""Optional live validation. Does not send mail, translate abstracts, or mark DOIs sent."""
import argparse
import json
import logging
import os
from datetime import date
from pathlib import Path

import requests

from main import paper_from_crossref_item
from author_metadata import enrich_selected_papers
from wechat_article_builder import build_wechat_html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--doi', default='10.5194/hess-30-5647-2026')
    parser.add_argument('--output', default='validation-output')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    response = requests.get('https://api.crossref.org/works/'+args.doi, timeout=30)
    response.raise_for_status()
    p = paper_from_crossref_item(response.json()['message'], '', 1, 'hydrology')
    output = Path(args.output)
    enriched = enrich_selected_papers([p], os.getenv('CONTACT_EMAIL', ''), output)[0]
    output.mkdir(parents=True, exist_ok=True)
    (output/'author-information.json').write_text(json.dumps(enriched.__dict__, ensure_ascii=False, indent=2), encoding='utf-8')
    _, _, body = build_wechat_html([enriched], [{'chinese_title': enriched.title, 'chinese_abstract': ''}], date.today())
    (output/'author-information.html').write_text('<!doctype html><meta charset="utf-8">'+body, encoding='utf-8')
    print(enriched.authors)
    print(enriched.author_info)
    assert any(a.get('is_corresponding') and a.get('affiliations') for a in enriched.author_details), 'No corresponding affiliation found'
    if os.getenv('OPENAI_API_KEY'):
        assert enriched.author_metadata['affiliation_translations'], 'No Chinese affiliation translations verified'
        assert any(a.get('name_zh') for a in enriched.author_details if a.get('is_corresponding')), 'No verified Chinese name for this validation sample'


if __name__ == '__main__':
    main()
