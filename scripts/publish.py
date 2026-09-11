"""Create-only publication of the verified export using an already authenticated gh.

Defaults to verification only. --publish explicitly creates a private repository;
--public additionally selects public visibility. No source history is ever copied.
The manifest detects accidental changes but is not an independent signature.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile

TARGET = 'eidolonofficial/recursion-reiteration-engine'


def verified_files(root: Path) -> dict[str, bytes]:
    root = root.resolve()
    manifest_path = root / 'EXPORT_MANIFEST.json'
    if manifest_path.is_symlink():
        raise ValueError('manifest must not be a symlink')
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError('unsupported manifest version')
    if manifest.get('target') != TARGET:
        raise ValueError('manifest target does not match this publishing helper')
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('manifest must list export files')
    result = {}
    for name, expected in files.items():
        if not isinstance(name, str) or not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('invalid manifest path or digest')
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '..' in relative.parts or '.git' in relative.parts
                or '\\' in name or ':' in name or '\0' in name or str(relative) != name
                or name == 'EXPORT_MANIFEST.json'):
            raise ValueError('unsafe export path')
        path = root / name
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f'symlink refused: {name}')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f'export file changed: {name}')
        result[name] = data
    result['EXPORT_MANIFEST.json'] = raw
    return result


def checked(argv: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    outcome = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, shell=False)
    if outcome.returncode:
        # External diagnostics may contain sensitive configuration. Keep them local.
        raise RuntimeError(f'{argv[0]} {argv[1]} failed with status {outcome.returncode}; '
                           'check the command locally before retrying')
    return outcome


def identity(root: Path, key: str, fallback: str) -> str:
    out = subprocess.run(['git', '-C', str(root), 'config', '--get', key],
                         capture_output=True, text=True, shell=False)
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else fallback


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true', help='create and push the checked export')
    parser.add_argument('--public', action='store_true', help='choose public instead of private visibility')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        files = verified_files(root)
        visibility = 'public' if args.public else 'private'
        print(f'Verified {len(files)} files for {TARGET}; visibility={visibility}.')
        if not args.publish:
            print('No network call or repository write performed. Add --publish to create the repository.')
            return 0
        if shutil.which('git') is None or shutil.which('gh') is None:
            raise RuntimeError('git and an already authenticated gh installation are required')
        checked(['gh', 'auth', 'status'])
        existing = subprocess.run(['gh', 'repo', 'view', TARGET, '--json', 'nameWithOwner'],
                                  capture_output=True, text=True, shell=False)
        if existing.returncode == 0:
            raise RuntimeError('destination already exists; this helper never overwrites it')
        # A denied or unavailable view does not authorize overwriting. The create
        # endpoint must still succeed; existing repositories are never updated.
        with tempfile.TemporaryDirectory(prefix='reiteration-clean-publish-') as temp:
            staged = Path(temp)
            for name, data in files.items():
                path = staged / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            checked(['git', 'init', '--template=', '-b', 'main'], cwd=staged)
            checked(['git', 'config', 'core.hooksPath', '.git/no-hooks'], cwd=staged)
            checked(['git', 'config', 'core.attributesFile', os.devnull], cwd=staged)
            checked(['git', 'config', 'core.autocrlf', 'false'], cwd=staged)
            checked(['git', 'config', 'user.name', identity(root, 'user.name', 'Clean export')], cwd=staged)
            checked(['git', 'config', 'user.email', identity(root, 'user.email', 'clean-export@localhost')], cwd=staged)
            checked(['git', 'add', '--all'], cwd=staged)
            checked(['git', '-c', 'commit.gpgsign=false', 'commit', '-m',
                     'Initial Recursion Reiteration Engine release'], cwd=staged)
            checked(['gh', 'repo', 'create', TARGET, '--' + visibility,
                     '--source', str(staged), '--remote', 'origin', '--push',
                     '--description', 'Model-neutral recursive refinement, bounded working context, and evidence-gated promotion'],
                    cwd=staged)
        print(f'Created and pushed {TARGET} with fresh root history.')
        return 0
    except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as exc:
        print(f'Publish stopped: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
