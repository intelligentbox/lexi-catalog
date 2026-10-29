"""Pinned downloads; Linux CPU runtime for GitHub's free standard runner."""
import argparse
import hashlib
import os
import subprocess
import tarfile
import time
from pathlib import Path
from urllib.request import urlopen
from catalog import ROOT, read

def download(url, target, expected):
    if target.exists():
        with target.open('rb') as existing:
            if hashlib.file_digest(existing, 'sha256').hexdigest() == expected:
                return
    temp = target.with_suffix('.partial')
    digest = hashlib.sha256()
    with urlopen(url, timeout=120) as response, temp.open('wb') as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk); digest.update(chunk)
    if digest.hexdigest() != expected:
        temp.unlink(missing_ok=True)
        raise ValueError('Download checksum mismatch')
    temp.replace(target)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-only', action='store_true', help='Verify runtime archive without downloading the model')
    args = parser.parse_args()
    lock = read(ROOT / 'runtime-lock.json')
    directory = ROOT / '.runtime'
    directory.mkdir(exist_ok=True)
    archive = directory / 'runtime.tar.gz'
    download(lock['runtime']['url'], archive, lock['runtime']['sha256'])
    with tarfile.open(archive) as source:
        source.extractall(directory, filter='data')
    servers = list(directory.rglob('llama-server'))
    if len(servers) != 1:
        raise ValueError('Pinned runtime has no unique llama-server executable')
    if args.runtime_only:
        print(f'Runtime archive verified; server: {servers[0].name}')
        return
    model = lock['model']
    weights = directory / model['filename']
    download(f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/{model['filename']}", weights, model['sha256'])
    env = dict(os.environ)
    env['LD_LIBRARY_PATH'] = str(servers[0].parent)
    with (directory / 'server.log').open('wb') as log:
        process = subprocess.Popen([str(servers[0]), '-m', str(weights), '--alias', 'lexi-local', '--host', '127.0.0.1', '--port', '8080', '-c', '8192', '-t', '4', '-ngl', '0', '--parallel', '1', '--jinja', '--reasoning-format', 'deepseek'], stdout=log, stderr=subprocess.STDOUT, env=env)
    (directory / 'server.pid').write_text(str(process.pid))
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError('Model server stopped; see .runtime/server.log')
        try:
            with urlopen('http://127.0.0.1:8080/health', timeout=2) as response:
                if response.status == 200:
                    print('Pinned local CPU model is ready'); return
        except OSError:
            time.sleep(2)
    process.terminate()
    raise TimeoutError('Model server did not become ready')

if __name__ == '__main__':
    main()
