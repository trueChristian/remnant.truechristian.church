"""Small generated-site regression fixtures, independent of the full archive.

The optional complete integration check is scripts/check_site.py dist. These
fixtures exercise real generator HTML/Markdown/RSS and mutation-test the checker
without downloading source repositories or building 15,000 pages per unit test.
"""
import copy
import gzip
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build import Site, ORIGIN
from check_site import SiteChecker, PageParser, private_json_keys
from i18n import load_locales
from routes import initialize_routes, set_article_alias

I = '00000000-0000-4000-8000-000000000001'
J = '00000000-0000-4000-8000-000000000002'


def uuid_for(index):
    return f'00000000-0000-4000-9000-{index:012d}'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')


def fixture(root, *, translated=True, count=3, missing_title=False,
            duplicate_titles=False, translated_count=1, translated_title='Afrikaanse opskrif'):
    locales = {tag: value for tag, value in load_locales(ROOT / 'locales').items() if tag in {'en', 'af', 'fr'}}
    category_ids = list(locales['en']['categories'])[:2]
    categories = [{'id': cid, 'slug': locales['en']['categories'][cid]['slug'], 'name': locales['en']['categories'][cid]['name']} for cid in category_ids]
    for locale in locales.values():
        locale['categories'] = {cid: locale['categories'][cid] for cid in category_ids}
    issues = [{'id': I, 'slug': 'summer-2024', 'publication': 'The Heartbeat of the Remnant', 'date': {'year': 2024, 'season': 'Summer', 'precision': 'season'}},
              {'id': J, 'slug': 'year-2023', 'publication': 'The Heartbeat of the Remnant', 'date': {'year': 2023, 'precision': 'year'}}]
    articles = []
    for n in range(count):
        aid = uuid_for(n + 1)
        article = {'id': aid, 'issue_id': I, 'issue': copy.deepcopy(issues[0]), 'sequence': count-n,
                   'title': None if missing_title and n == 0 else ('English source' if duplicate_titles else f'English source {n+1}'), 'subtitle': None,
                   'section': '', 'byline': {'raw': 'Original Author'}, 'source_pages': {'start': 3, 'end': 5},
                   'categories': {'primary': category_ids[0], 'additional': []}, 'topics': [], 'images': [],
                   'locale': 'en', 'language': 'en', 'direction': 'ltr', 'ai_notice_required': False,
                   'human_reviewed': True, 'text': f'Faithful text {n+1} with meaning.',
                   'excerpt': f'Faithful text {n+1} with meaning.',
                   'html': f'<article data-article-id="{aid}"><p>Faithful text {n+1} with <em>meaning</em>.</p></article>'}
        articles.append(article)
    model = {'issues': issues, 'categories': categories, 'topics': [], 'series': [], 'articles': {'en': articles}}
    if translated:
        model['articles']['af'] = []
        for source in articles[:translated_count]:
            af = copy.deepcopy(source)
            af.update(title=None if missing_title else translated_title, locale='af', language='af', human_reviewed=False, ai_notice_required=True,
                      text='Getroue woorde met betekenis.', excerpt='Getroue woorde met betekenis.')
            af['html'] = f'<article data-article-id="{af["id"]}"><p>Getroue woorde met <em>betekenis</em>.</p></article><aside data-translation-notice="ai"><p>KI-vertaling. <a href="/en/articles/{af["id"]}/">English</a></p></aside>'
            model['articles']['af'].append(af)
    routes = initialize_routes(model, locales, root / 'routes-source.json', update=True)
    theme, output = root / 'theme', root / 'dist'
    footer = '<div data-tcc-directory-footer><a href="https://truechristian.church/history">History</a></div><footer data-tcc-copyright-footer><a href="https://truechristian.church/copyright">Copyright</a></footer>'
    write(theme / 'src/html/site-footer.html', footer)
    for relative in ('assets/brand/logo.jpg', 'assets/favicons/favicon.ico', 'assets/footer/city-skyline-skyscrapers-top.jpg'):
        for location in (theme, output):
            file = location / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'unchanged fixture asset')
    for name in ('preferences.js', 'theme.css', 'site.css', 'theme.js', 'site.js', 'article-figures.css', 'article-figures.js'):
        write(output / 'assets' / name, '')
    site = Site(model, locales, routes, theme, output, {})
    site.build()
    return model, locales, routes, theme, output


class GeneratedSiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model, self.locales, self.routes, self.theme, self.output = fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def check(self):
        checker = SiteChecker(self.output)
        checker.run(model=self.model, locales=self.locales, routes=self.routes, theme=self.theme)
        return checker

    def page_path(self, route):
        path = self.output / route.lstrip('/')
        return path / 'index.html' if route.endswith('/') else path

    def mutate(self, route, old, new):
        path = self.page_path(route)
        self.assertIn(old, path.read_text())
        path.write_text(path.read_text().replace(old, new, 1))

    def test_complete_small_archive_passes_independent_output_check(self):
        checker = self.check()
        self.assertEqual(checker.errors, [])
        self.assertEqual(CounterArticleIds(checker), {'en': 3, 'af': 1})

    def test_french_empty_interface_categories_and_issue_inventory_are_real(self):
        checker = self.check()
        fr = checker.pages['/fr/']
        self.assertEqual((fr.lang, fr.direction, fr.selected), ('fr', 'ltr', ['fr']))
        self.assertIn(self.locales['fr']['ui']['coming_soon'], fr.main_text)
        self.assertIn('/en/', fr.references)
        self.assertEqual(checker.search['fr'], [])
        self.assertEqual(len(checker.pages['/fr/categories/'].category_links), 2)
        self.assertEqual(len(checker.pages['/fr/issues/'].issue_links), 2)

    def test_missing_language_is_noindex_and_links_available_languages(self):
        checker = self.check()
        aid = uuid_for(1)
        page = checker.pages[self.routes['articles']['fr'][aid]]
        self.assertTrue(page.noindex)
        self.assertFalse(page.alternates)
        self.assertFalse(page.article_ids)
        self.assertIn(self.locales['fr']['ui']['missing_translation'], page.main_text)
        self.assertIn(self.model['articles']['en'][0]['url'], page.references)
        self.assertIn(self.model['articles']['af'][0]['url'], page.references)
        self.assertEqual(page.languages['af'], self.model['articles']['af'][0]['url'])
        self.assertEqual(page.h1, self.locales['fr']['ui']['no_articles_title'])

    def test_true_translation_titles_and_hreflang_are_not_english_fallbacks(self):
        checker = self.check()
        source, translated = self.model['articles']['en'][0], self.model['articles']['af'][0]
        page = checker.pages[translated['url']]
        self.assertEqual(page.h1, 'Afrikaanse opskrif')
        self.assertNotEqual(page.h1, source['title'])
        self.assertEqual(set(page.alternates), {'en', 'af'})
        self.assertEqual(page.notices, 1)
        self.assertIn('data-translation-notice="ai"', (self.output / translated['markdown_url'].lstrip('/')).read_text())

    def test_source_sequence_and_issue_count_do_not_depend_on_input_order(self):
        checker = self.check()
        issue = checker.pages[self.routes['issues']['en'][I]]
        self.assertEqual(issue.sequences, ['1', '2', '3'])
        self.assertEqual(issue.contents, [article['url'] for article in reversed(self.model['articles']['en'])])
        self.assertEqual(checker.pages[self.routes['issues']['en'][J]].contents, [])

    def test_winter_2024_leads_latest_archive_search_and_feed(self):
        # Permanent identities from the current publisher catalogue, intentionally
        # added after the older Summer/2023 fixture records to catch array ordering.
        winter = {'id': '81196f7a-e1f3-5653-ba8e-1ca6a2824470',
                  'slug': 'heartbeat-remnant-2024-winter',
                  'publication': 'The Heartbeat of the Remnant',
                  'date': {'year': 2024, 'season': 'Winter', 'precision': 'season'}}
        autumn = {'id': '6e434782-fad8-50a6-84db-a97babd8c346',
                  'slug': 'heartbeat-remnant-2024-autumn',
                  'publication': 'The Heartbeat of the Remnant',
                  'date': {'year': 2024, 'season': 'Autumn', 'precision': 'season'}}
        reviewed = {r['issueId']: r for r in json.loads((ROOT / 'data/issue-pdfs.json').read_text())['issues']}
        for issue in (winter, autumn):
            issue['source'] = {'sha256': reviewed[issue['id']]['sourceSha256']}
        self.model['issues'].extend([winter, autumn])
        for article, issue in zip(self.model['articles']['en'][1:], [autumn, winter]):
            article.update(issue_id=issue['id'], issue=copy.deepcopy(issue))
        self.routes = initialize_routes(self.model, self.locales,
                                        self.root / 'seasonal-routes.json', update=True)
        Site(self.model, self.locales, self.routes, self.theme, self.output, {}).build()
        expected = [winter['id'], autumn['id'], I, J]
        for tag in self.locales:
            home = self.page_path(f'/{tag}/').read_text()
            if tag == 'en':
                latest = home.split('data-home-latest', 1)[1].split('</section>', 1)[0]
                self.assertLess(latest.index('Winter 2024'), latest.index('Autumn 2024'))
            self.assertNotIn('latest-issue', home)
            archive = PageParser(f'/{tag}/issues/', self.page_path(f'/{tag}/issues/').read_text()).page
            self.assertEqual(archive.issue_links,
                             [self.routes['issues'][tag][issue_id] for issue_id in expected])
        index = json.loads((self.output / 'en/search-index.json').read_text())
        self.assertEqual([article['issue_id'] for article in index], expected[:3])
        feed = ET.parse(self.output / 'en/feed.xml')
        self.assertEqual([item.findtext('source') for item in feed.findall('channel/item')], [
            'The Heartbeat of the Remnant · Winter 2024',
            'The Heartbeat of the Remnant · Autumn 2024',
            'The Heartbeat of the Remnant · Summer 2024',
        ])
        self.assertEqual(feed.findall('.//pubDate'), [])

    def test_legacy_uuid_redirects_to_readable_article_and_markdown_uses_same_alias(self):
        checker = self.check()
        article = self.model['articles']['en'][0]
        page = checker.pages[article['compatibility_url']]
        self.assertEqual(page.redirect, article['url'])
        self.assertTrue(page.noindex)
        self.assertEqual(article['markdown_url'], article['url'].rstrip('/') + '.md')
        self.assertNotIn(article['id'], article['markdown_url'])
        markdown = (self.output / article['markdown_url'].lstrip('/')).read_text()
        self.assertIn(ORIGIN + self.routes['issues']['en'][I], markdown)
        self.assertIn('Original Author', markdown)

    def test_article_language_prefix_change_redirects_to_translated_category_and_alias(self):
        checker = self.check()
        identity = uuid_for(1)
        source = self.routes['articles']['en'][identity]
        destination = self.routes['articles']['af'][identity]
        changed = '/af/' + source.split('/', 2)[2]
        self.assertNotEqual(source.split('/', 2)[2], destination.split('/', 2)[2])
        redirect = checker.pages[changed]
        self.assertEqual(redirect.redirect, destination)
        self.assertEqual(redirect.canonical, [ORIGIN + destination])
        self.assertTrue(redirect.noindex)
        self.assertEqual(redirect.article_ids, [])
        canonical = checker.pages[destination]
        self.assertEqual(canonical.article_ids, [identity])
        self.assertFalse(canonical.redirect)
        self.assertFalse(canonical.noindex)
        self.assertEqual(canonical.languages, {tag: self.routes['articles'][tag][identity] for tag in self.locales})

    def test_category_prefix_changes_resolve_directly_to_same_localized_category(self):
        checker = self.check()
        for category in self.model['categories']:
            identity = category['id']
            for source_locale in self.locales:
                source = self.routes['categories'][source_locale][identity]
                for target_locale in self.locales:
                    requested = f'/{target_locale}/' + source.split('/', 2)[2]
                    destination = self.routes['categories'][target_locale][identity]
                    page = checker.pages[requested]
                    self.assertEqual(page.canonical, [ORIGIN + destination])
                    if requested != destination:
                        self.assertEqual(page.redirect, destination)
                        self.assertTrue(page.noindex)
                    else:
                        self.assertFalse(page.redirect)
                    self.assertFalse(checker.pages[destination].redirect)

    def test_every_language_and_history_redirect_is_direct_and_has_no_article_body(self):
        checker = self.check()
        self.assertTrue(self.routes['redirects'])
        for source, destination in self.routes['redirects'].items():
            page = checker.pages[source]
            self.assertEqual(page.redirect, destination)
            self.assertEqual(page.canonical, [ORIGIN + destination])
            self.assertTrue(page.noindex)
            self.assertFalse(page.alternates)
            self.assertFalse(page.article_ids)
            self.assertFalse(checker.pages[destination].redirect)
        self.assertEqual(CounterArticleIds(checker), {'en': 3, 'af': 1})

    def test_legacy_recovery_index_contains_only_known_aliases_and_direct_readable_targets(self):
        checker = self.check()
        expected = {'aliases': self.routes['legacy_aliases'],
                    'targets': {kind: self.routes[kind] for kind in ('articles', 'categories', 'issues')}}
        self.assertEqual(checker.legacy_routes, expected)
        self.assertEqual(checker.pages['/404.html'].config['legacyRouteIndex'], '/legacy-route-index.json')
        for kind, locales in checker.legacy_routes['targets'].items():
            for tag, identities in locales.items():
                for identity, path in identities.items():
                    self.assertNotIn(identity, path)
                    self.assertEqual(path.split('/')[1], tag)
                    self.assertFalse(checker.pages[path].redirect)
        missing = self.routes['articles']['fr'][uuid_for(1)]
        self.assertTrue(checker.pages[missing].noindex)
        self.assertEqual(checker.legacy_routes['targets']['articles']['fr'][uuid_for(1)], missing)

    def test_detects_unknown_or_uuid_bearing_legacy_index_canonical_targets(self):
        file = self.output / 'legacy-route-index.json'
        original = json.loads(file.read_text())
        for target, expected in [('/af/not-in-the-archive/unknown/', 'target is missing or redirects'),
                                 (f'/af/articles/{uuid_for(1)}/', 'UUID-bearing legacy route canonical target')]:
            with self.subTest(target=target):
                value = copy.deepcopy(original)
                value['targets']['articles']['af'][uuid_for(1)] = target
                write(file, json.dumps(value))
                self.assertTrue(any(expected in error for error in self.check().errors))

    def test_detects_legacy_index_owner_changed_to_another_valid_article(self):
        file = self.output / 'legacy-route-index.json'
        value = json.loads(file.read_text())
        value['aliases'][f'/articles/{uuid_for(1)}/']['id'] = uuid_for(2)
        write(file, json.dumps(value))
        self.assertTrue(any('differs from the registered aliases or canonical identities' in error
                            for error in self.check().errors))

    def test_detects_extra_schema_fields_or_nonlegacy_aliases_in_recovery_index(self):
        file = self.output / 'legacy-route-index.json'
        original = json.loads(file.read_text())
        value = copy.deepcopy(original)
        value['unexpected'] = 'extra public state'
        write(file, json.dumps(value))
        self.assertTrue(any('Invalid legacy route index schema' in error for error in self.check().errors))
        value = copy.deepcopy(original)
        value['aliases']['/guessed-title/'] = {'kind': 'articles', 'id': uuid_for(1)}
        write(file, json.dumps(value))
        self.assertTrue(any('Invalid legacy route alias/identity' in error for error in self.check().errors))

    def test_detects_missing_or_broken_root_404_recovery_index(self):
        self.mutate('/404.html', '/legacy-route-index.json', '/unknown-route-index.json')
        self.assertTrue(any('legacy route recovery index is missing' in error for error in self.check().errors))
        (self.output / 'legacy-route-index.json').unlink()
        self.assertTrue(any('Missing or invalid legacy-route-index.json' in error for error in self.check().errors))

    def test_swapped_prefix_without_translation_lands_on_readable_noindex_notice(self):
        checker = self.check()
        aid = uuid_for(1)
        source = self.routes['articles']['af'][aid]
        requested = '/fr/' + source.split('/', 2)[2]
        destination = self.routes['articles']['fr'][aid]
        self.assertEqual(checker.pages[requested].redirect, destination)
        notice = checker.pages[destination]
        self.assertTrue(notice.noindex)
        self.assertFalse(notice.article_ids)
        self.assertFalse(notice.alternates)
        self.assertFalse(notice.redirect)
        self.assertNotIn(aid, destination)
        self.assertIn(self.routes['articles']['en'][aid], notice.references)

    def test_canonical_navigation_markdown_and_notice_links_do_not_expose_uuids(self):
        checker = self.check()
        uuid_pattern = re.compile(r'[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}', re.I)
        for page in checker.pages.values():
            if page.redirect:
                continue
            self.assertIsNone(uuid_pattern.search(page.route), page.route)
            for reference in page.links:
                local = checker.local_reference(reference, page.route)
                if local:
                    self.assertIsNone(uuid_pattern.search(local[0]), reference)
        translated = self.model['articles']['af'][0]
        self.assertIn(f'/en/articles/{translated["id"]}/', translated['html'])
        for path in (self.page_path(translated['url']), self.output / translated['markdown_url'].lstrip('/')):
            self.assertNotIn(f'/en/articles/{translated["id"]}/', path.read_text())
            self.assertIn(self.routes['articles']['en'][translated['id']], path.read_text())

    def test_alias_migration_preserves_history_under_every_language_prefix(self):
        article = self.model['articles']['af'][0]
        previous = article['url']
        registry = self.routes['registry']
        set_article_alias(registry, 'af', article['id'], 'hersiene-opskrif')
        write(self.root / 'routes-source.json', json.dumps(registry))
        self.routes = initialize_routes(self.model, self.locales, self.root / 'routes-source.json', update=True)
        Site(self.model, self.locales, self.routes, self.theme, self.output, {}).build()
        checker = self.check()
        self.assertEqual(checker.errors, [])
        for tag in self.locales:
            old = f'/{tag}/' + previous.split('/', 2)[2]
            self.assertEqual(checker.pages[old].redirect, self.routes['articles'][tag][article['id']])
        self.assertEqual(CounterArticleIds(checker), {'en': 3, 'af': 1})

    def test_detects_removed_prefix_redirect_and_redirect_to_another_article(self):
        aid = uuid_for(1)
        source = '/af/' + self.routes['articles']['en'][aid].split('/', 2)[2]
        destination = self.routes['articles']['af'][aid]
        self.mutate(source, f'content="0;url={destination}"',
                    f'content="0;url={self.routes["articles"]["af"][uuid_for(2)]}"')
        errors = self.check().errors
        self.assertTrue(any('registered redirect does not directly identify canonical destination' in e for e in errors))
        self.page_path(source).unlink()
        self.assertTrue(any('Missing registered redirect page' in e for e in self.check().errors))

    def test_detects_redirect_chains_and_cycles(self):
        destination = self.routes['articles']['af'][uuid_for(1)]
        source = '/af/' + self.routes['articles']['en'][uuid_for(1)].split('/', 2)[2]
        compatibility = self.model['articles']['af'][0]['compatibility_url']
        self.mutate(source, f'content="0;url={destination}"', f'content="0;url={compatibility}"')
        self.mutate(source, f'href="{ORIGIN + destination}"', f'href="{ORIGIN + compatibility}"')
        self.assertTrue(any('redirect chain or cycle' in e for e in self.check().errors))
        self.mutate(compatibility, f'content="0;url={destination}"', f'content="0;url={source}"')
        self.mutate(compatibility, f'href="{ORIGIN + destination}"', f'href="{ORIGIN + source}"')
        self.assertTrue(any('redirect chain or cycle' in e for e in self.check().errors))

    def test_detects_readable_but_wrong_language_selector_identity(self):
        article = self.model['articles']['en'][0]
        destination = self.routes['articles']['fr'][article['id']]
        wrong = self.routes['articles']['fr'][uuid_for(2)]
        self.mutate(article['url'], f'value="{destination}" data-locale="fr"',
                    f'value="{wrong}" data-locale="fr"')
        self.assertTrue(any('language selector changes the articles identity' in e for e in self.check().errors))

    def test_detects_legacy_uuid_links_even_when_redirect_target_exists(self):
        article = self.model['articles']['en'][0]
        self.mutate(article['url'], '</main>', f'<a href="{article["compatibility_url"]}">old alias</a></main>')
        self.assertTrue(any('UUID in reader-facing URL' in e for e in self.check().errors))

    def test_detects_duplicate_article_body_published_at_redirect_address(self):
        article = self.model['articles']['af'][0]
        alternate = '/af/' + self.routes['articles']['en'][article['id']].split('/', 2)[2]
        self.page_path(alternate).write_text(self.page_path(article['url']).read_text())
        self.assertTrue(any('Published article inventory mismatch' in e for e in self.check().errors))

    def test_detects_uuid_values_in_search_filter_urls(self):
        identity = self.model['categories'][0]['id']
        slug = self.routes['categories']['en'][identity].rstrip('/').rsplit('/', 1)[-1]
        self.mutate('/en/search/', f'<option value="{slug}">', f'<option value="{identity}">')
        self.assertTrue(any('search filters must use the canonical readable' in e for e in self.check().errors))

    def test_detects_broken_images_and_unicode_encoded_local_links(self):
        route = '/fr/'
        self.mutate(route, '</main>', '<img src="/images/missing.jpg" alt=""><a href="/fr/absent/">broken</a></main>')
        errors = self.check().errors
        self.assertTrue(any('broken local link /images/missing.jpg' in e for e in errors))
        self.assertTrue(any('broken local link /fr/absent/' in e for e in errors))
        checker = SiteChecker(self.output).scan()
        path = '/fr/le-coin-des-b%C3%A9n%C3%A9dictions/'
        self.assertEqual(checker.local_reference(path)[0], '/fr/le-coin-des-bénédictions/')
        self.assertIsNotNone(checker.target_file(checker.local_reference(path)[0]))

    def test_detects_nonreciprocal_hreflang(self):
        route = self.model['articles']['af'][0]['url']
        self.mutate(route, 'hreflang="en"', 'hreflang="fr"')
        self.assertTrue(any('hreflang' in e for e in self.check().errors))

    def test_detects_rewritten_source_or_notice_even_if_inventory_matches(self):
        article = self.model['articles']['af'][0]
        self.mutate(article['url'], 'KI-vertaling.', 'Altered editorial notice.')
        self.assertTrue(any('original exported HTML/notice was changed' in e for e in self.check().errors))

    def test_detects_broken_language_dropdown_destination(self):
        self.mutate('/fr/', 'value="/af/" data-locale="af"', 'value="/af/missing/" data-locale="af"')
        self.assertTrue(any('broken local link /af/missing/' in e for e in self.check().errors))

    def test_detects_removed_markdown_fallback(self):
        article = self.model['articles']['en'][0]
        self.mutate(article['url'], 'id="markdown-text"', 'id="missing-fallback"')
        self.assertTrue(any('Markdown download/copy/fallback controls' in e for e in self.check().errors))

    def test_detects_missing_article_and_search_inventory(self):
        article = self.model['articles']['en'][0]
        self.page_path(article['url']).unlink()
        write(self.output / 'en/search-index.json', '[]')
        errors = self.check().errors
        self.assertTrue(any('Published article inventory mismatch' in e for e in errors))
        self.assertTrue(any('search article inventory/order mismatch' in e for e in errors))

    def test_detects_manufactured_rss_day_for_seasonal_issue(self):
        file = self.output / 'en/feed.xml'
        root = ET.parse(file).getroot()
        ET.SubElement(root.find('channel/item'), 'pubDate').text = 'Mon, 01 Jul 2024 00:00:00 GMT'
        file.write_text(ET.tostring(root, encoding='unicode'))
        self.assertTrue(any('manufactures a publication day' in e for e in self.check().errors))

    def test_rss_publishes_available_articles_and_no_imprecise_dates(self):
        for tag, count in [('en', 3), ('af', 1), ('fr', 0)]:
            root = ET.parse(self.output / tag / 'feed.xml')
            self.assertEqual(len(root.findall('channel/item')), count)
            self.assertEqual(root.findall('.//pubDate'), [])

    def test_detects_runtime_metadata_secrets_and_private_reports(self):
        write(self.output / 'build-report.json', json.dumps({'translation_omissions': [], 'source_metadata': {'internal': 'audit'}}))
        write(self.output / 'assets/leak.js', 'const accidental = "ghp_' + 'x' * 36 + '";')
        errors = self.check().errors
        self.assertTrue(any('Private build/source file' in e for e in errors))
        self.assertTrue(any('private JSON field source_metadata' in e for e in errors))
        self.assertTrue(any('Credential-like value' in e for e in errors))

    def test_compressed_search_index_matches_audited_json_exactly(self):
        for tag in self.locales:
            plain = self.output / tag / 'search-index.json'
            compressed = self.output / tag / 'search-index.json.gz'
            self.assertEqual(gzip.decompress(compressed.read_bytes()), plain.read_bytes())
            self.assertEqual(compressed.read_bytes()[4:8], b'\0' * 4)
        self.assertEqual(self.check().errors, [])

    def test_detects_stale_or_private_content_only_in_compressed_search(self):
        compressed = self.output / 'fr/search-index.json.gz'
        compressed.write_bytes(gzip.compress(b'[{"source_metadata":"private"}]', mtime=0))
        self.assertTrue(any('Compressed search index differs from neighboring JSON' in e for e in self.check().errors))

    def test_detects_invalid_missing_or_nondeterministic_compressed_search(self):
        (self.output / 'fr/search-index.json.gz').write_bytes(b'not gzip')
        (self.output / 'af/search-index.json.gz').unlink()
        english = self.output / 'en/search-index.json'
        english.with_suffix('.json.gz').write_bytes(gzip.compress(english.read_bytes(), mtime=1234))
        errors = self.check().errors
        self.assertTrue(any('Invalid compressed search index: fr/' in e for e in errors))
        self.assertTrue(any('Missing compressed search index: af/' in e for e in errors))
        self.assertTrue(any('Search gzip header is not deterministic' in e for e in errors))

    def test_compressed_search_cannot_hide_without_a_plain_json_neighbor(self):
        (self.output / 'fr/search-index.json').unlink()
        self.assertTrue(any('Compressed search index has no safe JSON neighbor' in e for e in self.check().errors))

    def test_safe_public_deployment_identity_is_allowed(self):
        write(self.output / 'deployment.json', json.dumps({'schema': 1, 'display_fingerprint': 'a'*64,
              'revisions': {'english': 'b'*40, 'translations': None, 'theme': 'c'*40, 'site': 'd'*40}, 'translation_status': 'failed'}))
        self.assertEqual(self.check().errors, [])

    def test_detects_theme_logo_or_favicon_byte_changes(self):
        (self.output / 'assets/brand/logo.jpg').write_bytes(b'modified pixels')
        (self.output / 'assets/favicons/favicon.ico').write_bytes(b'modified icon')
        errors = self.check().errors
        self.assertEqual(sum('Theme asset pixels/bytes were changed' in e for e in errors), 2)

    def test_detects_footer_destination_changes(self):
        self.mutate('/fr/', 'https://truechristian.church/history', 'https://unrelated.example/')
        self.assertTrue(any('footer destinations/order changed' in e for e in self.check().errors))

    def test_detects_missing_english_notice_target_and_improper_indexing(self):
        route = self.routes['articles']['fr'][uuid_for(1)]
        self.mutate(route, '<meta name="robots" content="noindex,follow">', '')
        self.assertTrue(any('missing translation must explain absence' in e for e in self.check().errors))

    def test_detects_incomplete_category_and_wrong_issue_sequence(self):
        route = self.routes['issues']['en'][I]
        self.mutate(route, '<span class="contents-number">1</span>', '<span class="contents-number">99</span>')
        self.assertTrue(any('source sequence mismatch' in e for e in self.check().errors))

    def test_detects_anchor_and_canonical_regressions(self):
        self.mutate('/fr/', 'href="#main"', 'href="#absent"')
        self.mutate('/en/', '<link rel="canonical" href="' + ORIGIN + '/en/">', '<link rel="canonical" href="' + ORIGIN + '/fr/">')
        errors = self.check().errors
        self.assertTrue(any('missing anchor /fr/#absent' in e for e in errors))
        self.assertTrue(any('canonical is not self-referential' in e for e in errors))

    def test_detects_wrong_current_locale_and_direction(self):
        self.mutate('/fr/', '<html lang="fr" dir="ltr">', '<html lang="en" dir="rtl">')
        errors = self.check().errors
        self.assertTrue(any('expected \'fr\'' in e for e in errors))
        self.assertTrue(any('direction disagrees with locale' in e for e in errors))


