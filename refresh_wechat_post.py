"""Refresh today's search and WeChat post while retaining earlier deduplication."""
import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import main as brief
from wechat_article_builder import write_wechat_article


def refresh(source_path: Path, now: datetime | None = None) -> list[brief.Paper]:
    now = now or datetime.now(timezone(timedelta(hours=8)))
    today = now.astimezone(timezone(timedelta(hours=8))).date()
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source_date = datetime.fromisoformat(source["generated_at"]).astimezone(
        timezone(timedelta(hours=8))
    ).date()
    if source_date != today:
        raise ValueError(f"Source papers are from {source_date}, not today ({today}).")
    papers = source["papers"]
    if not isinstance(papers, list):
        raise ValueError("Source papers must be a list.")
    todays_dois = {brief.normalize_doi(paper["doi"]) for paper in papers}
    sent_dois = brief.load_sent_dois()
    excluded_dois = sent_dois - todays_dois
    logging.info("Allowing %s of today's papers to be reconsidered.", len(todays_dois))
    candidates = brief.fetch_candidate_papers(brief.get_required_env("CONTACT_EMAIL"))
    relevant = brief.filter_hydroclimate_relevant_papers(candidates)
    selected = brief.select_papers(relevant, excluded_dois)
    if not selected:
        raise RuntimeError("Fresh search selected no papers; retaining the existing post.")
    if not write_wechat_article(selected, now, brief.OUTPUTS_DIR):
        raise RuntimeError("WeChat generation did not complete; retaining sent DOI history.")
    brief.write_selected_papers(selected, now)
    brief.save_sent_dois(sent_dois | {paper.doi for paper in selected})
    logging.info("Refreshed today's post with %s freshly selected papers.", len(selected))
    return selected


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_path", type=Path)
    refresh(parser.parse_args().source_path)
