"""Recover real missing abstracts/official summaries without email or sent-state writes."""
import json
import os
from pathlib import Path
import requests
import main
import abstract_sources


def run():
    fixture=json.loads((Path(__file__).parent/'fixtures/missing-abstracts-2026-10-19.json').read_text(encoding='utf-8'))
    output=Path('validation-output');output.mkdir(exist_ok=True)
    abstract_sources.configure_cache(output/'abstract-cache.json')
    rows=[]
    with requests.Session() as session:
        session.headers.update({'User-Agent':'hydrology-paper-brief/abstract-validation'})
        for paper in fixture['papers']:
            doi=paper['doi']
            text=main.resolve_crossref_abstract(session,{'DOI':doi},os.getenv('CONTACT_EMAIL',''))
            evidence=abstract_sources.provenance(doi)
            found=text != main.ABSTRACT_NOT_AVAILABLE
            row={**paper,'recovered':found,'characters':len(text) if found else 0,
                 'source':evidence.source,'kind':evidence.kind,'url':evidence.url,
                 'text':text if found else ''}
            rows.append(row)
            print(json.dumps({k:v for k,v in row.items() if k!='text'},ensure_ascii=False),flush=True)
    report={'total':len(rows),'recovered':sum(row['recovered'] for row in rows),
            'abstracts':sum(row['recovered'] and row['kind']=='abstract' for row in rows),
            'official_summaries':sum(row['recovered'] and row['kind']=='publisher_summary' for row in rows),
            'papers':rows}
    (output/'abstract-availability.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    assert all(row['recovered'] for row in rows), 'Some sample abstracts remain unavailable; inspect report'
    print(f"PASS: {report['recovered']}/{report['total']} recovered ({report['abstracts']} abstracts, {report['official_summaries']} official summaries); no email sent.")

if __name__=='__main__':
    run()
