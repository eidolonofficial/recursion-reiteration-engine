"""Rebuild the release allowlist after intentional source edits; never include runs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT_FILES = ('.gitignore', 'AGENTS.md', 'LICENSE', 'PUBLISHING.md', 'PROVENANCE.md',
              'README.md', 'SKILL.md', 'TESTING.md', 'pyproject.toml')
TREE_PATTERNS = {'src': '*.py', 'tests': '*.py', 'examples': '*.py',
                 'scripts': '*.py', 'references': '*.md', 'benchmarks': '*.py'}
LEAN_FILES = ('lean/.gitignore', 'lean/LeanOracle.lean', 'lean/LeanOracle/Smoke.lean',
              'lean/lakefile.toml', 'lean/lean-toolchain', 'lean/lake-manifest.json')


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [root / name for name in (*ROOT_FILES, *LEAN_FILES)]
    for directory, pattern in TREE_PATTERNS.items():
        paths.extend((root / directory).rglob(pattern))
    files = {}
    for path in sorted(paths):
        relative = path.relative_to(root)
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root):
            raise ValueError(f'symlink is not an export source: {relative}')
        data = path.read_bytes()
        data.decode('utf-8')
        files[relative.as_posix()] = hashlib.sha256(data).hexdigest()
    manifest = {'schema_version': 1, 'target': 'eidolonofficial/recursion-reiteration-engine',
                'source_commit': '23e6758e3b95510736711c9eb09d68fbf91063be',
                'files': files}
    (root / 'EXPORT_MANIFEST.json').write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode('utf-8'))
    print(f'Recorded {len(files)} reviewed export files; manifest is not a signature.')


if __name__ == '__main__':
    main()
