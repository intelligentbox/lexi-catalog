"""Read dictionary evidence, never instructions. No Cambridge/MW scraping."""
import re
import time
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup
from catalog import IPA, WORD, source_url

UK = re.compile(r'\b(UK|British|Received Pronunciation|RP|Standard Southern British)\b', re.I)
US = re.compile(r'\b(US|USA|American|General American|GA)\b', re.I)
POS = {'Noun': 'noun', 'Verb': 'verb', 'Adjective': 'adjective', 'Adverb': 'adverb'}

def parse_article(html, word):
    soup = BeautifulSoup(html, 'html.parser')
    marker = soup.find(id='English')
    if marker is None:
        raise ValueError('English section not found')
    heading = marker if marker.name == 'h2' else marker.find_parent('h2')
    if heading is None:
        raise ValueError('Unexpected dictionary markup')
    group, pos, senses, pronunciations = 0, None, [], {}
    for node in heading.find_all_next(['h2', 'h3', 'h4', 'h5', 'ol', 'span']):
        if node.name == 'h2':
            break
        if node.name in ('h3', 'h4', 'h5'):
            title = node.get_text(' ', strip=True).split('[')[0].strip()
            if title.startswith('Etymology'):
                group += 1
            pos = POS.get(title)
        elif node.name == 'span' and 'IPA' in node.get('class', []):
            ipa = node.get_text('', strip=True)
            li = node.find_parent('li')
            if not li or not IPA.fullmatch(ipa):
                continue
            # Only labels preceding this IPA in the same item describe its accent.
            prefix = li.decode().split(str(node), 1)[0]
            label = BeautifulSoup(prefix, 'html.parser').get_text(' ', strip=True)
            regions = [name for name, pattern in (('uk', UK), ('us', US)) if pattern.search(label)]
            if regions:
                bucket = pronunciations.setdefault(group, {})
                for name in regions:
                    bucket.setdefault(name, ipa)
        elif node.name == 'ol' and pos and node.find_parent(['ol', 'ul', 'dl']) is None:
            for item in node.find_all('li', recursive=False):
                fragment = BeautifulSoup(str(item), 'html.parser')
                for child in fragment.select('dl, ul, ol, .HQToggle, .citation-whole, .mw-editsection'):
                    child.decompose()
                definition = fragment.get_text(' ', strip=True)
                if 10 <= len(definition) <= 500 and not re.search(r'\b(obsolete|archaic|offensive|vulgar|slur)\b', definition, re.I):
                    senses.append({'pos': pos, 'definition': definition, 'group': group})
    supported = []
    for sense in senses:
        p = pronunciations.get(sense['group'], pronunciations.get(0, {}))
        if set(p) == {'uk', 'us'}:
            supported.append({'index': len(supported), 'pos': sense['pos'], 'definition': sense['definition'], 'pronunciation': dict(p)})
    if not supported:
        raise ValueError('No sense with explicitly labelled UK and US transcriptions')
    return {'word': word, 'url': source_url(word), 'senses': supported[:12]}

def fetch_article(word, repository, cache=None):
    if not WORD.fullmatch(word) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid word or repository')
    url = source_url(word)
    if cache:
        saved = cache / (word.replace(' ', '_') + '.html')
        if saved.exists():
            return parse_article(saved.read_text(encoding='utf-8'), word)
    # Sequential and deliberately infrequent; no retries on rate limiting.
    time.sleep(1)
    req = Request(url, headers={'User-Agent': f'LexiCatalog/1.0 (educational vocabulary; https://github.com/{repository})', 'Accept': 'text/html'})
    with urlopen(req, timeout=40) as response:
        if response.url.split('#')[0] != url.split('#')[0]:
            raise ValueError('Unexpected dictionary redirect')
        body = response.read(3 * 1024 * 1024 + 1)
    if len(body) > 3 * 1024 * 1024:
        raise ValueError('Dictionary page too large')
    return parse_article(body.decode('utf-8'), word)
