"""Live expert-selection check with real Crossref papers; never sends emails."""
import json
from pathlib import Path
from types import SimpleNamespace

from joh_selection import choose_interesting_joh


def main():
    fixture = Path(__file__).parent / 'fixtures/joh-selection-real-papers.json'
    data = json.loads(fixture.read_text(encoding='utf8'))
    candidates = [SimpleNamespace(**p) for p in data['papers']]
    assert len(candidates) > 10
    selected = choose_interesting_joh(candidates, Path('validation-output'))
    assert len(selected) == len({p.doi for p in selected}) == 10
    assert {p.doi for p in selected} <= {p.doi for p in candidates}
    print(f'GPT selected 10 of {len(candidates)} real Journal of Hydrology papers.')
    for p in selected:
        print(p.doi, p.title)


if __name__ == '__main__':
    main()
