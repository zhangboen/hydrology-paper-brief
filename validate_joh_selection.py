"""Live expert-selection check with archived real papers; never sends emails."""
import json
from pathlib import Path
from types import SimpleNamespace

from joh_selection import choose_interesting_joh


def main():
    papers = {}
    for path in sorted(Path('outputs').glob('selected-papers-*.json'), reverse=True):
        for data in json.loads(path.read_text(encoding='utf8')).get('papers', []):
            if data.get('journal', '').strip().casefold() == 'journal of hydrology':
                papers.setdefault(data['doi'], SimpleNamespace(**data))
        if len(papers) >= 14:
            break
    candidates = list(papers.values())[:14]
    assert len(candidates) > 10, 'Need at least 11 archived real JoH papers'
    selected = choose_interesting_joh(candidates, Path('validation-output'))
    assert len(selected) == len({p.doi for p in selected}) == 10
    assert {p.doi for p in selected} <= set(papers)
    print(f'GPT selected 10 of {len(candidates)} archived real Journal of Hydrology papers.')
    for p in selected:
        print(p.doi, p.title)


if __name__ == '__main__':
    main()
