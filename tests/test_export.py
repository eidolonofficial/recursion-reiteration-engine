"""Release consistency tests; publication actions are mocked, never sent remotely."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('local_publish', ROOT / 'scripts' / 'publish.py')
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class ExportTests(unittest.TestCase):
    def setUp(self):
        # Publication is mocked below; do not print mock success as real status.
        quiet = patch.object(publish, 'print', create=True)
        quiet.start()
        self.addCleanup(quiet.stop)

    def fixture(self, root, name='README.md', data=b'checked file\n'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        manifest = {'schema_version': 1, 'target': publish.TARGET,
                    'files': {name: hashlib.sha256(data).hexdigest()}}
        (root / 'EXPORT_MANIFEST.json').write_text(json.dumps(manifest))
        return manifest

    def test_verified_export_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            files = publish.verified_files(root)
            self.assertEqual(files['README.md'], b'checked file\n')
            self.assertIn('EXPORT_MANIFEST.json', files)

    def test_unlisted_data_is_not_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / 'private-notes.txt').write_text('not for publication')
            self.assertNotIn('private-notes.txt', publish.verified_files(root))

    def test_changed_file_stops_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / 'README.md').write_text('modified')
            with self.assertRaisesRegex(ValueError, 'changed'):
                publish.verified_files(root)

    def test_missing_file_stops_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / 'README.md').unlink()
            with self.assertRaises(OSError):
                publish.verified_files(root)

    def test_wrong_target_stops_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.fixture(root)
            manifest['target'] = 'unrelated/repository'
            (root / 'EXPORT_MANIFEST.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'target'):
                publish.verified_files(root)

    def test_unsafe_paths_stop_export(self):
        for name in ('../escape', '/absolute', '.git/config', 'C:/escape', 'a\\b', 'x/../y'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.fixture(root)
                manifest['files'] = {name: '0' * 64}
                (root / 'EXPORT_MANIFEST.json').write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, 'unsafe'):
                    publish.verified_files(root)

    def test_symlink_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.fixture(root)
            original = root / 'original.txt'
            (root / 'README.md').rename(original)
            try:
                (root / 'README.md').symlink_to(original)
            except OSError:
                self.skipTest('symlink creation unavailable')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                publish.verified_files(root)

    def test_verify_only_never_calls_a_process(self):
        with patch.object(publish, 'verified_files', return_value={'a': b'b'}), \
             patch.object(publish.subprocess, 'run', side_effect=AssertionError('no process permitted')):
            self.assertEqual(publish.main([]), 0)

    def test_existing_destination_is_never_written(self):
        existing = subprocess.CompletedProcess([], 0, '{}', '')
        with patch.object(publish, 'verified_files', return_value={'a': b'b'}), \
             patch.object(publish.shutil, 'which', return_value='/local/tool'), \
             patch.object(publish, 'checked') as checked, \
             patch.object(publish.subprocess, 'run', return_value=existing) as runner:
            self.assertEqual(publish.main(['--publish']), 1)
            checked.assert_called_once_with(['gh', 'auth', 'status'])
            self.assertEqual(runner.call_args.args[0][1:3], ['repo', 'view'])

    def test_default_publish_is_private_and_create_only(self):
        missing = subprocess.CompletedProcess([], 1, '', '')
        calls = []
        def checked(argv, **kwargs):
            calls.append(argv)
            if argv[:3] == ['gh', 'repo', 'create']:
                staged = Path(argv[argv.index('--source') + 1])
                self.assertEqual((staged / 'README.md').read_bytes(), b'publicly-reviewed')
                self.assertEqual({p.name for p in staged.iterdir()}, {'README.md'})
            return subprocess.CompletedProcess(argv, 0, '', '')
        with patch.object(publish, 'verified_files', return_value={'README.md': b'publicly-reviewed'}), \
             patch.object(publish.shutil, 'which', return_value='/local/tool'), \
             patch.object(publish, 'checked', side_effect=checked), \
             patch.object(publish, 'identity', return_value='test-identity'), \
             patch.object(publish.subprocess, 'run', return_value=missing):
            self.assertEqual(publish.main(['--publish']), 0)
        create = next(argv for argv in calls if argv[:3] == ['gh', 'repo', 'create'])
        self.assertIn('--private', create)
        self.assertNotIn('--public', create)
        self.assertIn(publish.TARGET, create)
        self.assertFalse(any('--force' in argv or 'clone' in argv for argv in calls))

    def test_original_lean_blobs_are_preserved(self):
        originals = {
            'lean/lakefile.toml': 'ae2da41cc1136e9a70d6c4c4114c877bbd4a91e9',
            'lean/lean-toolchain': '18640c8b066b182147f324d3aefd8ee48ee45238',
            'lean/LeanOracle/Smoke.lean': 'e23a583e7aa84022766ee3cfd9c9d0a3780eaaef',
            'lean/lake-manifest.json': '6bb05201603cf949b3fee45dd6322dde23c4e4f2',
        }
        for name, expected in originals.items():
            with self.subTest(file=name):
                data = (ROOT / name).read_bytes()
                actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
                self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
