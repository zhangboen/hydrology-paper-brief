import json
import logging
import os
import re
import smtplib
import ssl
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import unescape
from pathlib import Path
from typing import Any

import requests


LOGGER = logging.getLogger("hydrology_paper_brief")

SENT_DOIS_PATH = Path("sent_dois.json")
CROSSREF_API = "https://api.crossref.org/journals/{issn}/works"
ARXIV_API = "https://export.arxiv.org/api/query"
ROWS_PER_JOURNAL = int(os.getenv("ROWS_PER_JOURNAL", "200"))
ROWS_PER_ARXIV_QUERY = int(os.getenv("ROWS_PER_ARXIV_QUERY", "200"))
MAX_PAPERS = int(os.getenv("MAX_PAPERS", "50"))
MAX_ARXIV_PAPERS = int(os.getenv("MAX_ARXIV_PAPERS", "10"))

JOURNALS = {
    "Water Resources Research": "1944-7973",
    "Geophysical Research Letters": "1944-8007",
    "Journal of Geophysical Research: Atmospheres": "2169-8996",
    "Earth's Future": "2328-4277",
    "AGU Advances": "2576-604X",
    "Reviews of Geophysics": "1944-9208",
    "Nature": "1476-4687",
    "Science": "1095-9203",
    "Science Advances": "2375-2548",
    "PNAS": "1091-6490",
    "Nature Climate Change": "1758-6798",
    "Nature Geoscience": "1752-0908",
    "Nature Communications": "2041-1723",
    "Communications Earth & Environment": "2662-4435",
    "Nature Sustainability": "2398-9629",
    "Nature Water": "2731-6084",
    "Geoscientific Model Development": "1991-9603",
    "Bulletin of the American Meteorological Society": "1520-0477",
    "Journal of Climate": "1520-0442",
    "Journal of Hydrology": "0022-1694",
    "Remote Sensing of Environment": "1879-0704",
    "Hydrology and Earth System Sciences": "1607-7938",
}

TOPIC_KEYWORDS = (
    (
        "flood",
        (
            "flood",
            "flooding",
            "floodplain",
            "flash flood",
            "inundation",
            "pluvial flood",
            "fluvial flood",
        ),
    ),
    (
        "climate extreme events",
        (
            "climate extreme",
            "extreme event",
            "extreme precipitation",
            "extreme rainfall",
            "heatwave",
            "compound event",
            "atmospheric river",
            "storm surge",
        ),
    ),
    (
        "drought",
        (
            "drought",
            "aridity",
            "dry spell",
            "water scarcity",
            "soil moisture deficit",
            "meteorological drought",
            "hydrological drought",
        ),
    ),
    (
        "hydrological machine learning",
        (
            "hydrological machine learning",
            "hydrologic machine learning",
            "hydrology machine learning",
            "hydrological deep learning",
            "hydrologic deep learning",
            "hydrology deep learning",
        ),
    ),
    (
        "SWOT",
        (
            "swot",
            "surface water and ocean topography",
        ),
    ),
)

MACHINE_LEARNING_KEYWORDS = (
            "machine learning",
            "deep learning",
            "artificial intelligence",
            "neural network",
            "random forest",
            "xgboost",
            "lstm",
            "transformer",
            "data-driven",
)

HYDROLOGY_CONTEXT_KEYWORDS = (
    "hydrology",
    "hydrological",
    "hydrologic",
    "flood",
    "streamflow",
    "runoff",
    "river",
    "discharge",
    "precipitation",
    "drought",
    "soil moisture",
    "catchment",
    "watershed",
    "basin",
    "water resources",
    "hydroclimate",
    "hydroclimatic",
    "climate",
    "climate change",
    "climate model",
    "climate extreme",
    "meteorology",
    "atmospheric",
    "earth system",
    "sea surface temperature",
    "sst",
)

ARXIV_CATEGORIES = (
    "cs.LG",
    "stat.ML",
    "cs.AI",
    "eess.SP",
    "eess.IV",
    "physics.ao-ph",
    "physics.geo-ph",
)

