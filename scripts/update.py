import argparse
import datetime as dt
import os
import re
from collections import deque
from pathlib import Path
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo
from catalog import ROOT, LEVELS, LICENSE, WORD, append_pack, due, read, validate, validate_word, write
from dictionary import fetch_article
from model import LocalModel, CARD_SCHEMA, CANDIDATE_SCHEMA, REVIEW_SCHEMA, DRAFT, REVIEW, TOPICS

def make_card(model, article, level, today):
    feedback = None
    for attempt in range(2):
        try:
            return _make_card(model, article, level, today, feedback)
        except ValueError as error:
            # One corrective attempt for malformed writing, never for a rejected meaning.
            feedback = str(error)
            if attempt or feedback in ('No suitable sense', 'Linguistic review rejected card'):
                raise

def _make_card(model, article, level, today, feedback):
    # The model only sees English evidence, never the Russian terms or IPA.
    evidence = {'word': article['word'], 'senses': [{k: s[k] for k in ('index', 'pos', 'definition', 'examples', 'collocations')} | {'translations': [{'index': t['index'], 'gloss': t['gloss']} for t in s['translations']]} for s in article['senses']]}
    request = {'level': level, 'article': evidence, 'requiredExampleWord': article['word']}
    if feedback:
        request['previousValidationError'] = feedback
    draft = model.complete(DRAFT, request, CARD_SCHEMA)
    if draft.get('suitable') is not True or type(draft.get('senseIndex')) is not int or not 0 <= draft['senseIndex'] < len(article['senses']):
        raise ValueError('No suitable sense')
    sense = article['senses'][draft['senseIndex']]
    ei = draft.get('exampleIndex')
    if type(ei) is not int or not 0 <= ei < len(sense['examples']):
        raise ValueError('No dictionary example selected')
    ti = draft.get('translationIndex')
    if type(ti) is not int or not 0 <= ti < len(sense['translations']):
        raise ValueError('No matching dictionary translation selected')
    translation = sense['translations'][ti]
    if draft.get('topic') not in TOPICS:
        raise ValueError('Unsupported topic')
    word = article['word']
    card = {'id': f"pack-{today:%Y%m%d}-{level.lower()}-{re.sub('[^a-z0-9]+', '-', word).strip('-')}", 'word': word, 'level': level, 'pos': sense['pos'], 'pronunciation': sense['pronunciation'],
            **{k: draft[k] for k in ('definition', 'collocation', 'levelReason')},
            'example': sense['examples'][ei], 'exampleOrigin': 'dictionary',
            'translation': translation['terms'][0], 'translationGloss': translation['gloss'], 'topic': TOPICS[draft['topic']],
            'source': {'name': 'Wiktionary', 'url': article['url'], 'checkedOn': today.isoformat(), 'attribution': 'Wiktionary contributors', 'license': 'CC BY-SA 4.0', 'licenseUrl': LICENSE, 'adapted': True}}
    if sense['collocations']:
        card['collocation'] = sense['collocations'][0]
    validate_word(card, new=True)
    if word not in card['collocation'].lower():
        raise ValueError('Collocation missing headword')
    # Avoid simply republishing a full source definition as generated writing.
    if card['definition'].strip().lower() == sense['definition'].strip().lower():
        raise ValueError('Definition not adapted')
    review = model.complete(REVIEW, {'card': {k: card[k] for k in ('word', 'level', 'pos', 'definition', 'example', 'collocation', 'translationGloss', 'levelReason')}, 'sourceDefinition': sense['definition']}, REVIEW_SCHEMA)
    if set(review) != set(REVIEW_SCHEMA['properties']) or not all(v is True for v in review.values()):
        raise ValueError('Linguistic review rejected card')
    return card

def generate(catalog, base, model, today, repository, fetch=fetch_article):
    result = catalog
    used = {w['word'].casefold() for w in catalog['words'] + base}
    attempted = set(used)
    seeds = read(ROOT / 'data/candidates.json')
    queues = {level: deque(w for w in seeds[level] if w not in used) for level in LEVELS}
    for kind in due(catalog, today):
        cards = []
        for level in LEVELS:
            accepted = 0
            target = 1 if kind == 'daily' else 5
            for attempt in range(target * 40):
                if not queues[level]:
                    proposal = model.complete('Propose 12 useful English headwords for the requested CEFR level, varied everyday topics, lowercase spelling. No names, phrases longer than two words, offensive or technical words. Exclude listed words. A dictionary will independently verify each proposal.', {'level': level, 'exclude': sorted(attempted)[-600:]}, CANDIDATE_SCHEMA)
                    words = proposal.get('words', [])
                    if not isinstance(words, list) or len(words) > 12:
                        raise ValueError('Invalid candidate response')
                    queues[level].extend(w for w in words if isinstance(w, str) and WORD.fullmatch(w) and w not in attempted)
                    if not queues[level]:
                        continue
                word = queues[level].popleft()
                if word in attempted:
                    continue
                attempted.add(word)
                try:
                    article = fetch(word, repository)
                    card = make_card(model, article, level, today)
                except HTTPError as error:
                    if error.code in (403, 429, 503):
                        raise RuntimeError('Dictionary access limited; preserving existing catalog') from error
                    print(f'Skipped {level} {word}: HTTP {error.code}')
                    continue
                except ValueError as error:
                    print(f'Skipped {level} {word}: {error}')
                    continue
                cards.append(card); used.add(word); accepted += 1
                print(f'Accepted {level} {word}')
                if accepted == target:
                    break
            if accepted != target:
                raise RuntimeError(f'Could not prepare a complete {kind} pack at {level}; no publication')
        result = append_pack(result, kind, today, cards, base)
    return validate(result, catalog)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--date', type=dt.date.fromisoformat)
    args = parser.parse_args()
    today = args.date or dt.datetime.now(ZoneInfo('Europe/Moscow')).date()
    previous = validate(read(ROOT / 'data/catalog.json'))
    kinds = due(previous, today)
    if args.plan:
        print(','.join(kinds) or 'up-to-date')
        output = os.environ.get('GITHUB_OUTPUT')
        if output:
            with open(output, 'a', encoding='utf-8') as file:
                file.write(f"needed={'true' if kinds else 'false'}\n")
        return
    if not kinds:
        print('Catalog is already current'); return
    repository = os.environ.get('GITHUB_REPOSITORY', '')
    if not repository:
        raise ValueError('GITHUB_REPOSITORY is required for source attribution')
    result = generate(previous, read(ROOT / 'data/base-words.json'), LocalModel(), today, repository)
    write(ROOT / 'data/catalog.json', result)
    print(f"Prepared revision {result['revision']}: {len(result['words'])} words; nothing has been published by this script")

if __name__ == '__main__':
    main()
