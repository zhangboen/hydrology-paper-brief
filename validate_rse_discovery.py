"""Read-only live RSE discovery check; no email, LLM calls or sent-list changes."""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from main import JOURNALS, fetch_recent_journal_articles, match_ranked_topic


def main():
    logging.basicConfig(level=logging.INFO)
    now = datetime.now(timezone.utc)
    with requests.Session() as session:
        session.headers['User-Agent'] = 'hydrology-paper-brief/RSE-discovery-validation'
        items = fetch_recent_journal_articles(session, 'Remote Sensing of Environment',
                                              JOURNALS['Remote Sensing of Environment'],
                                              now-timedelta(hours=48), now,
                                              os.getenv('CONTACT_EMAIL', ''))
    report = {'checked_at': now.isoformat(), 'count': len(items), 'keyword_candidates': [], 'records': []}
    for item in items:
        record = {'doi': item.get('DOI'), 'title': item.get('title'), 'created': item.get('created'),
                  'published': item.get('published'), 'topic': match_ranked_topic(item)}
        report['records'].append(record)
        if record['topic']:
            report['keyword_candidates'].append(record)
    output = Path('validation-output')
    output.mkdir(exist_ok=True)
    (output/'rse-discovery.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(f"Retrieved {len(items)} RSE records, including {len(report['keyword_candidates'])} keyword candidates.")
    for item in report['keyword_candidates']:
        print(item['doi'], item['title'])
    assert items, 'Live RSE query returned no records; inspect API results'


if __name__ == '__main__':
    main()
