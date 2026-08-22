from __future__ import annotations

import html
import json
import logging
import os
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from openai import OpenAI


LOGGER = logging.getLogger("wechat_article_builder")


class WeChatPaper(Protocol):
    title: str
    authors: str
    journal: str
    publication_date: str
    doi: str
    url: str
    topic: str
    topic_rank: int
    abstract: str


PAPER_FIELDS = (
    "title",
    "authors",
    "journal",
    "publication_date",
    "doi",
    "url",
    "topic",
    "topic_rank",
    "abstract",
)
OPENAI_WECHAT_BATCH_SIZE = max(1, int(os.getenv("OPENAI_WECHAT_BATCH_SIZE", "5")))
OPENAI_WECHAT_MAX_ATTEMPTS = max(1, int(os.getenv("OPENAI_WECHAT_MAX_ATTEMPTS", "3")))
OPENAI_WECHAT_RETRY_SLEEP_SECONDS = max(
    0.0, float(os.getenv("OPENAI_WECHAT_RETRY_SLEEP_SECONDS", "2"))
)
CHINESE_TRANSLATION_SYSTEM_PROMPT = (
    "You translate hydrology and hydroclimate literature into professional academic Chinese. "
    "Translate each paper title faithfully. Translate each available English abstract completely "
    "and faithfully into Chinese; do not summarize, shorten, paraphrase away details, or add "
    "interpretation. Preserve the abstract's sentence-level meaning, research background, methods, "
    "data, locations, findings, numerical values, uncertainty ranges, qualifications, and implications. "
    "Use natural academic Chinese while retaining the original logical structure. Use the standard "
    "hydrology translations '骤旱' for 'flash drought' and '骤洪' for 'flash flood'; never translate "
    "'flash' as '闪电' in these terms. Translate 'downscaling' as '降尺度'. If the abstract is "
    "unavailable, set chinese_abstract exactly to '该论文暂无可用摘要。'; do not infer content from "
    "the title or metadata. Do not invent information. Return valid JSON only."
)


JOURNAL_ABBREVIATIONS = {
    "Geoscientific Model Development": "GMD",
    "Hydrology and Earth System Sciences": "HESS",
    "Journal of Geophysical Research: Atmospheres": "JGR: Atmospheres",
    "Proceedings of the National Academy of Sciences": "PNAS",
    "Water Resources Research": "WRR",
    "Geophysical Research Letters": "GRL",
    "Nature Communications": "Nat. Commun.",
    "Communications Earth & Environment": "CEE",
    "Communications Earth and Environment": "CEE",
    "Nature Geoscience": "Nat. Geosci.",
    "Nature Climate Change": "Nat. Clim. Change",
    "Nature Sustainability": "Nat. Sustain.",
    "Nature Water": "Nat. Water",
    "Journal of Hydrology": "J. Hydrol.",
    "Remote Sensing of Environment": "RSE",
    "Bulletin of the American Meteorological Society": "BAMS",
    "Journal of Climate": "J. Climate",
    "Earth's Future": "Earth's Future",
    "AGU Advances": "AGU Adv.",
    "Reviews of Geophysics": "Rev. Geophys.",
}


def journal_abbreviation(journal: str) -> str:
    if journal in JOURNAL_ABBREVIATIONS:
        return JOURNAL_ABBREVIATIONS[journal]
    normalized_journal = journal.strip().casefold()
    for full_name, abbreviation in JOURNAL_ABBREVIATIONS.items():
        if full_name.casefold() == normalized_journal:
            return abbreviation
    if journal.startswith("arXiv"):
        return "arXiv"
    words = [word for word in journal.replace("&", " ").replace(":", " ").split() if word[:1].isalpha()]
    if len(words) <= 3:
        return journal
    return "".join(word[0].upper() for word in words[:5])


def normalize_hydrology_terms(text: str) -> str:
    replacements = {
        "闪电干旱": "骤旱",
        "干旱闪电": "骤旱",
        "闪电洪水": "骤洪",
        "洪水闪电": "骤洪",
        "降比例": "降尺度",
        "下尺度": "降尺度",
        "向下尺度化": "降尺度",
        "Downscaling": "降尺度",
        "downscaling": "降尺度",
        "CEAE": "CEE",
    }
    for incorrect, preferred in replacements.items():
        text = text.replace(incorrect, preferred)
    return text


