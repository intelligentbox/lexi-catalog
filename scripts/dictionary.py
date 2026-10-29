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
    group, pos, lexical_pos, senses, pronunciations, translations = 0, None, None, [], {}, []
    for node in heading.find_all_next(['h2', 'h3', 'h4', 'h5', 'ol', 'span', 'table']):
        if node.name == 'h2':
            break
        if node.name in ('h3', 'h4', 'h5'):
            title = node.get_text(' ', strip=True).split('[')[0].strip()
            if title.startswith('Etymology'):
                group += 1
                lexical_pos = None
            pos = POS.get(title)
            if pos:
                lexical_pos = pos
        elif node.name == 'table' and 'translations' in node.get('class', []) and lexical_pos:
            gloss = node.get('data-gloss', '').strip()
            terms = []
            for span in node.select('span[lang="ru"]'):
                term = span.get_text(' ', strip=True).replace('\u0301', '')
                parent = span.find_parent('li')
                if parent and re.search(r'\b(archaic|obsolete|vulgar|offensive)\b', parent.get_text(' ', strip=True), re.I):
                    continue
                if re.fullmatch(r'[А-Яа-яЁё -]{1,60}', term) and term not in terms:
                    terms.append(term)
            if gloss and terms:
                translations.append({'group': group, 'pos': lexical_pos, 'gloss': gloss[:300], 'terms': terms[:5]})
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
                examples, collocations = [], []
                for usage in item.select('.h-usage-example'):
                    if usage.find_parent('li') is not item or usage.find_parent(class_='quotation'):
                        continue
                    sentence = usage.select_one('.e-example[lang="en"]')
                    if sentence is None:
                        continue
                    value = sentence.get_text(' ', strip=True)
                    value = re.sub(r'\s+', ' ', value).replace('“', '"').replace('”', '"')
                    value = re.sub(r'\s+([.,!?;:])', r'\1', value)
                    if not re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", value.lower()):
                        continue
                    if 'collocation' in usage.get('class', []):
                        if len(value) <= 100 and value not in collocations:
                            collocations.append(value)
                    elif 15 <= len(value) <= 220 and re.match('[A-Z]', value) and value[-1] in '.?!' and value not in examples:
                        examples.append(value)
                fragment = BeautifulSoup(str(item), 'html.parser')
                for child in fragment.select('dl, ul, ol, .HQToggle, .citation-whole, .mw-editsection'):
                    child.decompose()
                definition = re.sub(r'\s+([.,!?;:])', r'\1', fragment.get_text(' ', strip=True)).replace('“', '"').replace('”', '"')
                if 10 <= len(definition) <= 220 and not re.search(r'\b(obsolete|archaic|offensive|vulgar|slur)\b', definition, re.I):
                    senses.append({'pos': pos, 'definition': definition, 'group': group, 'examples': examples[:8], 'collocations': collocations[:8]})
    supported = []
    for sense in senses:
        p = pronunciations.get(sense['group'], pronunciations.get(0, {}))
        choices = [dict(index=i, gloss=t['gloss'], terms=t['terms']) for i, t in enumerate(t for t in translations if t['group'] == sense['group'] and t['pos'] == sense['pos'])][:12]
        if set(p) == {'uk', 'us'} and choices and sense['examples']:
            supported.append({'index': len(supported), **{k: sense[k] for k in ('pos', 'definition', 'examples', 'collocations')}, 'pronunciation': dict(p), 'translations': choices})
    if not supported:
        raise ValueError('No sense with UK/US IPA, Russian translation and a complete dictionary example')
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
