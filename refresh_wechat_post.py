"""Refresh today's search and WeChat post while retaining earlier deduplication."""
import argparse
import json
import logging
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

import main as brief
from wechat_article_builder import write_wechat_article


def refresh(source_path: Path, now: datetime | None = None, replay_source: bool = False, additional_source_paths=()) -> list[brief.Paper]:
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
    sources = [source_path]
    papers = list(papers)
    for extra_path in additional_source_paths:
        extra_path = Path(extra_path)
        extra = json.loads(extra_path.read_text(encoding="utf-8"))
        extra_date = datetime.fromisoformat(extra["generated_at"]).astimezone(timezone(timedelta(hours=8))).date()
        if extra_date != today:
            raise ValueError("Additional selection is not from today")
        papers.extend(extra["papers"])
        sources.append(extra_path)
    todays_dois = {brief.normalize_doi(paper["doi"]) for paper in papers}
    sent_dois = brief.load_sent_dois()
    excluded_dois = sent_dois - todays_dois
    logging.info("Allowing %s of today's papers to be reconsidered.", len(todays_dois))
    if replay_source:
        # Reapply current rules to the exact original edition, without a moving
        # discovery window dropping its preprints or adding unrelated new papers.
        paper_fields = {field.name for field in fields(brief.Paper)}
        candidates = [brief.Paper(**{k: v for k, v in paper.items() if k in paper_fields}) for paper in papers]
    else:
        candidates = brief.fetch_candidate_papers(brief.get_required_env("CONTACT_EMAIL"))
        # A moving search window must not lose the original edition or rejected
        # candidates that are being reconsidered under updated scientific rules.
        restored = {}
        for path in sources:
            audit_path = path.parent / f"relevance-review-{today.isoformat()}.json"
            if audit_path.exists():
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
                for entry in audit.get("decisions", []):
                    doi = brief.normalize_doi(entry["doi"])
                    restored[doi] = brief.Paper(
                        title=entry["title"], authors="", journal=entry["journal"],
                        publication_date="", doi=doi, url="https://doi.org/" + doi,
                        topic="archived same-day candidate", topic_rank=0,
                        abstract=entry.get("abstract", ""))
        paper_fields = {field.name for field in fields(brief.Paper)}
        for entry in papers:
            if "title" in entry:
                item = brief.Paper(**{k: v for k, v in entry.items() if k in paper_fields})
                restored[item.doi] = item
        # Fresh discovery carries more complete current bibliographic metadata.
        restored.update({item.doi: item for item in candidates})
        candidates = list(restored.values())
        logging.info("Reviewing %s merged current and archived candidates.", len(candidates))
    relevant = brief.filter_hydroclimate_relevant_papers(candidates, audit_dir=brief.OUTPUTS_DIR)
    selected = brief.select_papers(relevant, excluded_dois)
    if not selected:
        raise RuntimeError("Fresh search selected no papers; retaining the existing post.")
    selected = brief.enrich_selected_papers(
        selected, brief.get_required_env("CONTACT_EMAIL"), brief.OUTPUTS_DIR)
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
    parser.add_argument("--replay-source", action="store_true", help="Review the exact original edition rather than searching again.")
    parser.add_argument("--merge-source", action="append", type=Path, default=[])
    args = parser.parse_args()
    refresh(args.source_path, replay_source=args.replay_source, additional_source_paths=args.merge_source)