def paper_to_dict(paper: WeChatPaper) -> dict:
    if is_dataclass(paper):
        return asdict(paper)
    if isinstance(paper, dict):
        return {field: paper.get(field, "") for field in PAPER_FIELDS}
    return {field: getattr(paper, field, "") for field in PAPER_FIELDS}


def generate_chinese_entries_batch(client: OpenAI, model: str, papers: list[WeChatPaper]) -> list[dict]:
    payload = [paper_to_dict(paper) for paper in papers]
    entries: list[dict] = []
    for attempt in range(1, OPENAI_WECHAT_MAX_ATTEMPTS + 1):
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": CHINESE_TRANSLATION_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": (
                        "For each paper, return a JSON object with key papers. "
                        "papers must be an array with exactly one object per input paper, in the same order. "
                        "Each object must have keys: chinese_title, chinese_abstract. "
                        "chinese_title must be a faithful Chinese translation of the paper title, not a generic label "
                        "such as research background, research purpose, or research method. "
                        "chinese_abstract must be a complete Chinese translation of the supplied English abstract, "
                        "not a summary or condensed rewrite. "
                        "Here are the papers:\n"
                        + json.dumps(payload, ensure_ascii=False)
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        if isinstance(data, list):
            entries = data
        else:
            entries = data.get("papers") or data.get("entries") or []
        if len(entries) == len(papers) and all(
            isinstance(entry, dict)
            and str(entry.get("chinese_title", "")).strip()
            and str(entry.get("chinese_abstract", "")).strip()
            for entry in entries
        ):
            break
        if attempt < OPENAI_WECHAT_MAX_ATTEMPTS:
            LOGGER.warning(
                "OpenAI response included %s entrie(s) for %s paper(s); retrying batch attempt %s/%s.",
                len(entries),
                len(papers),
                attempt + 1,
                OPENAI_WECHAT_MAX_ATTEMPTS,
            )
            time.sleep(OPENAI_WECHAT_RETRY_SLEEP_SECONDS)
    else:
        raise RuntimeError(
            "OpenAI response included "
            f"{len(entries)} entrie(s) for {len(papers)} paper(s) after "
            f"{OPENAI_WECHAT_MAX_ATTEMPTS} attempt(s)."
        )
    for entry in entries:
        entry["chinese_title"] = normalize_hydrology_terms(str(entry.get("chinese_title", "")))
        chinese_abstract = normalize_hydrology_terms(
            str(entry.get("chinese_abstract", ""))
        )
        entry["chinese_abstract"] = chinese_abstract.strip()
    return entries


def generate_chinese_entries(papers: list[WeChatPaper]) -> list[dict]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY secret.")

    client = OpenAI(api_key=api_key)
    model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    entries: list[dict] = []
    for start in range(0, len(papers), OPENAI_WECHAT_BATCH_SIZE):
        batch = papers[start : start + OPENAI_WECHAT_BATCH_SIZE]
        entries.extend(generate_chinese_entries_batch(client, model, batch))
    return entries


def generate_daily_intro(papers: list[WeChatPaper], entries: list[dict], run_date: date) -> str:
    del run_date
    listed_titles = [
        normalize_hydrology_terms(str(entry.get("chinese_title", "")).strip())
        for entry in entries
        if str(entry.get("chinese_title", "")).strip()
    ]
    items = "；".join(f"{index}）{title}" for index, title in enumerate(listed_titles, start=1))
    return f"本期共收录 {len(papers)} 篇水文气候相关论文，题目如下：{items}。"


def build_wechat_html(
    papers: list[WeChatPaper],
    entries: list[dict],
    run_date: date,
    intro: str | None = None,
) -> tuple[str, str, str]:
    title = f"今日水文气候文献简报（{run_date.isoformat()}）"
    digest = f"今日筛选 {len(papers)} 篇水文与水文气候论文，涵盖洪水、干旱、气候极端、机器学习、遥感和水文过程等主题。"
    intro = intro or generate_daily_intro(papers, entries, run_date)
    parts = [
        "<section style=\"box-sizing:border-box; max-width: 677px; margin: 0 auto; padding: 0 6px; color:#263238; "
        "font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue','PingFang SC','Microsoft YaHei',Arial,sans-serif; "
        "line-height:1.68; font-size:15px;\">",
        f"<p style=\"margin:0 0 14px;\">{html.escape(intro)}</p>",
    ]

    for idx, (paper, entry) in enumerate(zip(papers, entries), start=1):
        abbrev = journal_abbreviation(paper.journal)
        chinese_title = str(entry["chinese_title"]).strip()
        section_title = f"{chinese_title} | {abbrev}"
        chinese_abstract = str(entry["chinese_abstract"]).strip()
        url = paper.url or (f"https://doi.org/{paper.doi}" if paper.doi and not paper.doi.startswith("arxiv:") else "")
        link = f'<a href="{html.escape(url)}" style="color:#2878b5; text-decoration:underline;">{html.escape(url)}</a>' if url else ""
        parts.extend(
            [
                f"<section style=\"margin:18px 0 10px; padding:10px 12px; background:linear-gradient(90deg,#d9edf7 0%,#eef7fb 58%,#ffffff 100%); color:#17324d; font-weight:700; line-height:1.55; border-left:5px solid #2878b5; border-bottom:1px solid #b9d7e8; box-shadow:0 2px 8px rgba(40,120,181,0.12);\">{idx:02d}｜{html.escape(section_title)}</section>",
                f"<h2 style=\"margin:10px 0 6px; color:#162b3c; font-size:18px; line-height:1.42;\">{html.escape(paper.title)}</h2>",
                f"<p style=\"margin:0 0 6px;\"><strong>Authors：</strong>{html.escape(paper.authors)}</p>",
                f"<p style=\"margin:0 0 6px;\"><strong>文章链接：</strong>{link}</p>",
                f"<p style=\"margin:0 0 16px; padding:10px 12px; background:#fbfcfd; border-left:3px solid #f0b429;\"><strong>摘要译文：</strong>{html.escape(chinese_abstract)}</p>",
            ]
        )

    parts.append("</section>")
    html_body = "\n".join(part.strip() for part in parts if part.strip())
    html_body = normalize_hydrology_terms(html_body)
    if "CEAE" in html_body:
        raise RuntimeError("HTML validation failed: CEE was incorrectly abbreviated as CEAE.")
    return title, digest, html_body


def delete_previous_wechat_files(run_date: datetime, outputs_dir: Path) -> list[Path]:
    previous_stamp = (run_date.date() - timedelta(days=1)).isoformat()
    removed: list[Path] = []
    for suffix in ("html", "json"):
        path = outputs_dir / f"wechat-post-{previous_stamp}.{suffix}"
        if path.exists():
            path.unlink()
            removed.append(path)
            LOGGER.info("Deleted previous day's WeChat output: %s", path)
    return removed


def write_wechat_article(papers: list[WeChatPaper], run_date: datetime, outputs_dir: Path) -> bool:
    if not papers:
        return False
    if not os.getenv("OPENAI_API_KEY"):
        return False

    outputs_dir.mkdir(exist_ok=True)
    entries = generate_chinese_entries(papers)
    intro = generate_daily_intro(papers, entries, run_date.date())
    title, digest, html = build_wechat_html(papers, entries, run_date.date(), intro)

    date_stamp = run_date.date().isoformat()
    html_path = outputs_dir / f"wechat-post-{date_stamp}.html"
    metadata_path = outputs_dir / f"wechat-post-{date_stamp}.json"

    html_path.write_text(html, encoding="utf-8")
    metadata_path.write_text(
        json.dumps(
            {
                "title": title,
                "digest": digest,
                "paper_count": len(papers),
                "intro": intro,
                "generated_at": run_date.isoformat(),
                "html_path": str(html_path),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    delete_previous_wechat_files(run_date, outputs_dir)
    return True
