"""Replay real daily candidates through GPT; no discovery, email, or sent-state writes."""
import json
from pathlib import Path

import main


def run():
    fixture = json.loads((Path(__file__).parent / 'fixtures/relevance-2026-10-11.json').read_text(encoding='utf-8'))
    entries = fixture['papers']
    papers = [main.Paper(**entry['paper']) for entry in entries]
    output = Path('validation-output')
    kept = {p.doi for p in main.filter_hydroclimate_relevant_papers(papers, audit_dir=output)}
    audit_file = max(output.glob('relevance-review-*.json'), key=lambda p: p.stat().st_mtime)
    audit = json.loads(audit_file.read_text(encoding='utf-8'))
    decisions = {d['doi']: d for d in audit['decisions']}
    comparisons = []
    for entry in entries:
        p = entry['paper']
        actual = p['doi'] in kept
        result = {'number': entry['number'], 'title': p['title'], 'doi': p['doi'],
                  'expected_relevant': entry['expected_relevant'], 'actual_relevant': actual,
                  'match': actual == entry['expected_relevant'], 'reason': decisions[p['doi']]['reason']}
        comparisons.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    report = {'source_run': fixture['source_run'], 'rule_version': audit['rule_version'],
              'model': audit['model'], 'kept_count': len(kept), 'comparisons': comparisons}
    (output / 'relevance-regression.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    assert all(row['match'] for row in comparisons), 'Scientific relevance mismatch; see saved review and comparison.'
    print(f'PASS: {len(papers)} real papers reviewed, {len(kept)} retained; no email sent.')


if __name__ == '__main__':
    run()
