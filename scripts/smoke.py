"""Integration check on the real runner, without altering the public catalog."""
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo
from catalog import ROOT, LEVELS, read
from dictionary import fetch_article
from model import LocalModel
from update import make_card

def main():
    today = dt.datetime.now(ZoneInfo('Europe/Moscow')).date()
    repository = os.environ['GITHUB_REPOSITORY']
    model = LocalModel()
    candidates = read(ROOT / 'data/candidates.json')
    report = []
    for level in LEVELS:
        for word in candidates[level][:8]:
            try:
                card = make_card(model, fetch_article(word, repository), level, today)
            except ValueError as error:
                print(f'Skipped {word}: {error}'); continue
            report.append(card)
            print(json.dumps(card, ensure_ascii=False))
            break
        else:
            raise RuntimeError(f'No accepted integration sample for {level}')
    print(f'PASS: {len(report)} complete real-source cards; no catalog changes')

if __name__ == '__main__':
    main()
