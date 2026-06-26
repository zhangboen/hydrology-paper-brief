# Daily Hydrology Paper Brief

This project searches journal articles published in the last 24 hours in Crossref, adds arXiv preprints that overlap machine learning and hydroclimate topics, selects up to 20 new papers by ranked topic priority, and sends an email brief every day at 09:00 China Standard Time.

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

The script searches titles, abstracts, and Crossref subjects, then prioritizes matching papers in this order:

1. flood
2. climate extreme events
3. drought
4. hydrological machine learning
5. SWOT

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
- hydroclimate context, such as hydrology, flood, streamflow, runoff, precipitation, drought, soil moisture, water resources, hydroclimate, climate change, meteorology, Earth system, or sea surface temperature

## Files

- `main.py` - Crossref search, ranked topic selection, abstract formatting, duplicate tracking, and SMTP email sending.
- `requirements.txt` - Python dependencies.
- `.github/workflows/daily.yml` - Scheduled GitHub Actions automation.
- `sent_dois.json` - Stores sent papers to avoid resending them.

## GitHub Secrets

Create these repository secrets before enabling the workflow:

| Secret | Value |
| --- | --- |
| `RECIPIENT_EMAIL` | `zhangboenvip@gmail.com` |
| `CONTACT_EMAIL` | Your contact email for Crossref polite API use |
| `SMTP_USER` | `893001879@qq.com` |
| `SMTP_PASSWORD` | Your regenerated QQ SMTP authorization code |
| `SMTP_HOST` | `smtp.qq.com` |
| `SMTP_PORT` | `465` |
Do not commit SMTP passwords or authorization codes to the repository.

## Local Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Set environment variables:

```bash
export RECIPIENT_EMAIL="zhangben@mail.sysu.edu.cn"
export CONTACT_EMAIL="your-contact-email@example.com"
export SMTP_USER="893001879@qq.com"
export SMTP_PASSWORD="your-regenerated-smtp-authorization-code"
export SMTP_HOST="smtp.qq.com"
export SMTP_PORT="465"
```

Run the automation:

```bash
python main.py
```

By default, the script asks Crossref for up to 200 recent items per journal, asks arXiv for up to 200 recent items, keeps up to 10 arXiv matches, and selects up to 20 papers total. You can override these with `ROWS_PER_JOURNAL`, `ROWS_PER_ARXIV_QUERY`, `MAX_ARXIV_PAPERS`, and `MAX_PAPERS`.


## How Duplicate Prevention Works

After a successful email with selected papers, the script writes sent identifiers to `sent_dois.json`. Crossref papers use DOI identifiers, and arXiv papers use `arxiv:<id>` identifiers. The GitHub Actions workflow commits this file back to the repository so future scheduled runs can skip papers that have already been emailed.

If no new matching papers are found, the script sends a short email saying there are no new unsent results and does not modify `sent_dois.json`.
