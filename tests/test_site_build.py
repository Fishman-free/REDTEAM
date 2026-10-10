"""Publication invariants for the integrated static presentation site."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('redteam_site_build', ROOT / 'scripts' / 'build_site.py')
site_build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site_build)


class StaticSiteTests(unittest.TestCase):
    def test_sources_include_every_menu_and_only_curated_assets(self):
        sources = site_build.validate_sources(ROOT)
        self.assertEqual(set(sources), set(site_build.SITE_FILES))
        self.assertEqual(len(site_build.ROUTES), 5)
        self.assertNotIn('server.py', sources)
        self.assertNotIn('reviewed-contribution.json', sources)

    def test_root_and_nested_entry_resolve_to_the_same_page_sources(self):
        source = (ROOT / 'docs' / 'site' / 'index.html').read_bytes()
        root = site_build.root_portal(source).decode()
        self.assertIn('data-page-root="./docs/site/"', root)
        self.assertIn('href="./docs/site/portal.css"', root)
        self.assertIn('src="./docs/site/portal.js"', root)
        for page in site_build.ROUTES.values():
            self.assertIn(f'href="./docs/site/{page}"', root)
        self.assertIn('src="./docs/site/overview.html"', root)

    def test_committed_root_and_jekyll_config_are_current(self):
        site_build.build(ROOT, check=True)

    def test_legacy_branch_build_excludes_raw_code_evidence_and_private_material(self):
        config = site_build.jekyll_config(ROOT).decode()
        excluded = {json.loads(line.strip()[2:]) for line in config.splitlines() if line.startswith('  - ')}
        for name in ('contracts', 'rsi4safety', 'archieve', 'scripts', 'tests', 'node_modules', 'docs/business', 'docs/paper', 'docs/references'):
            self.assertIn(name, excluded)
        self.assertNotIn('docs/site', excluded)
        self.assertNotIn('index.html', excluded)
        self.assertFalse((ROOT / '.nojekyll').exists())

    def test_actions_artifact_has_exact_allowlist(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'public'
            site_build.build(ROOT, output_dir=output)
            files = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
            self.assertEqual(files, {'index.html', *(f'docs/site/{name}' for name in site_build.SITE_FILES)})
            self.assertNotIn('_config.yml', files)

    def test_nonempty_bundle_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / 'keep.txt').write_text('user file')
            with self.assertRaisesRegex(ValueError, 'new or empty'):
                site_build.build(ROOT, output_dir=output)
            self.assertEqual((output / 'keep.txt').read_text(), 'user file')

    def test_flower_snapshots_are_static_same_token_and_no_raw_identity(self):
        demo = json.loads((ROOT / 'docs' / 'site' / 'flower-demo.json').read_text())
        self.assertTrue(demo['synthetic'])
        self.assertEqual(demo['network']['chainId'], 31337)
        self.assertEqual([s['label'] for s in demo['snapshots']], ['issued', 'revoked'])
        self.assertEqual(demo['snapshots'][0]['tokenId'], demo['snapshots'][1]['tokenId'])
        for forbidden in ('recipient', 'owner', 'signature', 'privateKey', 'evidence'):
            self.assertNotIn(f'"{forbidden}"', json.dumps(demo))

    def test_historical_pages_preserve_interactions_and_are_marked_archival(self):
        for name in ('archive-introduction.html', 'archive-brief.html'):
            page = (ROOT / 'docs' / 'site' / name).read_text(encoding='utf-8')
            self.assertIn('历史', page)
            self.assertIn('2026', page)
            self.assertIn('<details', page)
            self.assertIn('window.print', page)
            self.assertIn('resources.html', page)
            self.assertIn('overview.html', page)


if __name__ == '__main__':
    unittest.main()
