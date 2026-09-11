"""Standalone skill identity and compatibility checks; no remote writes."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SLUG = 'recursion-reiteration-engine'
TARGET = 'eidolonofficial/' + SLUG


class ReleaseIdentityTests(unittest.TestCase):
    def test_skill_front_matter(self):
        text = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        self.assertTrue(text.startswith('---\n'))
        metadata = text.split('---', 2)[1]
        self.assertIn('name: ' + SLUG, metadata.splitlines())
        self.assertIn('# Recursion Reiteration Engine\n', text)

    def test_distribution_name_and_version(self):
        text = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        self.assertIn('name = "' + SLUG + '"', text)
        self.assertIn('version = "0.4.1"', text)
        self.assertIn('dependencies = []', text)

    def test_new_and_compatible_commands(self):
        text = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        for command in ('reiterate', SLUG, 'recurse'):
            self.assertIn(command + ' = "headroom_recursion.cli:main"', text)

    def test_existing_import_namespace(self):
        from headroom_recursion import WorkspacePolicy, RecurseConfig, recurse
        from headroom_recursion.folding import ResearchBridge
        self.assertTrue(callable(recurse))
        self.assertIsNotNone(WorkspacePolicy)
        self.assertIsNotNone(RecurseConfig)
        self.assertIsNotNone(ResearchBridge)

    def test_publisher_and_manifest_agree(self):
        spec = importlib.util.spec_from_file_location('identity_publish', ROOT / 'scripts/publish.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.TARGET, TARGET)
        manifest = json.loads((ROOT / 'EXPORT_MANIFEST.json').read_text())
        self.assertEqual(manifest['target'], TARGET)
        self.assertGreater(len(module.verified_files(ROOT)), 50)

    def test_release_docs_target_only_new_destination(self):
        for name in ('README.md', 'SKILL.md', 'PUBLISHING.md', 'scripts/publish.py', 'scripts/make_manifest.py'):
            with self.subTest(file=name):
                text = (ROOT / name).read_text(encoding='utf-8')
                self.assertNotIn('eidolonofficial/headroom-recursion', text)
        self.assertIn(TARGET, (ROOT / 'PUBLISHING.md').read_text())

    def test_manifest_has_no_runtime_or_research_payload(self):
        manifest = json.loads((ROOT / 'EXPORT_MANIFEST.json').read_text())
        for name in manifest['files']:
            parts = Path(name).parts
            self.assertFalse(any(p in ('.git', '.env', 'runs', 'traces', 'models', 'weights', 'corpus') for p in parts), name)
            self.assertNotRegex(name, r'\.(?:zip|bundle|sqlite3?|pdf|gguf|safetensors|bin)$')

    def test_attribution_not_erased(self):
        text = (ROOT / 'LICENSE').read_text()
        self.assertIn('Copyright (c) headroom-recursion contributors', text)
        self.assertIn('d16a233d5e39bc416647d191dde6512d8bcd616b3dc193cc8840cca5f04a3d74',
                      (ROOT / 'PROVENANCE.md').read_text())


if __name__ == '__main__':
    unittest.main()