class BuildModeTests(unittest.TestCase):
    def test_english_only_generates_complete_empty_interfaces_without_stale_translation(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, locales, routes, theme, output = fixture(Path(temporary), translated=False)
            checker = SiteChecker(output)
            self.assertEqual(checker.run(model=model, locales=locales, routes=routes, theme=theme), [])
            self.assertEqual(CounterArticleIds(checker), {'en': 3})
            self.assertEqual(checker.search['af'], [])
            self.assertEqual(checker.search['fr'], [])
            self.assertEqual(list((output / 'af/articles').glob('*.md')), [])
            self.assertTrue(checker.pages[routes['articles']['af'][uuid_for(1)]].noindex)
            self.assertEqual(checker.pages[f'/af/articles/{uuid_for(1)}/'].redirect,
                             routes['articles']['af'][uuid_for(1)])

    def test_unicode_localized_aliases_and_encoded_prefix_redirects_resolve(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, locales, routes, theme, output = fixture(Path(temporary), translated_title='Genade en seën')
            checker = SiteChecker(output)
            self.assertEqual(checker.run(model=model, locales=locales, routes=routes, theme=theme), [])
            article = model['articles']['af'][0]
            self.assertTrue(article['url'].endswith('/genade-en-seën/'))
            encoded = article['url'].replace('ë', '%C3%AB')
            self.assertEqual(checker.local_reference(encoded)[0], article['url'])
            self.assertIsNotNone(checker.target_file(checker.local_reference(encoded)[0]))
            changed = '/en/' + article['url'].split('/', 2)[2]
            self.assertEqual(checker.pages[changed].redirect, routes['articles']['en'][article['id']])

    def test_duplicate_titles_use_readable_numeric_suffixes_and_preserve_article_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, locales, routes, theme, output = fixture(Path(temporary), duplicate_titles=True, translated_count=2)
            checker = SiteChecker(output)
            self.assertEqual(checker.run(model=model, locales=locales, routes=routes, theme=theme), [])
            english = [article['url'].rstrip('/').rsplit('/', 1)[-1] for article in model['articles']['en']]
            afrikaans = [article['url'].rstrip('/').rsplit('/', 1)[-1] for article in model['articles']['af']]
            self.assertEqual(english, ['english-source', 'english-source-2', 'english-source-3'])
            self.assertEqual(afrikaans, ['afrikaanse-opskrif', 'afrikaanse-opskrif-2'])
            self.assertEqual(CounterArticleIds(checker), {'en': 3, 'af': 2})
            for article in model['articles']['af']:
                requested = '/af/' + routes['articles']['en'][article['id']].split('/', 2)[2]
                self.assertEqual(checker.pages[requested].redirect, article['url'])

    def test_paginated_listings_never_claim_first_page_hreflang_equivalence(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, locales, routes, theme, output = fixture(Path(temporary), count=27)
            checker = SiteChecker(output)
            self.assertEqual(checker.run(model=model, locales=locales, routes=routes, theme=theme), [])
            page = checker.pages['/en/articles/page/2/']
            self.assertTrue(page.noindex)
            self.assertEqual(page.alternates, {})
            self.assertEqual(page.canonical, [ORIGIN + '/en/articles/page/2/'])
            self.assertFalse((output / 'fr/articles/page/2/index.html').exists())
            path = output / 'en/articles/page/2/index.html'
            path.write_text(path.read_text().replace('</head>', '<link rel="alternate" hreflang="fr" href="' + ORIGIN + '/fr/articles/"></head>'))
            self.assertTrue(any('noindex page advertises hreflang' in e for e in SiteChecker(output).run()))

    def test_missing_translated_title_uses_local_interface_fallback_never_english_title(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, locales, routes, theme, output = fixture(Path(temporary), missing_title=True)
            checker = SiteChecker(output)
            self.assertEqual(checker.run(model=model, locales=locales, routes=routes, theme=theme), [])
            page = checker.pages[model['articles']['af'][0]['url']]
            self.assertEqual(page.h1, locales['af']['ui']['untitled_article'])
            self.assertNotEqual(page.h1, locales['en']['ui']['untitled_article'])

    def test_private_metadata_detection_is_structural_not_word_search(self):
        self.assertEqual(list(private_json_keys({'body': 'The word prompt in an article is ordinary public text.'})), [])
        self.assertEqual(list(private_json_keys({'records': [{'source_translation_key': 'secret'}]})), ['source_translation_key'])


def CounterArticleIds(checker):
    result = {}
    for page in checker.pages.values():
        if page.article_ids:
            result[page.lang] = result.get(page.lang, 0) + len(page.article_ids)
    return result


if __name__ == '__main__':
    unittest.main()
