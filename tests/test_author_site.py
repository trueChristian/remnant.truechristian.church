"""Exercise complete author pages against independent English source records."""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_site import ROOT, J, fixture, uuid_for, write
from build import ORIGIN, Site
from check_site import PageParser, SiteChecker, normalized_text
from i18n import load_locales
from routes import initialize_routes


PRIMARY = 'Zoe Writer'
COAUTHOR = 'Anne Writer'
VARIANT = 'Zoe writer'


def author_site_fixture(root, *, count=5, translated_count=2, all_locales=False):
    """Build exact-name variants, coauthors, historical details, and missing locales.

    PRIMARY owns ``count - 2`` articles. Article two also credits COAUTHOR;
    article three belongs only to VARIANT, and the last article is raw-only.
    """
    if count < 4:
        raise ValueError('Author site fixture requires at least four articles')
    model, locales, _, theme, output = fixture(root, count=count, translated_count=translated_count)
    if all_locales:
        locales = load_locales(ROOT / 'locales')
        for locale in locales.values():
            locale['categories'] = {category['id']: locale['categories'][category['id']] for category in model['categories']}
    for index, source in enumerate(model['articles']['en']):
        name = VARIANT if index == 2 else PRIMARY
        people = [{'name': name, 'location': 'Old Town' if index == 0 else 'Coastville',
                   'role': 'Editor' if index == 0 else 'Writer'}]
        if index == 1:
            people.append({'name': COAUTHOR, 'role': 'Coauthor'})
        if index == count - 1:
            people = []
        raw = ('from Herald of His Coming' if not people else
               'Written by ' + ' & '.join(person['name'] for person in people) + ' — as printed')
        source['byline'] = {'raw': raw, 'authors': people}
        source['source_metadata'] = {'byline': copy.deepcopy(source['byline'])}
        if index == 0:
            source['images'] = [{'public_path': '/images/articles/fixture.jpg', 'alt': 'Original article illustration'}]
            source['html'] = source['html'].replace('</article>', '<img src="/images/articles/fixture.jpg" alt="Original article illustration"></article>')
        for translated in model['articles'].get('af', []):
            if translated['id'] == source['id']:
                translated['byline'] = copy.deepcopy(source['byline'])
                translated['source_metadata'] = copy.deepcopy(source['source_metadata'])
    write(output / 'images/articles/fixture.jpg', 'original fixture image')
    routes = initialize_routes(model, locales, root / 'authors-route-source.json', update=True)
    Site(model, locales, routes, theme, output, {}).build()
    return model, locales, routes, theme, output


class AuthorPageParser(PageParser):
    """Capture public semantics independently of the generator's author index."""
    def __init__(self, route, source):
        self.cards = []
        self.current_card = None
        self.article_links = []
        self.section_images = []
        super().__init__(route, source)
        for card in self.cards:
            card['name'] = normalized_text(''.join(card.pop('name_parts')))
            card['text'] = normalized_text(' '.join(card.pop('text_parts')))

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set(attributes.get('class', '').split())
        super().handle_starttag(tag, attrs)
        if 'author-card' in classes:
            self.current_card = {'href': attributes.get('href'), 'links': [], 'name_parts': [], 'text_parts': []}
            self.cards.append(self.current_card)
        if tag == 'a' and self.current_card is not None:
            self.current_card['links'].append(attributes.get('href', ''))
        if tag == 'a' and self.within('author-articles') and (self.within('h2') or self.within('h3')):
            self.article_links.append(attributes.get('href', ''))
        if tag == 'img' and any(self.within(name) for name in ('authors-page', 'author-profile', 'author-articles')):
            self.section_images.append(attributes.get('src'))

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if not self.within('author-card'):
            self.current_card = None

    def handle_data(self, data):
        super().handle_data(data)
        if self.current_card is not None:
            self.current_card['text_parts'].append(data)
            if self.within('h2') or self.within('h3'):
                self.current_card['name_parts'].append(data)


class AuthorSiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model, self.locales, self.routes, self.theme, self.output = author_site_fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def parse(self, route):
        source = (self.output / route.lstrip('/') / 'index.html').read_text()
        return AuthorPageParser(route, source)

    def check(self):
        checker = SiteChecker(self.output)
        checker.run(model=self.model, locales=self.locales, routes=self.routes, theme=self.theme)
        return checker

    def test_complete_author_archive_passes_independent_site_checker(self):
        self.assertEqual(self.check().errors, [])

    def test_directory_preserves_exact_variants_and_counts_distinct_articles(self):
        page = self.parse('/en/authors/')
        self.assertEqual([card['name'] for card in page.cards], [COAUTHOR, PRIMARY, VARIANT])
        expected_counts = {COAUTHOR: 1, PRIMARY: 3, VARIANT: 1}
        for card in page.cards:
            count = expected_counts[card['name']]
            self.assertIn(self.routes['authors']['en'][card['name']], card['links'])
            self.assertIn(self.locales['en']['ui']['author_total_articles'].format(count=count), card['text'])
            self.assertIn(self.locales['en']['ui']['author_available_articles'].format(count=count), card['text'])
        self.assertNotIn('Herald of His Coming', ' '.join(card['text'] for card in page.cards))
        self.assertEqual(page.section_images, [])

    def test_profile_lists_only_its_articles_at_existing_category_urls(self):
        expected_ids = [uuid_for(4), uuid_for(2), uuid_for(1)]
        expected = [self.routes['articles']['en'][identity] for identity in expected_ids]
        page = self.parse(self.routes['authors']['en'][PRIMARY])
        self.assertEqual(page.page.h1, PRIMARY)
        self.assertEqual(page.article_links, expected)
        self.assertEqual(page.section_images, [])
        self.assertEqual(page.page.article_ids, [])
        self.assertTrue(all('/authors/' not in route for route in page.article_links))
        for value in ('Old Town', 'Coastville', 'Editor', 'Writer'):
            self.assertIn(value, page.page.main_text)
        self.assertIn(self.locales['en']['ui']['author_recorded_details'], page.page.main_text)
        coauthor = self.parse(self.routes['authors']['en'][COAUTHOR])
        self.assertEqual(coauthor.article_links, [self.routes['articles']['en'][uuid_for(2)]])
        self.assertEqual(self.parse(self.routes['authors']['en'][VARIANT]).article_links,
                         [self.routes['articles']['en'][uuid_for(3)]])

    def test_profile_uses_issue_recency_before_article_sequence(self):
        first = self.model['articles']['en'][0]
        first.update(issue_id=J, issue=copy.deepcopy(self.model['issues'][1]), sequence=0)
        Site(self.model, self.locales, self.routes, self.theme, self.output, {}).build()
        page = self.parse(self.routes['authors']['en'][PRIMARY])
        self.assertEqual(page.article_links, [self.routes['articles']['en'][identity]
                                              for identity in (uuid_for(4), uuid_for(2), uuid_for(1))])

    def test_available_language_counts_and_article_links_match_published_translation_inventory(self):
        page = self.parse('/af/authors/')
        expected_counts = {COAUTHOR: 1, PRIMARY: 2, VARIANT: 0}
        for card in page.cards:
            self.assertIn(self.locales['af']['ui']['author_available_articles'].format(count=expected_counts[card['name']]), card['text'])
        profile = self.parse(self.routes['authors']['af'][PRIMARY])
        self.assertEqual(profile.article_links, [self.routes['articles']['af'][identity]
                                                 for identity in (uuid_for(2), uuid_for(1))])
        self.assertTrue(all(route.startswith('/af/') for route in profile.article_links))

    def test_empty_language_profile_keeps_identity_and_links_matching_english_author(self):
        route = self.routes['authors']['fr'][PRIMARY]
        page = self.parse(route)
        self.assertEqual(page.page.h1, PRIMARY)
        self.assertEqual(page.article_links, [])
        self.assertIn(self.locales['fr']['ui']['author_no_articles'], page.page.main_text)
        self.assertIn(self.locales['fr']['ui']['author_read_english'], page.page.main_text)
        self.assertIn(self.routes['authors']['en'][PRIMARY], page.page.references)
        self.assertEqual(page.page.languages, {tag: self.routes['authors'][tag][PRIMARY] for tag in self.locales})
        self.assertEqual(page.page.canonical, [ORIGIN + route])

    def test_reader_byline_links_preserve_printed_credit_and_original_html(self):
        for tag in ('en', 'af'):
            article = next(item for item in self.model['articles'][tag] if item['id'] == uuid_for(2))
            page = self.parse(article['url'])
            self.assertIn(article['byline']['raw'], page.page.main_text)
            self.assertIn(self.routes['authors'][tag][PRIMARY], page.page.references)
            self.assertIn(self.routes['authors'][tag][COAUTHOR], page.page.references)
            source = (self.output / article['url'].lstrip('/') / 'index.html').read_text()
            expected_html = article['html'].replace('/en/articles/' + article['id'] + '/', self.routes['articles']['en'][article['id']])
            self.assertIn(expected_html, source)
            self.assertEqual(page.page.canonical, [ORIGIN + article['url']])

    def test_repeated_printed_name_stays_intact_with_one_link_per_contributor(self):
        raw = f'{PRIMARY}, 2005; arranged by {PRIMARY}'
        for tag in ('en', 'af'):
            article = next(item for item in self.model['articles'][tag] if item['id'] == uuid_for(1))
            article['byline']['raw'] = raw
            article['source_metadata']['byline']['raw'] = raw
        Site(self.model, self.locales, self.routes, self.theme, self.output, {}).build()
        for tag in ('en', 'af'):
            page = self.parse(self.routes['articles'][tag][uuid_for(1)]).page
            self.assertIn(raw, page.main_text)
            self.assertEqual(page.author_byline_links, [(PRIMARY, self.routes['authors'][tag][PRIMARY])])
        self.assertEqual(self.check().errors, [])

    def test_search_index_keeps_raw_credits_and_only_same_language_contributor_links(self):
        for tag in ('en', 'af'):
            records = {record['id']: record for record in json.loads((self.output / tag / 'search-index.json').read_text())}
            shared = records[uuid_for(2)]
            self.assertEqual(shared['authors'], [{'name': name, 'url': self.routes['authors'][tag][name]}
                                                  for name in (COAUTHOR, PRIMARY)])
            self.assertEqual(shared['author'], 'Written by Zoe Writer & Anne Writer — as printed')
            self.assertEqual(self.parse(f'/{tag}/search/').page.config['authorLabel'], self.locales[tag]['ui']['author'])
        self.assertEqual(records[uuid_for(1)]['authors'], [{'name': PRIMARY, 'url': self.routes['authors']['af'][PRIMARY]}])
        english = json.loads((self.output / 'en/search-index.json').read_text())
        raw_only = next(record for record in english if record['id'] == uuid_for(5))
        self.assertEqual(raw_only['author'], 'from Herald of His Coming')
        self.assertEqual(raw_only['authors'], [])

    def test_second_page_has_no_false_language_equivalents_and_switches_to_author_base(self):
        self.model, self.locales, self.routes, self.theme, self.output = author_site_fixture(self.root / 'pagination', count=29)
        base = self.routes['authors']['en'][PRIMARY]
        first = self.parse(base)
        second = self.parse(base + 'page/2/')
        expected = [self.routes['articles']['en'][uuid_for(number)] for number in range(28, 0, -1) if number != 3]
        self.assertEqual(first.article_links, expected[:24])
        self.assertEqual(second.article_links, expected[24:])
        self.assertEqual(len(set(first.article_links + second.article_links)), 27)
        self.assertTrue(second.page.noindex)
        self.assertEqual(second.page.alternates, {})
        self.assertEqual(second.page.canonical, [ORIGIN + base + 'page/2/'])
        self.assertEqual(second.page.languages, {tag: self.routes['authors'][tag][PRIMARY] for tag in self.locales})
        self.assertIn(base, second.page.references)

    def test_manual_paginated_language_prefix_returns_to_matching_author(self):
        self.model, self.locales, self.routes, self.theme, self.output = author_site_fixture(self.root / 'prefix', count=29)
        english = self.routes['authors']['en'][PRIMARY]
        for tag in ('af', 'fr'):
            requested = f'/{tag}/' + english.split('/', 2)[2] + 'page/2/'
            page = self.parse(requested).page
            self.assertEqual(page.redirect, self.routes['authors'][tag][PRIMARY])
            self.assertEqual(page.canonical, [ORIGIN + self.routes['authors'][tag][PRIMARY]])
            self.assertTrue(page.noindex)
            self.assertEqual(page.article_ids, [])
            self.assertEqual(page.alternates, {})

    def test_all_configured_locales_have_translated_navigation_and_author_pages(self):
        self.model, self.locales, self.routes, self.theme, self.output = author_site_fixture(self.root / 'all-locales', all_locales=True)
        for tag, locale in self.locales.items():
            with self.subTest(locale=tag):
                directory = self.parse(f'/{tag}/authors/')
                profile = self.parse(self.routes['authors'][tag][PRIMARY])
                self.assertEqual(directory.page.h1, locale['ui']['authors'])
                self.assertEqual(directory.page.lang, tag)
                self.assertEqual(directory.page.direction, locale['meta']['dir'])
                self.assertEqual(directory.page.languages, {code: f'/{code}/authors/' for code in self.locales})
                self.assertEqual(profile.page.languages, {code: self.routes['authors'][code][PRIMARY] for code in self.locales})
                self.assertEqual(profile.page.direction, locale['meta']['dir'])
                source = (self.output / tag / 'authors/index.html').read_text()
                self.assertRegex(source, rf'<a[^>]*href="/{re.escape(tag)}/authors/"[^>]*>\s*{re.escape(locale["ui"]["authors"])}\s*</a>')
                self.assertEqual(directory.section_images + profile.section_images, [])


if __name__ == '__main__':
    unittest.main()
