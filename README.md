# Daily Hydrology Paper Brief

This project searches journal articles published in the last 48 hours in Crossref, adds arXiv preprints from the last 72 hours that overlap machine learning and hydroclimate topics, screens every result for expert-level hydroclimate relevance, selects up to 50 new papers by journal priority followed by ranked topic priority, sends an email brief, and generates a WeChat-ready HTML article every day.

The GitHub Actions workflow runs at `01:00 UTC`, which corresponds to `09:00` in China.

## Included Journals

- Water Resources Research
- Geophysical Research Letters
- Journal of Geophysical Research: Atmospheres
- Earth's Future
- AGU Advances
- Reviews of Geophysics
- Nature
- Science
- Science Advances
- PNAS
- Nature Climate Change
- Nature Geoscience
- Nature Communications
- Communications Earth & Environment
- Nature Sustainability
- Nature Water
- Geoscientific Model Development
- Bulletin of the American Meteorological Society
- Journal of Climate
- Journal of Hydrology
- Remote Sensing of Environment
- Hydrology and Earth System Sciences

## Ranked Topics

The script first matches keywords in titles, available Crossref abstracts, and subjects, then screens topic-matched candidates for hydroclimate relevance. Only relevant, unsent papers are eligible.

Nature, Science, and their **currently configured portfolio journals** have the highest journal priority: Science Advances, Nature Climate Change, Nature Geoscience, Nature Communications, Communications Earth & Environment, Nature Sustainability, and Nature Water. These papers precede other journals and arXiv before the daily paper limit is applied. Journal priority does not bypass topic or relevance screening, and does not add other portfolio journals to the search.

Within each journal tier, matching Crossref papers are prioritized in this order:

1. flood
2. climate extreme events
3. drought
4. evapotranspiration
5. soil moisture
6. groundwater and baseflow
7. snowmelt, including rain-on-snow
8. compound hydroclimate events, including drought-to-flood transitions
9. hydrological machine learning
10. SWOT
11. geomorphology, including fluvial and channel morphology, landscape evolution, sediment transport, and erosion
12. hydrography, including river, drainage, stream, and channel networks, bathymetry, and waterbody mapping
13. catchment processes and ungauged prediction, including hydrologic functional diversity/complexity, catchment classification, rainfall-runoff relationships, runoff/streamflow generation, stormflow, hydrologic response/similarity, ungauged catchments/basins/watersheds, rainfall persistence, and hydrologic model structure/transferability

