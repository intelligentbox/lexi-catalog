"""Commit only generated public content. Credentials exist only in this step."""
import base64
import os
import re
import subprocess

def run(*args, **kwargs):
    return subprocess.run(['git', *args], check=True, **kwargs)

def main():
    branch = os.environ['GITHUB_REF_NAME']
    repository = os.environ['GITHUB_REPOSITORY']
    token = os.environ['GH_TOKEN']
    if not re.fullmatch(r'[A-Za-z0-9._/-]+', branch) or branch.startswith('-'):
        raise ValueError('Invalid branch')
    # First browser-based installation also commits the inspected public sources.
    # Subsequent runs leave these unchanged; credentials and runtime are excluded.
    run('add', '--', 'data', 'docs', 'scripts', 'tests', 'README.md', '.gitignore', 'requirements.txt', 'runtime-lock.json', 'actions-lock.json')
    changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], check=False).returncode
    if changed == 0:
        print('No catalog changes'); return
    if changed != 1:
        raise RuntimeError('Cannot inspect staged changes')
    run('-c', 'user.name=github-actions[bot]', '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com', 'commit', '-m', 'Publish verified Lexi vocabulary update')
    auth = 'AUTHORIZATION: basic ' + base64.b64encode(('x-access-token:' + token).encode()).decode()
    # Pass through environment, not command-line arguments or files. No force push.
    env = dict(os.environ, GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.https://github.com/.extraheader', GIT_CONFIG_VALUE_0=auth)
    run('push', f'https://github.com/{repository}.git', f'HEAD:refs/heads/{branch}', env=env)

if __name__ == '__main__':
    main()
