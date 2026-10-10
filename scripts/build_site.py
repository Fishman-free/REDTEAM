"""Validate and publish one self-contained REDTEAM HTML document."""
from __future__ import annotations

import argparse
import base64
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SECTION_IDS = ('overview', 'arena', 'evidence', 'flower', 'services', 'roadmap', 'governance', 'faq', 'resources')
EXCLUDED_ROOTS = (
    'docs', 'archieve', 'artifacts', 'cache', 'contracts', 'docker', 'node_modules',
    'redteam', 'rsi4safety', 'scripts', 'src', 'sut', 'tests', 'README.md',
    'pytest.ini', 'requirements-dev.txt',
)
VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
SVG_NS = 'http://www.w3.org/2000/svg'


class SingleDocument(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.references = []
        self.dependencies = []
        self.forbidden_tags = []
        self.scripts = []
        self.styles = []
        self.sections = {}
        self.visible_text = []
        self.tags = []
        self.stack = []
        self.script = None
        self.in_style = False
        self.faq_count = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag in {'iframe', 'object', 'embed', 'base'} or 'srcdoc' in attrs:
            self.forbidden_tags.append(tag)
        if tag == 'a' and 'href' in attrs:
            self.references.append(attrs['href'])
        if tag in {'script', 'img', 'source', 'video', 'audio'} and 'src' in attrs:
            self.dependencies.append(attrs['src'])
        if tag == 'link' and attrs.get('rel', '').lower() not in {'canonical'}:
            self.dependencies.append(attrs.get('href', ''))
        if tag == 'script':
            self.script = {'id': attrs.get('id'), 'type': attrs.get('type', ''), 'text': []}
            self.scripts.append(self.script)
        if tag == 'style':
            self.in_style = True
        key = attrs.get('data-content-key')
        if key:
            if key in self.sections:
                raise ValueError(f'Duplicate content chapter: {key}')
            self.sections[key] = []
        inherited = self.stack[-1][1] if self.stack else None
        if tag not in VOID_TAGS:
            self.stack.append((tag, key or inherited))
        if tag == 'details' and (key == 'faq' or inherited == 'faq'):
            self.faq_count += 1

    def handle_endtag(self, tag):
        if tag == 'script':
            self.script = None
        if tag == 'style':
            self.in_style = False
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.script is not None:
            self.script['text'].append(data)
        elif self.in_style:
            self.styles.append(data)
        else:
            self.visible_text.append(data)
            for key in {entry[1] for entry in self.stack if entry[1]}:
                self.sections[key].append(data)

    def text(self, key=None):
        return ' '.join(self.sections[key] if key else self.visible_text)


def validate_svg_uri(uri: str):
    prefix = 'data:image/svg+xml;base64,'
    if not isinstance(uri, str) or not uri.startswith(prefix):
        raise ValueError('Images must be embedded SVG data')
    raw = base64.b64decode(uri[len(prefix):], validate=True)
    if len(raw) > 200000 or b'<!' in raw:
        raise ValueError('Unsupported SVG data')
    svg = ElementTree.fromstring(raw)
    if svg.tag != '{' + SVG_NS + '}svg':
        raise ValueError('Invalid SVG namespace')
    allowed = {'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'title', 'desc', 'text', 'tspan', 'defs', 'linearGradient', 'radialGradient', 'stop'}
    for element in svg.iter():
        if not element.tag.startswith('{' + SVG_NS + '}') or element.tag.split('}', 1)[1] not in allowed:
            raise ValueError('Executable or unsupported SVG element')
        for name, value in element.attrib.items():
            if re.search(r'on\w+|href|src|style', name, re.I) or re.search(r'https?:|javascript:|data:|@import', value, re.I):
                raise ValueError('SVG must not execute code or load resources')
            if 'url(' in value and not re.fullmatch(r'url\(#[A-Za-z0-9_-]+\)', value):
                raise ValueError('Unsupported SVG resource')


def inspect_document(source: bytes) -> SingleDocument:
    document = SingleDocument()
    document.feed(source.decode('utf-8'))
    document.close()
    if document.forbidden_tags:
        raise ValueError('A consolidated HTML must not contain iframe/object/embed/base/srcdoc')
    if any(document.tags.count(tag) != 1 for tag in ('html', 'body', 'main')):
        raise ValueError('Expected one actual HTML document and one main content body')
    if len(document.ids) != len(set(document.ids)):
        raise ValueError('Duplicate HTML IDs')
    if set(document.sections) != set(SECTION_IDS):
        raise ValueError('Every substantive content chapter must be in the same document')
    for key in SECTION_IDS:
        if key not in document.ids or len(re.sub(r'\s+', '', document.text(key))) < 80:
            raise ValueError(f'Chapter {key} is missing substantive inline content')
    if document.faq_count < 12:
        raise ValueError('The combined FAQ must cover the original substantive questions')
    for ref in document.references:
        if ref.startswith('#'):
            if unquote(ref[1:]) not in document.ids:
                raise ValueError(f'Missing in-document navigation target: {ref}')
        elif not ref.startswith('https://'):
            raise ValueError(f'Content cannot depend on another page: {ref}')
    for dependency in document.dependencies:
        validate_svg_uri(dependency)
    for css in document.styles:
        if '@import' in css or re.search(r'url\(\s*["\']?(?:https?:|//|\./|/)', css, re.I):
            raise ValueError('Styles must be self-contained')
    for script in document.scripts:
        if script['type'] == 'application/json':
            continue
        code = ''.join(script['text'])
        if re.search(r'\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bimport\s*\(', code):
            raise ValueError('Single-page content must not be fetched or imported')
    return document


def validate_source(root: Path) -> bytes:
    if (root / '.nojekyll').exists():
        raise ValueError('.nojekyll would bypass publication exclusions')
    source_path = root / 'docs' / 'site' / 'index.html'
    if source_path.is_symlink() or not source_path.is_file():
        raise ValueError('Missing or linked canonical single-page source')
    source = source_path.read_bytes()
    document = inspect_document(source)
    scripts = [s for s in document.scripts if s['id'] == 'flower-demo-data' and s['type'] == 'application/json']
    if len(scripts) != 1:
        raise ValueError('Flower snapshots must be embedded exactly once')
    demo = json.loads(''.join(scripts[0]['text']))
    original = json.loads((root / 'docs' / 'site' / 'flower-demo.json').read_text(encoding='utf-8'))
    if demo != original:
        raise ValueError('Embedded Flower data must match the verified local export')
    if demo.get('protocol') != 'redteam-flower-demo-v1' or demo.get('synthetic') is not True:
        raise ValueError('Only synthetic Flower snapshots may be published')
    if demo.get('network') != {'name': 'hardhat', 'chainId': 31337, 'forked': False}:
        raise ValueError('No public-chain deployment claims in the sample')
    snapshots = demo.get('snapshots', [])
    if len(snapshots) != 2 or snapshots[0]['tokenId'] != snapshots[1]['tokenId']:
        raise ValueError('Expected two historical states of one local NFT')
    for snapshot in snapshots:
        validate_svg_uri(snapshot['metadata']['image'])
    return source


def jekyll_config(root: Path) -> bytes:
    excluded = set(EXCLUDED_ROOTS)
    excluded.update(entry.name for entry in root.iterdir() if not entry.name.startswith(('.', '_')) and entry.name != 'index.html')
    lines = ['# Generated: the Pages website contains only the consolidated index.html.',
             'title: REDTEAM', 'url: "https://fishman-free.github.io"', 'baseurl: "/REDTEAM"', 'exclude:']
    lines.extend('  - ' + json.dumps(name, ensure_ascii=False) for name in sorted(excluded))
    return ('\n'.join(lines) + '\n').encode('utf-8')


def build(root: Path, *, check=False, output_dir: Path | None = None):
    source = validate_source(root)
    if output_dir is not None:
        output_dir = output_dir.resolve()
        if output_dir == root.resolve() or output_dir.is_relative_to((root / 'docs').resolve()):
            raise ValueError('Bundle must not overwrite source files')
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ValueError('Bundle destination must be new or empty')
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / 'index.html').write_bytes(source)
        return
    for name, data in {'index.html': source, '_config.yml': jekyll_config(root)}.items():
        target = root / name
        if check:
            if not target.is_file() or target.read_bytes() != data:
                raise ValueError(f'Generated {name} is stale; run python scripts/build_site.py')
        else:
            if target.is_symlink():
                raise ValueError(f'Refusing linked generated file: {name}')
            target.write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    build(ROOT, check=args.check, output_dir=args.output_dir)
    print(f'Validated {len(SECTION_IDS)} inline chapters; publishing exactly one self-contained HTML')


if __name__ == '__main__':
    main()
