"""Readable publication titles without displaying publisher HTML markup."""
import html
import re
from bs4 import BeautifulSoup

_SUBSCRIPT = str.maketrans('0123456789+-=()', '₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎')

def clean_title(value):
    text = str(value or '')
    # Crossref and archived selections can contain encoded markup.
    for _ in range(2):
        text = html.unescape(text)
    def subscript(match):
        inner = BeautifulSoup(match.group(1), 'html.parser').get_text().strip()
        return inner.translate(_SUBSCRIPT)
    text = re.sub(r'\s*<(?:[\w-]+:)?sub\b[^>]*>(.*?)</(?:[\w-]+:)?sub\s*>',
                  subscript, text, flags=re.I | re.S)
    text = BeautifulSoup(text, 'html.parser').get_text()
    return re.sub(r'\s+', ' ', text).strip()
