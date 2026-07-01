from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


LOGGER = logging.getLogger("generate_wechat_post")
OUTPUTS_DIR = Path("outputs")


def latest_selected_papers_path() -> Path | None:
    paths = sorted(OUTPUTS_DIR.glob("selected-papers-*.json"))
    return paths[-1] if paths else None


def load_selected_papers(path: Path) -> list[SimpleNamespace]:
    data = json.loads(path.read_text(encoding="utf-8"))
    papers = data.get("papers", [])
    if not isinstance(papers, list):
        raise RuntimeError(f"{path} does not contain a papers list.")
    return [SimpleNamespace(**paper) for paper in papers if isinstance(paper, dict)]


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not os.getenv("OPENAI_API_KEY"):
        LOGGER.warning("OPENAI_API_KEY is not set; skipping WeChat HTML generation.")
        return 0

    from wechat_article_builder import write_wechat_article

    selected_path = latest_selected_papers_path()
    if selected_path is None:
        LOGGER.info("No selected paper JSON found in %s; skipping.", OUTPUTS_DIR)
        return 0

    papers = load_selected_papers(selected_path)
    if not papers:
        LOGGER.info("%s contains no papers; skipping.", selected_path)
        return 0

    wrote = write_wechat_article(
        papers,
        datetime.now(timezone(timedelta(hours=8))),
        OUTPUTS_DIR,
    )
    if wrote:
        LOGGER.info("Generated WeChat HTML from %s.", selected_path)
    else:
        LOGGER.info("No WeChat HTML was generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
