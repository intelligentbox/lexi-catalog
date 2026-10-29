import html
from catalog import ROOT, read, validate, write

def build():
    catalog = validate(read(ROOT / 'data/catalog.json'), read(ROOT / 'data/migration-baseline.json'))
    base = {w['word'].casefold() for w in read(ROOT / 'data/base-words.json')}
    if any(w['word'].casefold() in base for w in catalog['words']):
        raise ValueError('Catalog duplicates built-in vocabulary')
    # A static, complete snapshot; Android needs no account or secret.
    output = ROOT / 'docs'
    output.mkdir(exist_ok=True)
    write(output / 'catalog.json', catalog)
    (output / '.nojekyll').write_text('')
    rows = ''.join('<li><strong>' + html.escape(p['title']) + '</strong><br>' + html.escape(p['publishedOn']) + ' · ' + str(len(p['wordIds'])) + ' слов</li>' for p in reversed(catalog['packs'][-15:]))
    page = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Lexi — открытый каталог</title>
<style>body{font:17px/1.6 system-ui,sans-serif;background:#f7f7fc;color:#292634;max-width:720px;margin:auto;padding:32px 20px}h1{font-size:36px;line-height:1.15}a{color:#6550a5}section{background:white;padding:24px;border-radius:18px;margin:24px 0}li{margin:16px 0}small{color:#5d5a67}</style>
<header><small>LEXI · A2–C2</small><h1>Слова для ежедневной практики</h1><p>Открытый каталог учебных карточек для Android.</p></header>
<section><strong>__COUNT__ слов · версия __REVISION__</strong><p>Последняя публикация: __DATE__</p><p><a href="catalog.json">Скачать каталог JSON</a></p></section>
<section><h2>Последние подборки</h2><ul>__ROWS__</ul></section>
<section><h2>Как это работает</h2><p>Задача GitHub Actions готовит новые карточки по статьям Wiktionary. Модель адаптирует английские определения и составляет примеры. Русские переводы и транскрипции UK/US берутся из словарной статьи. Уровни CEFR ориентировочные. Нужна дополнительная редакторская проверка сложных и спорных значений.</p><p>В карточках сохранены ссылки на источники, даты и лицензия <a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>. Карточки прежнего каталога сохранены без изменения.</p><p>Телефон сохраняет загруженные слова для работы офлайн. Личный прогресс и свои слова не передаются в каталог. Если обновление задержалось или не прошло проверки, предыдущий выпуск остаётся доступен.</p></section></html>'''
    page = page.replace('__COUNT__', str(len(catalog['words']))).replace('__REVISION__', str(catalog['revision'])).replace('__DATE__', html.escape(catalog['publishedAt'])).replace('__ROWS__', rows)
    (output / 'index.html').write_text(page, encoding='utf-8')
    print(f"Built static catalog: {len(catalog['words'])} words, revision {catalog['revision']}")

if __name__ == '__main__':
    build()
