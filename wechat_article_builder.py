from __future__ import annotations

import html
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from openai import OpenAI


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
OPENAI_WECHAT_BATCH_SIZE = max(1, int(os.getenv("OPENAI_WECHAT_BATCH_SIZE", "10")))


JOURNAL_ABBREVIATIONS = {
    "Geoscientific Model Development": "GMD",
    "Hydrology and Earth System Sciences": "HESS",
    "Journal of Geophysical Research: Atmospheres": "JGR: Atmospheres",
    "Proceedings of the National Academy of Sciences": "PNAS",
    "Water Resources Research": "WRR",
    "Geophysical Research Letters": "GRL",
    "Nature Communications": "Nat. Commun.",
    "Communications Earth & Environment": "Commun. Earth Environ.",
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
    if journal.startswith("arXiv"):
        return "arXiv"
    words = [word for word in journal.replace("&", " ").replace(":", " ").split() if word[:1].isalpha()]
    if len(words) <= 3:
        return journal
    return "".join(word[0].upper() for word in words[:5])


def paper_to_dict(paper: WeChatPaper) -> dict:
    if is_dataclass(paper):
        return asdict(paper)
    if isinstance(paper, dict):
        return {field: paper.get(field, "") for field in PAPER_FIELDS}
    return {field: getattr(paper, field, "") for field in PAPER_FIELDS}


def generate_chinese_entries_batch(client: OpenAI, model: str, papers: list[WeChatPaper]) -> list[dict]:
    payload = [paper_to_dict(paper) for paper in papers]
    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": (
                    "You write concise Chinese hydrology and hydroclimate literature briefs. "
                    "Translate titles faithfully. Summaries must be accurate, 2-3 Chinese sentences, "
                    "and should emphasize research question, data/method, findings, and implications. "
                    "Do not invent information. Return valid JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    "For each paper, return a JSON object with key papers. "
                    "papers must be an array with exactly one object per input paper, in the same order. "
                    "Each object must have keys: chinese_title, summary. "
                    "chinese_title must be a faithful Chinese translation of the paper title, not a generic label "
                    "such as research background, research purpose, or research method. "
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
    if len(entries) != len(papers):
        raise RuntimeError(
            f"OpenAI response included {len(entries)} entrie(s) for {len(papers)} paper(s)."
        )
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


def build_wechat_html(papers: list[WeChatPaper], entries: list[dict], run_date: date) -> tuple[str, str, str]:
    title = f"今日水文气候文献简报（{run_date.isoformat()}）"
    digest = f"今日筛选 {len(papers)} 篇水文与水文气候论文，涵盖洪水、干旱、气候极端、机器学习、遥感和水文过程等主题。"
    parts = [
        "<section style=\"box-sizing:border-box; max-width: 677px; margin: 0 auto; padding: 0 6px; color:#263238; "
        "font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue','PingFang SC','Microsoft YaHei',Arial,sans-serif; "
        "line-height:1.68; font-size:15px;\">",
        f"<p style=\"margin:0 0 14px;\">今天的 brief 共筛选出 <strong style=\"color:#2878b5;\">{len(papers)} 篇</strong> 水文与水文气候论文。"
        "这些研究共同指向一个核心问题：如何在更高分辨率、更复杂过程和更强不确定性背景下，提高水文与气候风险分析的可解释性和可用性。</p>",
    ]

    for idx, (paper, entry) in enumerate(zip(papers, entries), start=1):
        abbrev = journal_abbreviation(paper.journal)
        chinese_title = str(entry["chinese_title"]).strip()
        section_title = f"{chinese_title} | {abbrev}"
        summary = str(entry["summary"]).strip()
        url = paper.url or (f"https://doi.org/{paper.doi}" if paper.doi and not paper.doi.startswith("arxiv:") else "")
        link = f'<a href="{html.escape(url)}" style="color:#2878b5; text-decoration:underline;">{html.escape(url)}</a>' if url else ""
        parts.extend(
            [
                f"<section style=\"margin: 16px 0 8px; padding: 8px 12px; background:#eef5f8; color:#2c5364; font-weight:700; line-height:1.55;\">{idx:02d}｜{html.escape(section_title)}</section>",
                f"<h2 style=\"margin:10px 0 6px; color:#162b3c; font-size:18px; line-height:1.42;\">{html.escape(paper.title)}</h2>",
                f"<p style=\"margin:0 0 6px;\"><strong>Journal：</strong>{html.escape(paper.journal)}</p>",
                f"<p style=\"margin:0 0 6px;\"><strong>Authors：</strong>{html.escape(paper.authors)}</p>",
                f"<p style=\"margin:0 0 6px;\"><strong>文章链接：</strong>{link}</p>",
                f"<p style=\"margin:0 0 16px; padding:10px 12px; background:#fbfcfd; border-left:3px solid #b9d7e8;\">{html.escape(summary)}</p>",
            ]
        )

    parts.append("</section>")
    html_body = "\n".join(part.strip() for part in parts if part.strip())
    return title, digest, html_body


def write_wechat_article(papers: list[WeChatPaper], run_date: datetime, outputs_dir: Path) -> bool:
    if not papers:
        return False
    if not os.getenv("OPENAI_API_KEY"):
        return False

    outputs_dir.mkdir(exist_ok=True)
    entries = generate_chinese_entries(papers)
    title, digest, html = build_wechat_html(papers, entries, run_date.date())

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
                "generated_at": run_date.isoformat(),
                "html_path": str(html_path),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return True