ARXIV_ML_QUERY_TERMS = (
    "machine",
    "learning",
    "deep",
    "neural",
    "transformer",
    "data-driven",
)

ARXIV_HYDROCLIMATE_QUERY_TERMS = (
    "climate",
    "hydrology",
    "hydrological",
    "hydroclimate",
    "flood",
    "drought",
    "precipitation",
    "streamflow",
    "runoff",
    "soil",
    "meteorology",
    "atmospheric",
    "sst",
)

ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


@dataclass(frozen=True)
class Paper:
    title: str
    authors: str
    journal: str
    publication_date: str
    doi: str
    url: str
    topic: str
    topic_rank: int
    abstract: str


def clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_sent_dois(path: Path = SENT_DOIS_PATH) -> set[str]:
    if not path.exists():
        LOGGER.info("%s does not exist yet; starting with an empty sent DOI list.", path)
        return set()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse {path}: {exc}") from exc

    if not isinstance(data, list):
        raise RuntimeError(f"{path} must contain a JSON list of DOI strings.")

    return {normalize_doi(item) for item in data if isinstance(item, str) and item.strip()}


def save_sent_dois(sent_dois: set[str], path: Path = SENT_DOIS_PATH) -> None:
    path.write_text(
        json.dumps(sorted(sent_dois), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    LOGGER.info("Saved %s sent DOI(s) to %s.", len(sent_dois), path)


def normalize_doi(doi: str) -> str:
    return doi.strip().lower()


def text_from_crossref(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    if value is None:
        return ""
    return str(value).strip()


def clean_abstract(raw_abstract: str) -> str:
    if not raw_abstract:
        return "No abstract available from Crossref."

    text = re.sub(r"<[^>]+>", " ", raw_abstract)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "No abstract available from Crossref."


def clean_arxiv_text(raw_text: str | None) -> str:
    if not raw_text:
        return ""
    return clean_whitespace(raw_text)


def arxiv_identifier(entry_id: str) -> str:
    identifier = entry_id.rstrip("/").rsplit("/", 1)[-1]
    identifier = re.sub(r"v\d+$", "", identifier)
    return f"arxiv:{identifier.lower()}"


def arxiv_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return value or "Unknown"


def arxiv_published_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def arxiv_categories(entry: ET.Element) -> list[str]:
    return [
        category.attrib.get("term", "")
        for category in entry.findall("atom:category", ARXIV_NS)
        if category.attrib.get("term")
    ]


def searchable_arxiv_text(entry: ET.Element) -> str:
    title = clean_arxiv_text(entry.findtext("atom:title", default="", namespaces=ARXIV_NS))
    summary = clean_arxiv_text(entry.findtext("atom:summary", default="", namespaces=ARXIV_NS))
    categories = " ".join(arxiv_categories(entry))
    return f"{title} {summary} {categories}".lower()


def is_arxiv_hydroclimate_ml_match(entry: ET.Element) -> bool:
    searchable_text = searchable_arxiv_text(entry)
    categories = set(arxiv_categories(entry))
    has_ml = (
        any(keyword in searchable_text for keyword in MACHINE_LEARNING_KEYWORDS)
        or bool(categories.intersection({"cs.LG", "stat.ML", "cs.AI"}))
    )
    has_hydroclimate = any(keyword in searchable_text for keyword in HYDROLOGY_CONTEXT_KEYWORDS)
    return has_ml and has_hydroclimate


def paper_from_arxiv_entry(entry: ET.Element) -> Paper | None:
    entry_id = clean_arxiv_text(entry.findtext("atom:id", default="", namespaces=ARXIV_NS))
    if not entry_id:
        return None

    title = clean_arxiv_text(entry.findtext("atom:title", default="Untitled", namespaces=ARXIV_NS))
    summary = clean_arxiv_text(entry.findtext("atom:summary", default="", namespaces=ARXIV_NS))
    published = clean_arxiv_text(entry.findtext("atom:published", default="", namespaces=ARXIV_NS))
    authors = [
        clean_arxiv_text(author.findtext("atom:name", default="", namespaces=ARXIV_NS))
        for author in entry.findall("atom:author", ARXIV_NS)
    ]
    authors = [author for author in authors if author]
    if len(authors) > 8:
        authors = authors[:8] + ["et al."]

    primary_category = entry.find("arxiv:primary_category", ARXIV_NS)
    primary_category_name = (
        primary_category.attrib.get("term", "arXiv")
        if primary_category is not None
        else "arXiv"
    )

    return Paper(
        title=title or "Untitled",
        authors=", ".join(authors) if authors else "Unknown",
        journal=f"arXiv ({primary_category_name})",
        publication_date=arxiv_date(published),
        doi=arxiv_identifier(entry_id),
        url=entry_id.replace("http://", "https://"),
        topic="arXiv hydroclimate machine learning",
        topic_rank=4,
        abstract=summary or "No abstract available from arXiv.",
    )


def crossref_date(item: dict[str, Any]) -> str:
    for key in ("published-print", "published-online", "published", "created"):
        date_parts = item.get(key, {}).get("date-parts", [])
        if date_parts and date_parts[0]:
            parts = [str(part) for part in date_parts[0]]
            return "-".join(parts)
    return "Unknown"


def crossref_publication_date(item: dict[str, Any]) -> datetime | None:
    for key in ("published-print", "published-online", "published"):
        date_parts = item.get(key, {}).get("date-parts", [])
        if not date_parts or not date_parts[0]:
            continue

        parts = date_parts[0]
        year = parts[0]
        month = parts[1] if len(parts) > 1 else 1
        day = parts[2] if len(parts) > 2 else 1
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None

    return None


def format_authors(authors: list[dict[str, Any]] | None) -> str:
    if not authors:
        return "Unknown"

    names = []
    for author in authors[:8]:
        given = author.get("given", "").strip()
        family = author.get("family", "").strip()
        name = " ".join(part for part in (given, family) if part)
        if name:
            names.append(name)

    if not names:
        return "Unknown"
    if len(authors) > len(names):
        names.append("et al.")
    return ", ".join(names)


def searchable_crossref_text(item: dict[str, Any]) -> str:
    return " ".join(
        [
            text_from_crossref(item.get("title")),
            clean_abstract(text_from_crossref(item.get("abstract"))),
            text_from_crossref(item.get("subject")),
        ]
    ).lower()


def match_ranked_topic(item: dict[str, Any]) -> tuple[int, str] | None:
    searchable_text = searchable_crossref_text(item)

    for rank, (topic, keywords) in enumerate(TOPIC_KEYWORDS, start=1):
        if any(keyword in searchable_text for keyword in keywords):
            return rank, topic

        if topic == "hydrological machine learning":
            has_ml = any(keyword in searchable_text for keyword in MACHINE_LEARNING_KEYWORDS)
            has_hydrology_context = any(
                keyword in searchable_text for keyword in HYDROLOGY_CONTEXT_KEYWORDS
            )
            if has_ml and has_hydrology_context:
                return rank, topic

    return None


def paper_from_crossref_item(
    item: dict[str, Any],
    fallback_journal: str,
    topic_rank: int,
    topic: str,
) -> Paper | None:
    doi = normalize_doi(text_from_crossref(item.get("DOI")))
    if not doi:
        LOGGER.debug("Skipping Crossref item without DOI: %s", item)
        return None

    title = text_from_crossref(item.get("title")) or "Untitled"
    journal = text_from_crossref(item.get("container-title")) or fallback_journal
    url = text_from_crossref(item.get("URL")) or f"https://doi.org/{doi}"
    abstract = clean_abstract(text_from_crossref(item.get("abstract")))

    return Paper(
        title=title,
        authors=format_authors(item.get("author")),
        journal=journal,
        publication_date=crossref_date(item),
        doi=doi,
        url=url,
        topic=topic,
        topic_rank=topic_rank,
        abstract=abstract,
    )


def fetch_recent_journal_articles(
    session: requests.Session,
    journal_name: str,
    issn: str,
    from_datetime: datetime,
    until_datetime: datetime,
    contact_email: str,
) -> list[dict[str, Any]]:
    from_date = from_datetime.date()
    until_date = until_datetime.date()
    params = {
        "filter": (
            f"from-pub-date:{from_date.isoformat()},"
            f"until-pub-date:{until_date.isoformat()},"
            "type:journal-article"
        ),
        "sort": "published",
        "order": "desc",
        "rows": ROWS_PER_JOURNAL,
        "mailto": contact_email,
    }

    url = CROSSREF_API.format(issn=issn)
    LOGGER.info(
        "Searching %s (%s) from %s to %s.",
        journal_name,
        issn,
        from_date.isoformat(),
        until_date.isoformat(),
    )

    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    items = payload.get("message", {}).get("items", [])

    if not isinstance(items, list):
        LOGGER.warning("Unexpected Crossref response shape for %s.", journal_name)
        return []

    recent_items = []
    for item in items:
        publication_date = crossref_publication_date(item)
        if publication_date is None or publication_date.date() >= from_datetime.date():
            recent_items.append(item)

    LOGGER.info(
        "Found %s article(s) in %s before keyword filtering.",
        len(recent_items),
        journal_name,
    )
    return recent_items


def fetch_recent_arxiv_entries(
    session: requests.Session,
    from_datetime: datetime,
    until_datetime: datetime,
) -> list[ET.Element]:
    from_stamp = from_datetime.strftime("%Y%m%d%H%M")
    until_stamp = until_datetime.strftime("%Y%m%d%H%M")
    category_query = " OR ".join(f"cat:{category}" for category in ARXIV_CATEGORIES)
    ml_query = " OR ".join(f"all:{term}" for term in ARXIV_ML_QUERY_TERMS)
    hydroclimate_query = " OR ".join(
        f"all:{term}" for term in ARXIV_HYDROCLIMATE_QUERY_TERMS
    )
    params = {
        "search_query": (
            f"(({category_query}) OR ({ml_query})) AND "
            f"({hydroclimate_query}) AND "
            f"submittedDate:[{from_stamp} TO {until_stamp}]"
        ),
        "start": 0,
        "max_results": ROWS_PER_ARXIV_QUERY,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    LOGGER.info(
        "Searching arXiv from %s to %s across %s categories.",
        from_stamp,
        until_stamp,
        len(ARXIV_CATEGORIES),
    )
    response = session.get(ARXIV_API, params=params, timeout=30)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    entries = root.findall("atom:entry", ARXIV_NS)

    recent_entries = []
    for entry in entries:
        published = arxiv_published_datetime(
            clean_arxiv_text(entry.findtext("atom:published", default="", namespaces=ARXIV_NS))
        )
        if published is None or published >= from_datetime:
            recent_entries.append(entry)

    LOGGER.info("Found %s arXiv entry/entries before keyword filtering.", len(recent_entries))
    return recent_entries


def fetch_arxiv_candidate_papers(
    session: requests.Session,
    from_datetime: datetime,
    until_datetime: datetime,
) -> list[Paper]:
    try:
        entries = fetch_recent_arxiv_entries(
            session=session,
            from_datetime=from_datetime,
            until_datetime=until_datetime,
        )
    except (requests.RequestException, ET.ParseError) as exc:
        LOGGER.exception("arXiv request failed: %s", exc)
        return []

    papers_by_identifier: dict[str, Paper] = {}
    for entry in entries:
        if not is_arxiv_hydroclimate_ml_match(entry):
            continue
        paper = paper_from_arxiv_entry(entry)
        if paper:
            papers_by_identifier[paper.doi] = paper

    papers = sorted(
        papers_by_identifier.values(),
        key=lambda paper: (paper.publication_date, paper.title),
        reverse=True,
    )
    LOGGER.info("Collected %s arXiv hydroclimate-ML candidate paper(s).", len(papers))
    return papers[:MAX_ARXIV_PAPERS]


def fetch_candidate_papers(contact_email: str) -> list[Paper]:
    until_datetime = datetime.now(timezone.utc)
    from_datetime = until_datetime - timedelta(hours=24)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "hydrology-paper-email-brief/1.0 "
                f"(mailto:{contact_email})"
            )
        }
    )

    papers_by_doi: dict[str, Paper] = {}
    for paper in fetch_arxiv_candidate_papers(
        session=session,
        from_datetime=from_datetime,
        until_datetime=until_datetime,
    ):
        papers_by_doi[paper.doi] = paper

    for journal_name, issn in JOURNALS.items():
        try:
            items = fetch_recent_journal_articles(
                session=session,
                journal_name=journal_name,
                issn=issn,
                from_datetime=from_datetime,
                until_datetime=until_datetime,
                contact_email=contact_email,
            )
        except requests.RequestException as exc:
            LOGGER.exception("Crossref request failed for %s: %s", journal_name, exc)
            continue

        for item in items:
            topic_match = match_ranked_topic(item)
            if not topic_match:
                continue

            topic_rank, topic = topic_match
            paper = paper_from_crossref_item(item, journal_name, topic_rank, topic)
            if paper:
                papers_by_doi[paper.doi] = paper

        time.sleep(0.2)

    LOGGER.info("Collected %s topic-matched candidate paper(s).", len(papers_by_doi))
    return list(papers_by_doi.values())


def select_papers(candidates: list[Paper], sent_dois: set[str], limit: int = MAX_PAPERS) -> list[Paper]:
    unsent = [paper for paper in candidates if paper.doi not in sent_dois]
    LOGGER.info("%s candidate paper(s) remain after excluding sent DOI(s).", len(unsent))

    return sorted(unsent, key=lambda paper: (paper.topic_rank, paper.publication_date, paper.title))[:limit]


def build_email_body(papers: list[Paper]) -> str:
    if not papers:
        return (
            "No new papers matched the ranked Crossref topics or arXiv hydroclimate-ML filter "
            "for the last 24 hours, "
            "or all matching papers have already been sent."
        )

    lines = [
        f"Hydrology paper brief for {datetime.now(timezone.utc).date().isoformat()}",
        f"Selected {len(papers)} paper(s) by ranked topic priority from recent Crossref and arXiv results.",
        "Topic priority: flood; climate extreme events; drought; hydrological machine learning; arXiv hydroclimate machine learning; SWOT.",
        "",
    ]

    for index, paper in enumerate(papers, start=1):
        lines.extend(
            [
                f"{index}. {paper.title}",
                f"Ranked topic: {paper.topic} (priority {paper.topic_rank})",
                f"Authors: {paper.authors}",
                f"Journal: {paper.journal}",
                f"Publication date: {paper.publication_date}",
                f"Identifier: {paper.doi}",
                f"URL: {paper.url}",
                f"Abstract: {paper.abstract}",
                "",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def send_email(subject: str, body: str) -> None:
    smtp_user = get_required_env("SMTP_USER")
    smtp_password = get_required_env("SMTP_PASSWORD")
    smtp_host = get_required_env("SMTP_HOST")
    smtp_port = int(get_required_env("SMTP_PORT"))
    recipient_email = get_required_env("RECIPIENT_EMAIL")

    message = EmailMessage()
    message["From"] = smtp_user
    message["To"] = recipient_email
    message["Subject"] = subject
    message.set_content(body)

    LOGGER.info("Sending email to %s via %s:%s.", recipient_email, smtp_host, smtp_port)

    if smtp_port == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=30) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)

    LOGGER.info("Email sent successfully.")


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    contact_email = get_required_env("CONTACT_EMAIL")
    sent_dois = load_sent_dois()
    candidates = fetch_candidate_papers(contact_email)
    selected = select_papers(candidates, sent_dois)

    subject_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"Daily hydrology paper brief - {subject_date}"
    body = build_email_body(selected)

    send_email(subject, body)

    if selected:
        sent_dois.update(paper.doi for paper in selected)
        save_sent_dois(sent_dois)
    else:
        LOGGER.info("No new identifier(s) to add to %s.", SENT_DOIS_PATH)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        LOGGER.exception("Daily hydrology paper brief failed.")
        raise
