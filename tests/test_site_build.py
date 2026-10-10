"""Test actual inline content and the one-file publication boundary."""
import base64
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('redteam_site_build', ROOT / 'scripts' / 'build_site.py')
site_build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site_build)


class SinglePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = site_build.validate_source(ROOT)
        cls.document = site_build.inspect_document(cls.source)

    def test_one_document_not_a_multi_page_wrapper(self):
        self.assertEqual(self.document.tags.count('html'), 1)
        self.assertEqual(self.document.tags.count('body'), 1)
        self.assertEqual(self.document.tags.count('main'), 1)
        self.assertFalse(self.document.forbidden_tags)
        self.assertNotIn('iframe', self.document.tags)
        self.assertNotIn('object', self.document.tags)
        self.assertNotIn('embed', self.document.tags)

    def test_css_js_and_artwork_have_no_external_runtime_dependencies(self):
        self.assertTrue(self.document.styles)
        self.assertTrue(self.document.scripts)
        for uri in self.document.dependencies:
            site_build.validate_svg_uri(uri)
        code = '\n'.join(''.join(script['text']) for script in self.document.scripts if script['type'] != 'application/json')
        self.assertNotRegex(code, r'\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bimport\s*\(')
        self.assertNotRegex('\n'.join(self.document.styles), r'@import')

    def test_root_file_is_identical_to_the_self_contained_source(self):
        self.assertEqual((ROOT / 'index.html').read_bytes(), self.source)
        site_build.build(ROOT, check=True)

    def test_all_content_chapters_are_actual_inline_text(self):
        self.assertEqual(set(self.document.sections), set(site_build.SECTION_IDS))
        for key in site_build.SECTION_IDS:
            with self.subTest(chapter=key):
                self.assertGreater(len(re.sub(r'\s+', '', self.document.text(key))), 80)
                self.assertIn(key, self.document.ids)

    def test_in_document_links_do_not_load_different_html_pages(self):
        anchors = [ref for ref in self.document.references if ref.startswith('#')]
        self.assertGreaterEqual(len(anchors), 8)
        for ref in anchors:
            self.assertIn(ref[1:], self.document.ids)
        for ref in self.document.references:
            self.assertTrue(ref.startswith(('#', 'https://')), ref)

    def test_seven_business_tools_are_explained_in_body(self):
        text = self.document.text('arena')
        for tool in ('search_catalog', 'get_product', 'get_order', 'get_payment_status', 'create_invoice', 'pay_order', 'finish_task'):
            self.assertIn(tool, text)
        for surface in ('dialogue', 'tool_return', 'document', 'memory'):
            self.assertIn(surface, text)
        for scope in ('L0', 'L1'):
            self.assertIn(scope, text)

    def test_current_evidence_is_inline_with_its_limits(self):
        text = self.document.text('evidence')
        for marker in ('2026-10-05', 'live.v3', '12', '449', '460', '549', '1665', '2517', '4096', '20%', '100%'):
            self.assertIn(marker, text)
        self.assertRegex(text, r'开放|未解决')
        self.assertRegex(text, r'生产安全|生产认证')
        self.assertIn('Qwen/Qwen3-4B-Instruct-2507', text)
        self.assertIn('glm-5.3', text)

    def test_flower_is_a_full_inline_product_explanation(self):
        text = self.document.text('flower')
        for marker in ('ERC-721', 'ERC-5192', 'EIP-712', 'nonce', 'deadline', '31337'):
            self.assertIn(marker, text)
        for phrase in ('撤销', '转让', '隐私', '身份', 'gas'):
            self.assertIn(phrase, text)

    def test_business_material_is_not_relegated_to_external_link_cards(self):
        text = self.document.text('services')
        for phrase in ('评测', '整改', '回归', '授权', '隔离', '复核', '税'):
            self.assertIn(phrase, text)
        self.assertRegex(text, r'发票|开票')
        self.assertRegex(text, r'收入|收费')
        self.assertRegex(text, r'成本')
        self.assertRegex(text, r'待验证|假设')
        self.assertGreater(len(re.sub(r'\s+', '', text)), 500)

    def test_roadmap_and_collaboration_are_in_the_same_body(self):
        text = self.document.text('roadmap')
        for marker in ('30', '60', '90'):
            self.assertIn(marker, text)
        for phrase in ('合作', '企业', '高校', '算力'):
            self.assertIn(phrase, text)

    def test_governance_and_legal_uncertainty_are_inline(self):
        text = self.document.text('governance')
        for phrase in ('授权', '漏洞', '隐私', '资金', '停止'):
            self.assertIn(phrase, text)
        self.assertRegex(text, r'未核验|未独立核验|待核验')
        self.assertRegex(text, r'合法|法律')

    def test_merged_faq_contains_at_least_twelve_questions(self):
        self.assertGreaterEqual(self.document.faq_count, 12)
        self.assertGreater(len(self.document.text('faq')), 500)

    def test_embedded_demo_equals_verified_local_export(self):
        data = next(s for s in self.document.scripts if s['id'] == 'flower-demo-data')
        demo = json.loads(''.join(data['text']))
        original = json.loads((ROOT / 'docs' / 'site' / 'flower-demo.json').read_text())
        self.assertEqual(demo, original)
        self.assertEqual([s['label'] for s in demo['snapshots']], ['issued', 'revoked'])
        self.assertEqual(demo['snapshots'][0]['tokenId'], demo['snapshots'][1]['tokenId'])
        self.assertEqual(demo['snapshots'][0]['metadata']['image'], demo['snapshots'][1]['metadata']['image'])
        for forbidden in ('recipient', 'owner', 'signature', 'privateKey', 'evidence'):
            self.assertNotIn(f'"{forbidden}"', json.dumps(demo))

    def test_actions_artifact_contains_only_one_html(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'published'
            site_build.build(ROOT, output_dir=output)
            files = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
            self.assertEqual(files, {'index.html'})
            self.assertEqual((output / 'index.html').read_bytes(), self.source)

    def test_legacy_pages_excludes_all_old_htmls_and_raw_research(self):
        config = site_build.jekyll_config(ROOT).decode()
        excluded = {json.loads(line.strip()[2:]) for line in config.splitlines() if line.startswith('  - ')}
        for name in ('docs', 'contracts', 'rsi4safety', 'archieve', 'scripts', 'tests', 'node_modules'):
            self.assertIn(name, excluded)
        self.assertNotIn('index.html', excluded)
        self.assertFalse((ROOT / '.nojekyll').exists())

    def test_nonempty_bundle_target_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            keep = Path(temp) / 'keep.txt'
            keep.write_text('existing user material')
            with self.assertRaisesRegex(ValueError, 'new or empty'):
                site_build.build(ROOT, output_dir=Path(temp))
            self.assertEqual(keep.read_text(), 'existing user material')

    def test_malformed_multi_page_dependencies_are_rejected(self):
        for injection in ('<iframe src="overview.html"></iframe>', '<object data="flower.html"></object>', '<embed src="other.html">', '<script src="portal.js"></script>', '<link rel="stylesheet" href="portal.css">', '<script>fetch("flower-demo.json")</script>'):
            with self.subTest(injection=injection):
                altered = self.source.replace(b'</body>', injection.encode() + b'</body>')
                with self.assertRaises(ValueError):
                    site_build.inspect_document(altered)

    def test_unsafe_embedded_svg_is_rejected(self):
        malicious = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        uri = 'data:image/svg+xml;base64,' + base64.b64encode(malicious.encode()).decode()
        with self.assertRaisesRegex(ValueError, 'unsupported SVG'):
            site_build.validate_svg_uri(uri)


if __name__ == '__main__':
    unittest.main()