The new catchment terms are informed by [Ameli et al. (2026), Nature Water](https://doi.org/10.1038/s44221-026-00699-6). The article's title passes the keyword filter even without an abstract. Hyphens and Unicode dashes (for example, rainfall–runoff) are normalized during matching. Existing arXiv hydroclimate-ML papers retain topic priority 4 within the lower journal tier; ties retain publication-date and title ordering.

## arXiv Preprint Filter

The script also queries recent arXiv submissions from these categories:

- `cs.LG`
- `stat.ML`
- `cs.AI`
- `eess.SP`
- `eess.IV`
- `physics.ao-ph`
- `physics.geo-ph`

It keeps arXiv papers only when the title, abstract, or categories match both:

- machine-learning context, such as machine learning, deep learning, artificial intelligence, neural network, LSTM, transformer, or data-driven methods
- hydroclimate and Earth-surface context, such as hydrology, flood, streamflow, runoff, precipitation, drought, evapotranspiration, soil moisture, groundwater, baseflow, snowmelt, rain-on-snow, compound events, drought-to-flood transitions, water resources, hydroclimate, climate change, meteorology, Earth system, sea surface temperature, geomorphology, sediment transport, hydrography, river networks, or river bathymetry

## Files

- `main.py` - Crossref/arXiv search, ranked topic selection, abstract formatting, duplicate tracking, SMTP email sending, and selected-paper JSON export.
- `generate_wechat_post.py` - Reads the selected-paper JSON and generates the WeChat HTML article.
- `wechat_article_builder.py` - OpenAI-backed Chinese title and full abstract translation with WeChat-compatible HTML layout.
- `requirements.txt` - Python dependencies.
- `.github/workflows/daily.yml` - Scheduled GitHub Actions automation.
- `sent_dois.json` - Stores sent papers to avoid resending them.
- `outputs/wechat-post-YYYY-MM-DD.html` - Generated WeChat article HTML.

## GitHub Secrets

Create these repository secrets before enabling the workflow:

| Secret | Value |
| --- | --- |
| `RECIPIENT_EMAIL` | `boenzhang.gis@outlook.com` |
| `CONTACT_EMAIL` | Your contact email for Crossref polite API use |
| `SMTP_USER` | `893001879@qq.com` |
| `SMTP_PASSWORD` | Your regenerated QQ SMTP authorization code |
| `SMTP_HOST` | `smtp.qq.com` |
| `SMTP_PORT` | `465` |
| `OPENAI_API_KEY` | OpenAI API key for relevance screening and Chinese title/full abstract translation |
| `OPENAI_RELEVANCE_MODEL` | Optional; relevance screening defaults to `gpt-5` |
| `OPENAI_MODEL` | Optional; Chinese translation defaults to `gpt-4o-mini` |

Relevance screening uses `OPENAI_RELEVANCE_MODEL` independently of the translation model, so an existing `OPENAI_MODEL` secret does not override the `gpt-5` screening default. Leave `OPENAI_RELEVANCE_MODEL` unset or empty to use the default. Screening requests omit custom temperature for GPT-5 compatibility. If the API key is missing or all screening attempts fail, the existing keyword-based relevance fallback still applies.

Do not commit SMTP passwords or authorization codes to the repository.

`OPENAI_API_KEY` is required for WeChat HTML generation. If it is missing, the daily email still sends, but the workflow skips `outputs/wechat-post-YYYY-MM-DD.html`.

## Local Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Set environment variables:

```bash
export RECIPIENT_EMAIL="boenzhang.gis@outlook.com"
export CONTACT_EMAIL="your-contact-email@example.com"
export SMTP_USER="893001879@qq.com"
export SMTP_PASSWORD="your-regenerated-smtp-authorization-code"
export SMTP_HOST="smtp.qq.com"
export SMTP_PORT="465"
export OPENAI_API_KEY="your-openai-api-key"
export OPENAI_RELEVANCE_MODEL="gpt-5"
export OPENAI_MODEL="gpt-4o-mini"
```

Run the automation:

```bash
python main.py
```

By default, the script searches Crossref over the last 48 hours and arXiv over the last 72 hours. It asks Crossref for up to 200 recent items per journal, asks arXiv for up to 200 recent items with up to 3 request attempts, keeps up to 10 arXiv matches, screens every candidate from a hydroclimate-expert perspective, and selects up to 50 papers total. WeChat translation requests use batches of 5 papers, translate each available English abstract in full rather than summarizing it, and retry an incomplete batch up to 3 times with a 2-second delay. If no abstract is available after the configured lookups, the paper remains listed but the abstract paragraph is omitted, with no missing-abstract notice or title-based summary. It writes the WeChat article to `outputs/wechat-post-YYYY-MM-DD.html` and metadata to `outputs/wechat-post-YYYY-MM-DD.json`, then deletes the previous day's WeChat HTML and metadata. You can override these with `ROWS_PER_JOURNAL`, `ROWS_PER_ARXIV_QUERY`, `CROSSREF_LOOKBACK_HOURS`, `ARXIV_LOOKBACK_HOURS`, `ARXIV_MAX_ATTEMPTS`, `ARXIV_RETRY_SLEEP_SECONDS`, `MAX_ARXIV_PAPERS`, `MAX_PAPERS`, `OPENAI_RELEVANCE_BATCH_SIZE`, `OPENAI_RELEVANCE_MAX_ATTEMPTS`, `OPENAI_WECHAT_BATCH_SIZE`, `OPENAI_WECHAT_MAX_ATTEMPTS`, and `OPENAI_WECHAT_RETRY_SLEEP_SECONDS`.

For a topic-matched Crossref paper without an abstract, the script searches OpenAlex and Semantic Scholar up to three times and then stops looking. If all providers lack an abstract, the email and Chinese article omit the abstract section. Missing-abstract notices are not sent for translation, and no title-based summary is generated. Both services work without a key for light use; optional `OPENALEX_API_KEY` and `SEMANTIC_SCHOLAR_API_KEY` environment variables are supported, and `ABSTRACT_LOOKUP_TIMEOUT_SECONDS`, `ABSTRACT_LOOKUP_MAX_ATTEMPTS`, and `ABSTRACT_LOOKUP_RETRY_SLEEP_SECONDS` control the lookup behavior.


The daily introduction lists the translated titles directly after the paper count, without “题目如下”.

## Author information and Journal of Hydrology limit

Each daily selection includes at most **10 Journal of Hydrology papers**, selected
using the existing ranked keyword topics before applying the overall paper limit.
The cap applies to the unsent candidates in the existing 48-hour discovery window;
it does not affect Journal of Hydrology: Regional Studies. Papers omitted by the
cap are not marked as sent. Existing Nature/Science priority is preserved.

Full author lists are retained in `author_details`. When a paper has more than
eight authors, the visible byline includes the first two authors plus **all known
corresponding authors**, in publication order and without repeating a person.
An `et al.` suffix indicates omitted authors. If correspondence cannot be verified,
only the first two are shown; the last author is never assumed to be corresponding.

After Authors, both email and WeChat HTML include `作者信息：`. Corresponding teams
are joined with `联合`; a different first listed publication affiliation is appended
with `第一单位是…`. Multiple affiliations are retained. The first numbered/listed
publication affiliation is kept separately from the first author's affiliation.
Missing correspondence is explicitly reported without inventing a team.

`author_metadata.py` combines Crossref's full authors, DOI-specific OpenAlex
authorships, Copernicus publisher XML, and a Responses API web search. Publication
affiliations are used, not present-day employment. Chinese personal names and
titles require supporting source text and identity evidence (email/ORCID or full
name plus affiliation). Unverified names remain in English; unknown titles are
omitted, and junior titles are never promoted. Lookup failures fall back to the
available metadata and do not prevent sending the brief.

Web enrichment uses the existing `OPENAI_API_KEY`, with model `gpt-4.1-mini` by
default (`OPENAI_AUTHOR_MODEL` may override it). It makes one publication search per
uncached selected paper and, when needed, one targeted profile/translation search,
which adds API/search usage. Successful metadata is
cached for 30 days in `outputs/author-metadata-cache.json`; the existing workflow
commits this with other outputs. Selected-paper JSON preserves raw affiliations,
Chinese translations, source URLs, and verified evidence for audit.

Run all offline tests:

```bash
python -m unittest -v test_brief.py test_author_metadata.py
```

The separate **Validate paper brief** workflow runs offline checks on code changes.
Its optional manual live validation checks one public HESS paper using the existing
API secret, saves JSON/HTML artifacts, and does **not** send mail or mark papers sent.

## Existing regression tests

Run the offline regression tests without sending emails or calling external APIs:

```bash
python -m unittest -v test_brief.py
```

## How Duplicate Prevention Works

After a successful email with selected papers, the script writes sent identifiers to `sent_dois.json`. Crossref papers use DOI identifiers, and arXiv papers use `arxiv:<id>` identifiers. The GitHub Actions workflow commits this file back to the repository so future scheduled runs can skip papers that have already been emailed.

If no new matching papers are found, the script sends a short email saying there are no new unsent results and does not modify `sent_dois.json`.
