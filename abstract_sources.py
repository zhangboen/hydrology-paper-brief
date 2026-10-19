"""DOI-verified abstract recovery, provenance, caching and provider cooldowns."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote, urlparse
import html
import json
import logging
import re
import time

import requests
from bs4 import BeautifulSoup

LOG = logging.getLogger(__name__)
EUROPE_PMC = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'
_cache_path = None
_cache = {}
_results = {}
_disabled = set()
ALLOWED_HOSTS = ('nature.com', 'wiley.com', 'pnas.org', 'science.org',
                 'sciencedirect.com', 'springer.com', 'copernicus.org')

@dataclass
class AbstractResult:
    text: str = ''
    source: str = ''
    kind: str = 'abstract'
    url: str = ''

def normalize_doi(value):
    return re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', str(value).strip(), flags=re.I).lower()

def plain(value):
    soup = BeautifulSoup(html.unescape(str(value or '')), 'html.parser')
    for tag in soup(['script', 'style']):
        tag.decompose()
    return re.sub(r'\s+', ' ', soup.get_text(' ', strip=True)).strip()

def configure_cache(path):
    global _cache_path, _cache
    _cache_path = Path(path)
    try:
        loaded = json.loads(_cache_path.read_text(encoding='utf-8'))
        _cache = loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        _cache = {}

def remember(doi, result):
    _results[normalize_doi(doi)] = result
    if _cache_path is not None and result.text:
        _cache[normalize_doi(doi)] = {**asdict(result), 'checked_at': datetime.now(timezone.utc).isoformat()}
        _cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp = _cache_path.with_suffix('.tmp')
        temp.write_text(json.dumps(_cache, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        temp.replace(_cache_path)
    return result

def provenance(doi):
    return _results.get(normalize_doi(doi), AbstractResult())

def cached(doi):
    row = _cache.get(normalize_doi(doi), {})
    try:
        fresh = datetime.now(timezone.utc)-datetime.fromisoformat(row['checked_at']) < timedelta(days=30)
        if fresh and row.get('text'):
            result = AbstractResult(**{k: row[k] for k in ('text', 'source', 'kind', 'url')})
            _results[normalize_doi(doi)] = result
            return result
    except (KeyError, ValueError, TypeError):
        pass
    return AbstractResult()

def publisher_url(doi, item):
    suffix = doi.split('/', 1)[-1]
    if doi.startswith('10.1038/'):
        return 'https://www.nature.com/articles/' + suffix
    if doi.startswith('10.1029/'):
        return 'https://agupubs.onlinelibrary.wiley.com/doi/' + doi
    if doi.startswith('10.1073/'):
        return 'https://www.pnas.org/doi/' + doi
    if doi.startswith('10.1126/'):
        return 'https://www.science.org/doi/' + doi
    candidates = [(item.get('resource') or {}).get('primary', {}).get('URL'), item.get('URL')]
    for url in candidates:
        if isinstance(url, str):
            parsed = urlparse(url)
            if parsed.scheme == 'https' and any(parsed.hostname == h or (parsed.hostname or '').endswith('.'+h) for h in ALLOWED_HOSTS):
                return url
    return ''

def parse_publisher_html(document, doi, url):
    soup = BeautifulSoup(document, 'html.parser')
    doi_values = []
    for tag in soup.find_all('meta'):
        key = str(tag.get('name') or tag.get('property') or '').lower()
        if key in ('citation_doi', 'dc.identifier', 'dc.identifier.doi', 'prism.doi'):
            doi_values.append(normalize_doi(tag.get('content', '')))
    # Do not accept related-article abstracts, login pages or a redirect to a
    # different paper. Exact article DOI metadata is required.
    if normalize_doi(doi) not in doi_values:
        return AbstractResult()
    for selector in ['#Abs1-content', 'section.abstract', 'div.abstractSection',
                     '.abstract-group', '#abstract .abstract', '#abstract']:
        node = soup.select_one(selector)
        if node:
            for heading in node.find_all(['h2', 'h3', 'h4']):
                heading.decompose()
            text = plain(str(node))
            if len(text) >= 80:
                return AbstractResult(text, 'Publisher', 'abstract', url)
    for name in ('citation_abstract', 'dc.abstract', 'dcterms.abstract'):
        tag = soup.find('meta', attrs={'name': re.compile('^'+re.escape(name)+'$', re.I)})
        if tag and len(plain(tag.get('content', ''))) >= 80:
            return AbstractResult(plain(tag['content']), 'Publisher', 'abstract', url)
    # Nature briefings, editorials and comments often have an official standfirst
    # but no formal abstract. Keep the distinction; never use social/SEO snippets.
    if (urlparse(url).hostname or '').endswith('nature.com'):
        tag = soup.find('meta', attrs={'name': re.compile(r'^dc\.description$', re.I)})
        text = plain(tag.get('content', '')) if tag else ''
        if len(text) >= 80 and not re.search(r'(?:\.{3}|…)\s*$', text):
            return AbstractResult(text, 'Publisher', 'publisher_summary', url)
    return AbstractResult()

def fetch_publisher(session, doi, item, timeout):
    url = publisher_url(doi, item)
    if not url:
        return AbstractResult()
    response = session.get(url, timeout=timeout, headers={'Accept': 'text/html'})
    if response.status_code == 404:
        return AbstractResult()
    response.raise_for_status()
    return parse_publisher_html(response.text, doi, response.url)

def fetch_europe_pmc(session, doi, timeout):
    response = session.get(EUROPE_PMC, params={'query': 'DOI:'+doi, 'format': 'json',
                                             'resultType': 'core', 'pageSize': 5}, timeout=timeout)
    response.raise_for_status()
    for row in response.json().get('resultList', {}).get('result', []):
        if normalize_doi(row.get('doi', '')) == normalize_doi(doi):
            text = plain(row.get('abstractText', ''))
            if text:
                return AbstractResult(text, 'Europe PMC', 'abstract',
                                      'https://europepmc.org/article/'+row.get('source', 'MED')+'/'+row.get('id', ''))
    return AbstractResult()

def recover(session, doi, item, legacy_providers, attempts=3, timeout=15, sleep_seconds=2):
    result = cached(doi)
    if result.text:
        LOG.info('Abstract cache hit for DOI %s (%s).', doi, result.source)
        return result
    url = publisher_url(doi, item)
    publisher_key = 'Publisher:' + (urlparse(url).hostname or '')
    providers = [(publisher_key, lambda: fetch_publisher(session, doi, item, timeout)),
                 ('Europe PMC', lambda: fetch_europe_pmc(session, doi, timeout))]
    providers.extend((name, lambda f=fetch, n=name: AbstractResult(plain(f()), n))
                     for name, fetch in legacy_providers)
    for name, fetch in providers:
        if name in _disabled:
            continue
        for attempt in range(max(1, attempts)):
            try:
                result = fetch()
                if result.text:
                    LOG.info('Recovered %s for DOI %s from %s.', result.kind, doi, name)
                    return remember(doi, result)
                # An empty response is not a transient transport error. Let the
                # next provider try instead of repeating the same empty lookup.
                break
            except (requests.RequestException, ValueError, TypeError) as exc:
                response = getattr(exc, 'response', None)
                status = getattr(response, 'status_code', None)
                LOG.warning('%s abstract lookup failed (%s, HTTP %s).', name, type(exc).__name__, status)
                if status in (401, 403, 429):
                    # Shared unauthenticated API quotas must not be hammered for
                    # every DOI. Cool down this provider for the rest of the run.
                    _disabled.add(name)
                    break
                if status in (400, 404, 410, 422):
                    break
                if attempt+1 < max(1, attempts):
                    time.sleep(min(10, sleep_seconds * 2**attempt))
    return AbstractResult()
