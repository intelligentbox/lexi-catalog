"""Prepare a source copy only after the real public endpoint passes validation."""
import argparse
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from catalog import ROOT, read, validate
import json

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--catalog-url', required=True)
    args = parser.parse_args()
    url = urlparse(args.catalog_url)
    if url.scheme != 'https' or not url.hostname or not url.hostname.endswith('.github.io') or url.username or url.password or url.port or url.query or url.fragment or not url.path.endswith('/catalog.json'):
        raise ValueError('A direct HTTPS GitHub Pages catalog URL is required')
    with urlopen(Request(args.catalog_url, headers={'Accept': 'application/json'}), timeout=30) as response:
        if response.status != 200 or response.url != args.catalog_url:
            raise ValueError('Catalog must be public without login or redirect')
        payload = response.read(8 * 1024 * 1024 + 1)
    if len(payload) > 8 * 1024 * 1024:
        raise ValueError('Catalog too large')
    remote = validate(json.loads(payload), read(ROOT / 'data/migration-baseline.json'))
    source = args.source.resolve()
    destination = args.destination.resolve()
    if destination.exists() or destination == source or source in destination.parents:
        raise ValueError('Destination must be a new separate directory')
    store = source / 'app/src/main/java/com/lexi/english/CatalogStore.java'
    code = store.read_text(encoding='utf-8')
    if 'new URL(ORIGIN+"/catalog.json")' not in code:
        raise ValueError('Unexpected Android source; inspect before migration')
    code, count = re.subn(r'public static final String ORIGIN="[^"]+";', 'public static final String CATALOG_URL=' + json.dumps(args.catalog_url) + ';', code)
    if count != 1:
        raise ValueError('Unexpected Android endpoint configuration')
    code = code.replace('new URL(ORIGIN+"/catalog.json")', 'new URL(CATALOG_URL)')
    # A cached validator belongs to the endpoint that issued it.
    code = code.replace('String etag=prefs.getString("etag","");', 'String etag=CATALOG_URL.equals(prefs.getString("etagUrl",""))?prefs.getString("etag",""):"";')
    code = code.replace('.putString("etag",newTag==null?"":newTag)', '.putString("etag",newTag==null?"":newTag).putString("etagUrl",CATALOG_URL)')
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('build', '.gradle', '.git', '*.p12', '*.jks', '*password*', 'local.properties'))
    (destination / store.relative_to(source)).write_text(code, encoding='utf-8')
    www = destination / 'app/src/main/assets/www'
    (www / 'seed-catalog.json').write_bytes(payload)
    (www / 'seed-catalog.js').write_text('window.LEXI_SEED_CATALOG=' + json.dumps(remote, ensure_ascii=False) + ';\n', encoding='utf-8')
    print(f'Prepared Android source copy: {destination}')
    print('NEXT: update versionCode/versionName, inspect source URL references, run tests, build with the existing private signing key, and verify on a phone. This script does not create or publish an APK.')

if __name__ == '__main__':
    main()
