"""Versioned, append-only learning catalog shared by Android and Pages."""
import copy
import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ('A2', 'B1', 'B2', 'C1', 'C2')
LICENSE = 'https://creativecommons.org/licenses/by-sa/4.0/'
WORD = re.compile(r"[a-z][a-z '-]{0,79}\Z")
IPA = re.compile(r'/[^/<>\x00-\x1f\x7f]{1,116}/\Z')

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)

def source_url(word):
    return 'https://en.wiktionary.org/wiki/' + quote(word.replace(' ', '_'), safe="'-") + '#English'

def date(value):
    if not isinstance(value, str) or dt.date.fromisoformat(value).isoformat() != value:
        raise ValueError('Invalid date')
    return value

def text(value, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or re.search(r'[<>\x00-\x08\x0b-\x1f]', value):
        raise ValueError('Invalid text')

def validate_word(w, new=False):
    if not re.fullmatch(r'pack-[A-Za-z0-9-]{1,100}', w['id']) or w['level'] not in LEVELS or not WORD.fullmatch(w['word']):
        raise ValueError('Invalid word identity')
    for field in ('translation', 'definition', 'example', 'collocation', 'topic', 'pos'):
        text(w[field])
    if not re.search(r"(?<![a-z])" + re.escape(w['word']) + r"(?![a-z])", w['example'].lower()):
        raise ValueError('Example must contain exact headword')
    if 'pronunciation' in w or new:
        if not all(IPA.fullmatch(w['pronunciation'][k]) for k in ('uk', 'us')):
            raise ValueError('Both regional transcriptions required')
    if 'source' in w or new:
        s = w['source']
        if s['name'] != 'Wiktionary' or s['url'] != source_url(w['word']) or s['license'] != 'CC BY-SA 4.0' or s['licenseUrl'] != LICENSE:
            raise ValueError('Incorrect attribution')
        date(s['checkedOn'])
    if new:
        text(w['levelReason'], 200)
        if w['pos'] not in ('noun', 'verb', 'adjective', 'adverb') or not re.search('[А-Яа-яЁё]', w['translation']):
            raise ValueError('Russian translation and supported part of speech required')
        for field in ('definition', 'example', 'collocation', 'levelReason'):
            if not re.fullmatch(r'''[A-Za-z0-9 \t.,;:!?()'"\-/–—’]+''', w[field]):
                raise ValueError(f'{field} must be English')
        if len(w['definition']) > 220 or len(w['example']) > 220 or len(w['collocation']) > 100 or len(w['translation']) > 100:
            raise ValueError('Learning text is too long')

def validate(catalog, previous=None):
    if catalog['schema'] != 1 or type(catalog['revision']) is not int or catalog['revision'] < 1:
        raise ValueError('Unsupported catalog revision')
    words, packs = catalog['words'], catalog['packs']
    if len(words) > 20000 or len(packs) > 5000 or len(json.dumps(catalog, ensure_ascii=False).encode()) > 8 * 1024 * 1024:
        raise ValueError('Android catalog limits exceeded')
    ids, names = set(), set()
    for w in words:
        validate_word(w)
        if w['id'] in ids or w['word'].casefold() in names:
            raise ValueError('Duplicate word')
        ids.add(w['id']); names.add(w['word'].casefold())
    pack_ids = set()
    for p in packs:
        text(p['title'], 200); date(p['publishedOn'])
        if not re.fullmatch(r'[A-Za-z0-9-]{1,100}', p['id']) or p['id'] in pack_ids or p['kind'] not in ('daily', 'weekly'):
            raise ValueError('Invalid pack')
        members = p['wordIds']
        if not members or len(set(members)) != len(members) or not set(members) <= ids:
            raise ValueError('Invalid pack membership')
        pack_ids.add(p['id'])
    if previous:
        if catalog['revision'] < previous['revision']:
            raise ValueError('Revision rollback')
        by_id = {w['id']: w for w in words}
        for old in previous['words']:
            if by_id.get(old['id']) != old:
                raise ValueError('Previously published card changed or missing')
        by_pack = {p['id']: p for p in packs}
        if any(by_pack.get(p['id']) != p for p in previous['packs']):
            raise ValueError('Previously published pack changed or missing')
        if catalog != previous and catalog['revision'] <= previous['revision']:
            raise ValueError('Changed catalog must increment revision')
    return catalog

def due(catalog, today):
    iso = today.isoformat()
    # Legacy IDs are also recognized; retries never create a second daily pack.
    done = {(p['kind'], p['publishedOn']) for p in catalog['packs']}
    return [kind for kind in ('daily', 'weekly') if (kind, iso) not in done and (kind == 'daily' or today.weekday() == 0)]

def append_pack(catalog, kind, today, words, base):
    count = 1 if kind == 'daily' else 5
    if kind not in ('daily', 'weekly') or Counter(w['level'] for w in words) != Counter({l: count for l in LEVELS}):
        raise ValueError('Pack must be balanced across all five levels')
    if any(p['kind'] == kind and p['publishedOn'] == today.isoformat() for p in catalog['packs']):
        raise ValueError('Pack for this date already exists')
    used = {w['word'].casefold() for w in catalog['words'] + base}
    for w in words:
        validate_word(w, new=True)
        if w['word'].casefold() in used:
            raise ValueError('Duplicate against catalog or built-in vocabulary')
        used.add(w['word'].casefold())
    result = copy.deepcopy(catalog)
    result['words'].extend(copy.deepcopy(words))
    result['packs'].append({'id': f'{kind}-{today:%Y%m%d}', 'kind': kind, 'title': 'Слова на каждый день' if kind == 'daily' else 'Недельная практика: новые значения', 'publishedOn': today.isoformat(), 'wordIds': [w['id'] for w in words]})
    result['revision'] += 1
    result['publishedAt'] = dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')
    return validate(result, catalog)
