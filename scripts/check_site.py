#!/usr/bin/env python3
"""Validate the generated static archive without HTTP or third-party packages.

Run after a build: python3 scripts/check_site.py dist
Use --english-only after a deliberately degraded build. --structural-only is
useful for inspecting an isolated output, but CI should use source comparisons.
All local references are resolved once against an inventory; Unicode URL paths
are decoded. Neither source checkouts nor generated files are changed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
import gzip
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import zlib
from urllib.parse import unquote, urljoin, urlsplit
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://remnant.truechristian.church'
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
PRIVATE_KEYS = {'source_metadata', 'source_translation_key', 'translation_key', 'html_sha256',
                'runtime_state', 'review_candidates', 'translation_omissions', 'api_key',
                'access_token', 'refresh_token', 'private_key', 'campaign_state', 'prompt', 'prompts',
                'password', 'client_secret', 'authorization', 'worker_state'}
PRIVATE_NAMES = {'build-report.json', 'source-report.json', 'manifest.json', 'catalogue.json',
                 'navigation.json', 'campaign.json', 'state.json', '.env', 'credentials.json'}
SECRET = re.compile(r'(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b|\bsk-[A-Za-z0-9_-]{32,}\b)')


def normalized_text(text):
    return re.sub(r'\s+', ' ', text).strip()


def public_route(relative):
    if relative == 'index.html':
        return '/'
    return '/' + (relative[:-10] if relative.endswith('/index.html') else relative)


@dataclass
class Page:
    route: str
    lang: str = ''
    direction: str = ''
    canonical: list = field(default_factory=list)
    alternates: dict = field(default_factory=dict)
    references: set = field(default_factory=set)
    ids: set = field(default_factory=set)
    duplicate_ids: set = field(default_factory=set)
    noindex: bool = False
    redirect: str | None = None
    title: str = ''
    h1: str = ''
    main_text: str = ''
    article_ids: list = field(default_factory=list)
    contents: list = field(default_factory=list)
    sequences: list = field(default_factory=list)
    category_links: list = field(default_factory=list)
    issue_links: list = field(default_factory=list)
    downloads: set = field(default_factory=set)
    notices: int = 0
    config: dict | None = None
    languages: dict = field(default_factory=dict)
    selected: list = field(default_factory=list)
    copy_markdown: str | None = None
    chrome: set = field(default_factory=set)
    footer_links: list = field(default_factory=list)
    errors: list = field(default_factory=list)


class PageParser(HTMLParser):
    """Small semantic inventory; does not keep DOMs for thousands of pages."""
    def __init__(self, route, source):
        super().__init__(convert_charrefs=True)
        self.page = Page(route)
        self.stack = []
        self.parts = {'title': [], 'h1': [], 'main': [], 'sequence': [], 'config': []}
        self.feed(source)
        self.close()
        p = self.page
        p.title = normalized_text(''.join(self.parts['title']))
        p.h1 = normalized_text(''.join(self.parts['h1']))
        p.main_text = normalized_text(' '.join(self.parts['main']))
        if self.parts['config']:
            try:
                p.config = json.loads(''.join(self.parts['config']))
            except ValueError:
                p.errors.append('invalid page-config JSON')

    def within(self, name):
        return any(name in classes or tag == name or attributes.get('id') == name for tag, classes, attributes in self.stack)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set(a.get('class', '').split())
        p = self.page
        if tag == 'html':
            p.lang, p.direction = a.get('lang', ''), a.get('dir', '')
        if a.get('id'):
            identity = a['id']
            if identity in p.ids:
                p.duplicate_ids.add(identity)
            p.ids.add(identity)
        if tag == 'link' and 'canonical' in a.get('rel', '').split():
            p.canonical.append(a.get('href', ''))
        if tag == 'link' and a.get('hreflang'):
            language = a['hreflang']
            if language in p.alternates:
                p.errors.append('duplicate hreflang ' + language)
            p.alternates[language] = a.get('href', '')
        if tag == 'meta':
            if a.get('name', '').lower() == 'robots' and 'noindex' in a.get('content', '').lower():
                p.noindex = True
            if a.get('http-equiv', '').lower() == 'refresh':
                match = re.search(r'url\s*=\s*(.+)', a.get('content', ''), re.I)
                if match:
                    p.redirect = match.group(1).strip(' \'"')
        for key in ('href', 'src', 'poster', 'action', 'data-copy-markdown'):
            if a.get(key):
                p.references.add(sys.intern(a[key]))
        if a.get('srcset'):
            # Generated asset srcsets use URL + optional width/density descriptors.
            for entry in a['srcset'].split(','):
                if entry.strip():
                    p.references.add(sys.intern(entry.strip().split()[0]))
        if tag == 'img' and 'alt' not in a:
            p.errors.append('image has no alt attribute: ' + a.get('src', ''))
        if a.get('data-article-id'):
            p.article_ids.append(a['data-article-id'])
        if a.get('data-translation-notice') == 'ai':
            p.notices += 1
        if tag == 'a':
            href = a.get('href', '')
            if self.within('issue-contents') and self.within('h2'):
                p.contents.append(href)
            if 'category-card' in classes or 'category-tile' in classes:
                p.category_links.append(href)
            if 'issue-tile' in classes:
                p.issue_links.append(href)
            if 'download' in a:
                p.downloads.add(href)
            if any('data-tcc-directory-footer' in entry[2] or 'data-tcc-copyright-footer' in entry[2] for entry in self.stack):
                p.footer_links.append(href)
        if tag == 'option' and a.get('data-locale'):
            p.languages[a['data-locale']] = a.get('value', '')
            if a.get('value'):
                p.references.add(sys.intern(a['value']))
            if 'selected' in a:
                p.selected.append(a['data-locale'])
        if a.get('data-copy-markdown'):
            p.copy_markdown = a['data-copy-markdown']
        for key in ('data-tcc-global-header', 'data-tcc-directory-footer', 'data-tcc-copyright-footer'):
            if key in a:
                p.chrome.add(key)
        if tag not in VOID:
            self.stack.append((tag, classes, a))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == 'span' and self.stack and 'contents-number' in self.stack[-1][1]:
            self.page.sequences.append(normalized_text(''.join(self.parts['sequence'])))
            self.parts['sequence'] = []
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        for key in ('title', 'h1'):
            if self.within(key):
                self.parts[key].append(data)
        if self.within('main') and not self.within('script') and not self.within('style'):
            self.parts['main'].append(data)
        if self.within('contents-number'):
            self.parts['sequence'].append(data)
        if self.within('page-config'):
            self.parts['config'].append(data)


def private_json_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in PRIVATE_KEYS:
                yield key
            yield from private_json_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from private_json_keys(item)


class SiteChecker:
    def __init__(self, output, *, origin=ORIGIN):
        self.output = Path(output)
        self.origin = origin.rstrip('/')
        self.pages = {}
        self.files = set()
        self.errors = []
        self.references = {}
        self.search = {}

    def error(self, message):
        self.errors.append(message)

    def local_reference(self, reference, source='/'):
        target = urlsplit(urljoin(self.origin + source, reference))
        if target.scheme not in {'http', 'https'} or target.netloc != urlsplit(self.origin).netloc:
            return None
        path = unquote(target.path)
        if '\\' in path or any(part == '..' for part in path.split('/')):
            self.error(f'{source}: unsafe local URL {reference}')
            return None
        return path or '/', unquote(target.fragment)

    def target_file(self, path):
        name = path.lstrip('/')
        if path.endswith('/'):
            name += 'index.html'
        if name in self.files:
            return name
        if name + '/index.html' in self.files:
            return name + '/index.html'
        return None

    def reference(self, reference, source):
        resolved = self.local_reference(reference, source)
        if resolved:
            self.references.setdefault(resolved, source)

    def scan(self):
        if not self.output.is_dir():
            self.error(f'Output directory does not exist: {self.output}')
            return self
        paths = sorted(self.output.rglob('*'))
        for file in paths:
            relative = file.relative_to(self.output).as_posix()
            if file.is_symlink():
                self.error('Public output contains a symlink: ' + relative)
                continue
            if not file.is_file():
                continue
            self.files.add(relative)
            if file.name in PRIVATE_NAMES or file.name.startswith('.env.') or any(part in {'.git', '.github', '__pycache__', '.build', 'runtime', 'campaigns'} for part in file.relative_to(self.output).parts):
                self.error('Private build/source file published: ' + relative)
            if file.suffix in {'.py', '.pyc', '.log', '.yml', '.yaml', '.sqlite', '.sqlite3', '.db', '.pem', '.key'}:
                self.error('Unexpected implementation/runtime file published: ' + relative)
            if file.suffix == '.gz':
                self.check_compressed_index(file, relative)
                continue
            if file.suffix not in {'.html', '.json', '.md', '.xml', '.css', '.js', '.txt'}:
                continue
            try:
                source = file.read_text(encoding='utf-8')
            except UnicodeError:
                self.error('Non-UTF-8 public text: ' + relative)
                continue
            if SECRET.search(source):
                self.error('Credential-like value in public output: ' + relative)
            if file.suffix == '.html':
                route = public_route(relative)
                page = PageParser(route, source).page
                self.pages[route] = page
                for item in page.references:
                    self.reference(item, route)
                for problem in page.errors:
                    self.error(f'{route}: {problem}')
                if page.config is not None:
                    for key in private_json_keys(page.config):
                        self.error(f'{route}: private JSON field {key}')
            elif file.suffix == '.json':
                try:
                    value = json.loads(source)
                    for key in private_json_keys(value):
                        self.error(f'{relative}: private JSON field {key}')
                    if relative.endswith('/search-index.json'):
                        self.search[relative.split('/')[0]] = value
                        if not file.with_suffix('.json.gz').is_file():
                            self.error('Missing compressed search index: ' + relative + '.gz')
                    elif relative == 'deployment.json':
                        revisions = value.get('revisions', {}) if isinstance(value, dict) else {}
                        if not isinstance(revisions, dict) or set(revisions) != {'site', 'english', 'translations', 'theme'} or any(
                            not (key == 'translations' and revision is None) and not (isinstance(revision, str) and re.fullmatch(r'[a-f0-9]{40}', revision))
                            for key, revision in revisions.items()):
                            self.error('deployment.json contains invalid publication revision identities')
                        allowed = {'schema', 'display_fingerprint', 'revisions', 'translation_status'}
                        if not isinstance(value, dict) or set(value) - allowed:
                            self.error('deployment.json contains more than the public publication identity')
                    elif relative != 'routes.json':
                        self.error('Unexpected public JSON file: ' + relative)
                except (ValueError, TypeError):
                    self.error('Invalid public JSON: ' + relative)
            elif file.suffix == '.css':
                for value in re.findall(r'url\(\s*[\'\"]?([^\)\'\"]+)', source):
                    self.reference(value.strip(), '/' + relative)
            elif file.suffix == '.md':
                # The Markdown contract deliberately keeps exact semantic HTML
                # and AI notices; their local URLs must resolve as well.
                for reference in PageParser('/' + relative, source).page.references:
                    self.reference(reference, '/' + relative)
                for value in re.findall(r'\]\(<([^>]+)>|<(https?://[^>]+)>', source):
                    self.reference(value[0] or value[1], '/' + relative)
        return self

    def check_compressed_index(self, file, relative):
        """Require the optimized payload to be the same already-audited JSON.

        Bound decompression by the uncompressed neighbor's actual byte length,
        rather than trusting a gzip size field or allocating an arbitrary bomb.
        The plain JSON is separately checked for UTF-8, structure, private keys,
        secrets, and exact exported-article parity by the ordinary scan.
        """
        if len(Path(relative).parts) != 2 or file.name != 'search-index.json.gz':
            self.error('Unexpected compressed public file: ' + relative)
            return
        neighbor = file.with_suffix('')
        if neighbor.is_symlink() or not neighbor.is_file():
            self.error('Compressed search index has no safe JSON neighbor: ' + relative)
            return
        expected = neighbor.read_bytes()
        try:
            with file.open('rb') as stream:
                header = stream.read(10)
            if len(header) < 10 or header[:3] != b'\x1f\x8b\x08':
                raise OSError('not a gzip stream')
            if header[3] != 0 or header[4:8] != b'\0' * 4:
                self.error('Search gzip header is not deterministic (mtime/flags): ' + relative)
            with gzip.open(file, 'rb') as stream:
                actual = stream.read(len(expected) + 1)
            if actual != expected:
                self.error('Compressed search index differs from neighboring JSON: ' + relative)
        except (OSError, EOFError, ValueError, zlib.error) as error:
            self.error('Invalid compressed search index: ' + relative + ': ' + str(error))

    def check_links(self):
        for (path, fragment), source in self.references.items():
            target = self.target_file(path)
            if not target:
                self.error(f'{source}: broken local link {path}' + ('#' + fragment if fragment else ''))
                continue
            if fragment and target.endswith('.html'):
                page = self.pages.get(public_route(target))
                # Text fragments are a browser feature, not element IDs.
                identity = fragment.split(':~:text=')[0]
                if identity and page and identity not in page.ids:
                    self.error(f'{source}: missing anchor {path}#{fragment}')

    def check_pages(self, locales=None):
        chrome = {'data-tcc-global-header', 'data-tcc-directory-footer', 'data-tcc-copyright-footer'}
        for route, p in self.pages.items():
            if len(p.canonical) != 1:
                self.error(f'{route}: expected one canonical, found {len(p.canonical)}')
                continue
            canonical = self.local_reference(p.canonical[0], route)
            canonical_parts = urlsplit(p.canonical[0])
            if not p.canonical[0].startswith(self.origin + '/') or canonical_parts.query or canonical_parts.fragment or not canonical or not self.target_file(canonical[0]):
                self.error(f'{route}: canonical does not resolve on the production origin')
            if not p.redirect and canonical != (route, ''):
                self.error(f'{route}: canonical is not self-referential')
            if not p.title:
                self.error(f'{route}: empty document title')
            if p.duplicate_ids:
                self.error(f'{route}: duplicate element IDs: {sorted(p.duplicate_ids)}')
            if p.noindex and p.alternates:
                self.error(f'{route}: noindex page advertises hreflang equivalents')
            if p.redirect:
                if not p.noindex:
                    self.error(f'{route}: redirect is indexable')
                if self.local_reference(p.redirect, route) != canonical:
                    self.error(f'{route}: redirect and canonical differ')
                continue
            expected_tag = route.split('/')[1] if route not in {'/', '/404.html'} else 'en'
            if p.lang != expected_tag:
                self.error(f'{route}: lang={p.lang!r}, expected {expected_tag!r}')
            if p.direction not in {'ltr', 'rtl'}:
                self.error(f'{route}: missing/invalid direction')
            if p.chrome != chrome:
                self.error(f'{route}: mandatory header/footer bands missing')
            if p.config is None or p.config.get('locale') != p.lang:
                self.error(f'{route}: page configuration locale mismatch')
            if p.selected != [p.lang]:
                self.error(f'{route}: current dropdown locale mismatch')
            if locales:
                if p.lang not in locales:
                    self.error(f'{route}: unconfigured locale')
                elif p.direction != locales[p.lang]['meta']['dir']:
                    self.error(f'{route}: direction disagrees with locale')
                if set(p.languages) != set(locales):
                    self.error(f'{route}: incomplete language dropdown')
            for tag, url in p.alternates.items():
                resolved = self.local_reference(url, route)
                target = self.pages.get(resolved[0]) if resolved else None
                if target is None or target.noindex or target.redirect:
                    self.error(f'{route}: hreflang {tag} is not an indexed real page')
                    continue
                if target.lang != tag:
                    self.error(f'{route}: hreflang {tag} target has lang={target.lang}')
                if target.alternates.get(p.lang) != p.canonical[0]:
                    self.error(f'{route}: nonreciprocal hreflang {tag}')
                if p.alternates != target.alternates:
                    self.error(f'{route}: inconsistent equivalent-page hreflang cluster')
            if not p.noindex and p.alternates.get(p.lang) != p.canonical[0]:
                self.error(f'{route}: missing self hreflang')

    def check_sitemap(self):
        file = self.output / 'sitemap.xml'
        if not file.is_file():
            self.error('Missing sitemap.xml')
            return
        try:
            tree = ET.parse(file)
        except ET.ParseError as error:
            self.error('Invalid sitemap: ' + str(error))
            return
        ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9', 'x': 'http://www.w3.org/1999/xhtml'}
        seen = set()
        for item in tree.findall('s:url', ns):
            url = item.findtext('s:loc', namespaces=ns) or ''
            target = self.local_reference(url)
            route = target[0] if target else None
            if route in seen:
                self.error('Duplicate sitemap URL: ' + str(route))
            seen.add(route)
            page = self.pages.get(route)
            if not page or page.noindex or page.redirect:
                self.error('Sitemap contains a missing/nonindexed page: ' + url)
                continue
            alternates = {link.get('hreflang'): link.get('href') for link in item.findall('x:link', ns)}
            if alternates != page.alternates:
                self.error(f'{route}: sitemap and HTML hreflang differ')
        expected = {route for route, page in self.pages.items() if not page.noindex and not page.redirect}
        if seen != expected:
            self.error(f'Sitemap inventory mismatch: {len(expected - seen)} missing, {len(seen - expected)} extra')

    def check_brand(self, theme):
        theme = Path(theme)
        for relative in ('assets/brand/logo.jpg', 'assets/favicons/favicon.ico', 'assets/footer/city-skyline-skyscrapers-top.jpg'):
            source, target = theme / relative, self.output / relative
            if not source.is_file() or not target.is_file():
                self.error('Cannot verify original theme asset: ' + relative)
            elif hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
                self.error('Theme asset pixels/bytes were changed: ' + relative)
        source = theme / 'src/html/site-footer.html'
        if not source.is_file():
            self.error('Cannot verify theme footer template')
            return
        original = PageParser('/theme-footer', source.read_text()).page.footer_links
        for route, page in self.pages.items():
            if not page.redirect and page.footer_links != original:
                self.error(f'{route}: canonical footer destinations/order changed')

    def require_page(self, route, label):
        page = self.pages.get(route)
        if page is None:
            self.error(f'Missing {label} page: {route}')
        return page

    def check_content(self, model, locales, routes):
        """Compare output against the validated exports, never hard-coded counts."""
        from content import ordered_issues
        issues = ordered_issues(model)
        issue_map = {item['id']: item for item in issues}
        rank = {item['id']: n for n, item in enumerate(issues)}
        actual_articles = Counter((page.lang, aid) for page in self.pages.values() for aid in page.article_ids)
        expected_articles = Counter((tag, article['id']) for tag, articles in model['articles'].items() for article in articles)
        if actual_articles != expected_articles:
            self.error(f'Published article inventory mismatch: {sum((expected_articles-actual_articles).values())} missing, {sum((actual_articles-expected_articles).values())} extra/duplicated')
        english = {article['id']: article for article in model['articles']['en']}
        for tag, locale in locales.items():
            articles = sorted(model['articles'].get(tag, []), key=lambda a: (rank[a['issue_id']], a.get('sequence', 0)))
            article_map = {a['id']: a for a in articles}
            home = self.require_page(f'/{tag}/', 'locale home')
            category_index = self.require_page(f'/{tag}/categories/', 'category index')
            issue_index = self.require_page(f'/{tag}/issues/', 'issue index')
            self.require_page(f'/{tag}/search/', 'search')
            self.require_page(f'/{tag}/404/', 'localized 404')
            if home and (normalized_text(locale['ui']['article_count'].format(count=len(articles))) not in home.main_text or normalized_text(locale['ui']['issue_count'].format(count=len(issues))) not in home.main_text):
                self.error(f'/{tag}/: homepage archive counts disagree with exports')
            if home and not articles and normalized_text(locale['ui']['coming_soon']) not in home.main_text:
                self.error(f'/{tag}/: empty locale lacks localized coming-soon notice')
            if category_index and set(category_index.category_links) != set(routes['categories'][tag].values()):
                self.error(f'/{tag}/categories/: category inventory is incomplete')
            if issue_index and issue_index.issue_links != [routes['issues'][tag][item['id']] for item in issues]:
                self.error(f'/{tag}/issues/: issue inventory/order differs from catalogue')
            for category in model['categories']:
                path = routes['categories'][tag][category['id']]
                page = self.require_page(path, 'category')
                selected = [a for a in articles if category['id'] in [a['categories']['primary'], *a['categories'].get('additional', [])]]
                if page and normalized_text(locale['categories'][category['id']]['description']) not in page.main_text:
                    self.error(f'{path}: localized category description missing')
                if page and normalized_text(locale['ui']['article_count'].format(count=len(selected))) not in page.main_text:
                    self.error(f'{path}: category article count disagrees with exports')
                if page and not selected and normalized_text(locale['ui']['coming_soon']) not in page.main_text:
                    self.error(f'{path}: empty category lacks localized notice')
            for issue in issues:
                path = routes['issues'][tag][issue['id']]
                page = self.require_page(path, 'issue')
                expected = [a for a in articles if a['issue_id'] == issue['id']]
                if page and normalized_text(locale['ui']['article_count'].format(count=len(expected))) not in page.main_text:
                    self.error(f'{path}: issue article count disagrees with exports')
                if page and (page.contents != [a['url'] for a in expected] or page.sequences != [str(a['sequence']) for a in expected]):
                    self.error(f'{path}: issue article inventory/source sequence mismatch')
            records = self.search.get(tag)
            if not isinstance(records, list):
                self.error(f'{tag}: missing/invalid search index')
            else:
                if [r.get('id') for r in records] != [a['id'] for a in articles]:
                    self.error(f'{tag}: search article inventory/order mismatch')
                for record in records:
                    source = article_map.get(record.get('id'))
                    if source and (record.get('url') != source['url'] or record.get('title') != (source.get('title') or locale['ui']['untitled_article']) or record.get('body') != source['text']):
                        self.error(f'{tag}: search text/title/route differs from exported article {record.get("id")}')
                    self.reference(record.get('url', ''), f'/{tag}/search-index.json')
            for article in articles:
                page = self.require_page(article['url'], 'article')
                if not page:
                    continue
                article_file = self.output / article['url'].lstrip('/') / 'index.html'
                if article['html'] not in article_file.read_text(encoding='utf-8'):
                    self.error(f'{article["url"]}: original exported HTML/notice was changed')
                if page.h1 != normalized_text(article.get('title') or locale['ui']['untitled_article']):
                    self.error(f'{article["url"]}: article title differs from published locale text')
                if page.notices != int(bool(article.get('ai_notice_required'))):
                    self.error(f'{article["url"]}: AI notice does not match approved export')
                issue_url = routes['issues'][tag][article['issue_id']]
                if issue_url not in page.references:
                    self.error(f'{article["url"]}: missing original issue backlink')
                markdown_url = article['markdown_url']
                if markdown_url not in page.downloads or page.copy_markdown != markdown_url or not {'markdown-fallback', 'markdown-text'} <= page.ids:
                    self.error(f'{article["url"]}: missing visible Markdown download/copy/fallback controls')
                markdown_path = self.output / markdown_url.lstrip('/')
                if not markdown_path.is_file():
                    self.error('Missing published article Markdown: ' + markdown_url)
                else:
                    markdown = markdown_path.read_text(encoding='utf-8')
                    if self.origin + article['url'] not in markdown or self.origin + issue_url not in markdown:
                        self.error(f'{markdown_url}: canonical or issue backlink missing')
                    if PageParser(markdown_url, markdown).page.notices != int(bool(article.get('ai_notice_required'))):
                        self.error(f'{markdown_url}: AI notice parity mismatch')
                expected_equivalents = {language: self.origin + available[article['id']]['url'] for language in locales if article['id'] in (available := {a['id']: a for a in model['articles'].get(language, [])})}
                if page.alternates != expected_equivalents:
                    self.error(f'{article["url"]}: article hreflang includes an unavailable translation')
                compatibility = self.require_page(article['compatibility_url'], 'UUID compatibility')
                if compatibility and (not compatibility.redirect or self.local_reference(compatibility.redirect, compatibility.route) != (article['url'], '')):
                    self.error(f'{article["compatibility_url"]}: UUID route does not redirect to canonical article')
            for aid, source in english.items():
                if aid in article_map:
                    continue
                path = f'/{tag}/articles/{aid}/'
                page = self.require_page(path, 'missing translation')
                if page and (not page.noindex or page.alternates or page.article_ids or normalized_text(locale['ui']['missing_translation']) not in page.main_text or source['url'] not in page.references):
                    self.error(f'{path}: missing translation must explain absence, stay noindex, and link authoritative English')
                if page and page.h1 != normalized_text(locale['ui']['no_articles_title']):
                    self.error(f'{path}: untranslated English title presented as the locale article heading')
            self.check_rss(tag, articles, issue_map, routes['issues'][tag], locale['ui']['untitled_article'])

    def check_rss(self, tag, articles, issues, issue_routes, untitled):
        file = self.output / tag / 'feed.xml'
        if not file.is_file():
            self.error(f'{tag}: missing RSS feed')
            return
        try:
            root = ET.parse(file).getroot()
        except ET.ParseError as error:
            self.error(f'{tag}: invalid RSS XML: {error}')
            return
        channel = root.find('channel')
        if root.tag != 'rss' or root.get('version') != '2.0' or channel is None:
            self.error(f'{tag}: invalid RSS 2.0 channel')
            return
        if channel.findtext('language') != tag:
            self.error(f'{tag}: RSS locale mismatch')
        items = channel.findall('item')
        if len(items) != min(50, len(articles)):
            self.error(f'{tag}: RSS recent-article inventory count mismatch')
        for item, article in zip(items, articles[:50]):
            if item.findtext('title') != (article.get('title') or untitled):
                self.error(f'{tag}: RSS title differs from published locale text')
            citation = item.find('source')
            if citation is None or citation.get('url') != self.origin + issue_routes[article['issue_id']]:
                self.error(f'{tag}: RSS original issue backlink is missing or incorrect')
            else:
                self.reference(citation.get('url'), f'/{tag}/feed.xml')
            if item.findtext('link') != self.origin + article['url'] or item.findtext('guid') != f'urn:remnant:{tag}:{article["id"]}':
                self.error(f'{tag}: RSS contains wrong/stale article identity/order')
            self.reference(item.findtext('link') or '', f'/{tag}/feed.xml')
            if item.findtext('pubDate'):
                date = issues[article['issue_id']].get('date', {})
                if date.get('precision') != 'day' or not all(date.get(key) for key in ('year', 'month', 'day')):
                    self.error(f'{tag}: RSS manufactures a publication day for imprecise issue date')
                else:
                    try:
                        actual = parsedate_to_datetime(item.findtext('pubDate'))
                        if (actual.year, actual.month, actual.day) != (date['year'], date['month'], date['day']):
                            raise ValueError('different day')
                    except (ValueError, TypeError):
                        self.error(f'{tag}: RSS publication date differs from actual issue day')

    def run(self, *, model=None, locales=None, routes=None, theme=None):
        self.scan()
        self.check_pages(locales)
        self.check_sitemap()
        if model is not None:
            self.check_content(model, locales, routes)
        if theme is not None:
            self.check_brand(theme)
        self.check_links()
        return self.errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, nargs='?', default=ROOT / 'dist')
    parser.add_argument('--english', type=Path, default=ROOT / '.build/english')
    parser.add_argument('--translations', type=Path, default=ROOT / '.build/translations')
    parser.add_argument('--locales', type=Path, default=ROOT / 'locales')
    parser.add_argument('--registry', type=Path, default=ROOT / 'data/routes.json')
    parser.add_argument('--theme', type=Path, default=ROOT / '.build/theme')
    parser.add_argument('--english-only', action='store_true')
    parser.add_argument('--structural-only', action='store_true')
    args = parser.parse_args()
    context = {}
    if not args.structural_only:
        from content import load_content
        from i18n import load_locales, validate_locales
        from routes import initialize_routes
        try:
            model = load_content(args.english, None if args.english_only else args.translations)
            locales = load_locales(args.locales)
            validate_locales(locales, categories=model['categories'])
            routes = initialize_routes(model, locales, args.registry)
            context = dict(model=model, locales=locales, routes=routes, theme=args.theme)
        except (ValueError, OSError, KeyError) as error:
            parser.error('Cannot validate source contract: ' + str(error))
    checker = SiteChecker(args.output)
    errors = checker.run(**context)
    for error in errors[:100]:
        print('FAIL: ' + error, file=sys.stderr)
    if len(errors) > 100:
        print(f'... {len(errors)-100} further errors omitted', file=sys.stderr)
    print(json.dumps({'ok': not errors, 'files': len(checker.files), 'html_pages': len(checker.pages),
                      'local_targets': len(checker.references), 'errors': len(errors)}, indent=2))
    raise SystemExit(bool(errors))


if __name__ == '__main__':
    main()
