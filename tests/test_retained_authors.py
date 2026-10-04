"""Historical author attribution stays attached to the correct locale reader."""
import copy
from html import escape
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import test_retained_reader as reader_fixtures
from build import ORIGIN, Site
from check_site import SiteChecker
from routes import initialize_routes


CURRENT_AUTHOR = 'Current English Author'
ORIGINAL_AUTHOR = 'Original Printed Author'
FORGED_AUTHOR = 'Untrusted Translation Author'


class RetainedAuthorTests(unittest.TestCase):
    def setUp(self):
        builder = reader_fixtures.RetainedReaderTests()
        builder.setUp()
        self.addCleanup(builder.doCleanups)
        base = builder.fixture(tags=('en', 'af', 'fr'))
        english = base.model['articles']['en'][0]
        english['byline'] = {'raw': CURRENT_AUTHOR, 'authors': [{'name': CURRENT_AUTHOR, 'location': 'New town'}]}
        english['source_metadata'] = {'byline': copy.deepcopy(english['byline'])}
        retained = base.model['articles']['af'][0]
        retained['byline'] = {'raw': ORIGINAL_AUTHOR, 'authors': [{'name': ORIGINAL_AUTHOR, 'location': 'Old town'}]}
        retained['source_metadata'] = {'byline': copy.deepcopy(retained['byline'])}
        ready = base.model['articles']['fr'][0]
        ready.pop('retention')
        ready['byline'] = copy.deepcopy(english['byline'])
        ready['source_metadata'] = {'byline': {'raw': FORGED_AUTHOR, 'authors': [{'name': FORGED_AUTHOR}]}}
        ready['source_revision'] = reader_fixtures.CURRENT
        routes = initialize_routes(base.model, base.locales, builder.root / 'author-routes.json', update=True)
        self.site = Site(base.model, base.locales, routes, base.theme, base.output, {})
        for tag in self.site.locales:
            self.site.authors_page(tag)
            for author in self.site.authors:
                self.site.author_page(tag, author)
            self.site.article_page(tag, self.site.articles[tag][0])
            self.site.search_page(tag)

    def reader(self, tag):
        article = self.site.articles[tag][0]
        return (self.site.output / article['url'].lstrip('/') / 'index.html').read_text(encoding='utf-8')

    def check(self):
        checker = SiteChecker(self.site.output).scan()
        checker.check_authors(self.site.model, self.site.locales, self.site.routes)
        return checker

    def test_retained_and_current_author_routes_and_memberships_are_distinct(self):
        self.assertEqual(set(self.site.author_map), {CURRENT_AUTHOR, ORIGINAL_AUTHOR})
        for tag, expected in [('en', CURRENT_AUTHOR), ('af', ORIGINAL_AUTHOR), ('fr', CURRENT_AUTHOR)]:
            with self.subTest(locale=tag):
                identity = self.site.articles[tag][0]['id']
                self.assertEqual([author['name'] for author in self.site.article_authors[(tag, identity)]], [expected])
                self.assertEqual(set(self.site.routes['authors'][tag]), {CURRENT_AUTHOR, ORIGINAL_AUTHOR})
                self.assertEqual([article['id'] for article in self.site.author_articles[tag][expected]], [identity])
                other = ORIGINAL_AUTHOR if expected == CURRENT_AUTHOR else CURRENT_AUTHOR
                self.assertEqual(self.site.author_articles[tag][other], [])
        self.assertEqual(self.site.author_map[ORIGINAL_AUTHOR]['details'], {'location': ['Old town']})
        self.assertEqual(self.check().errors, [])

    def test_reader_jsonld_and_search_keep_the_original_author_only_in_retained_locale(self):
        for tag, expected in [('en', CURRENT_AUTHOR), ('af', ORIGINAL_AUTHOR), ('fr', CURRENT_AUTHOR)]:
            with self.subTest(locale=tag):
                reader = self.reader(tag)
                expected_url = self.site.routes['authors'][tag][expected]
                byline = re.search(r'<div class="article-byline">(.*?)</div>', reader, re.S)[1]
                self.assertIn(expected, byline)
                self.assertIn(f'href="{expected_url}"', byline)
                self.assertNotIn('byline-authors', byline)
                self.assertNotIn(FORGED_AUTHOR, reader)
                structured = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', reader, re.S)[1])
                self.assertEqual(structured['author'], [{'@type': 'Person', 'name': expected, 'url': ORIGIN + expected_url}])
                record = json.loads((self.site.output / tag / 'search-index.json').read_text())[0]
                self.assertEqual(record['authors'], [{'name': expected, 'url': expected_url, 'aliases': [expected]}])

    def test_historical_only_author_keeps_counts_and_available_locale_without_english_shortcut(self):
        checker = self.check()
        self.assertEqual(checker.errors, [])
        routes = self.site.routes['authors']
        for tag, expected_available in [('en', 0), ('af', 1), ('fr', 0)]:
            with self.subTest(locale=tag):
                page = checker.pages[routes[tag][ORIGINAL_AUTHOR]]
                self.assertIn(self.site.ui(tag, 'author_total_articles', count=1), page.author_counts_text)
                self.assertIn(self.site.ui(tag, 'author_available_articles', count=expected_available), page.author_counts_text)
                directory = checker.pages[f'/{tag}/authors/']
                card = next(card for card in directory.author_cards if card['name'] == ORIGINAL_AUTHOR)
                self.assertIn(self.site.ui(tag, 'author_total_articles', count=1), card['text'])
                self.assertIn(self.site.ui(tag, 'author_available_articles', count=expected_available), card['text'])
                self.assertEqual(page.author_empty_links, [])
                self.assertEqual(page.languages['af'], routes['af'][ORIGINAL_AUTHOR])
                self.assertIn(routes['af'][ORIGINAL_AUTHOR], page.references)
                expected_articles = [self.site.articles['af'][0]['url']] if tag == 'af' else []
                self.assertEqual(page.author_article_links, expected_articles)
        # An empty translated profile still offers English when English work
        # really exists for that author.
        current_af = checker.pages[routes['af'][CURRENT_AUTHOR]]
        self.assertEqual(current_af.author_empty_links, [
            (self.site.ui('af', 'author_read_english'), routes['en'][CURRENT_AUTHOR])])

    def test_checker_rejects_empty_english_shortcuts_for_historical_only_author(self):
        for tag in ('en', 'fr'):
            with self.subTest(locale=tag):
                route = self.site.routes['authors'][tag][ORIGINAL_AUTHOR]
                path = self.site.output / route.lstrip('/') / 'index.html'
                original = path.read_text(encoding='utf-8')
                notice = '<p>' + escape(self.site.ui(tag, 'author_no_articles'), quote=True) + '</p>'
                shortcut = ('<a class="button" href="' + self.site.routes['authors']['en'][ORIGINAL_AUTHOR]
                            + '" hreflang="en">' + escape(self.site.ui(tag, 'author_read_english'), quote=True) + '</a>')
                self.assertIn(notice, original)
                path.write_text(original.replace(notice, notice + shortcut, 1), encoding='utf-8')
                self.assertTrue(any('empty author profile' in error for error in self.check().errors))
                path.write_text(original, encoding='utf-8')

    def test_checker_rejects_current_author_inserted_into_retained_byline(self):
        article = self.site.articles['af'][0]
        path = self.site.output / article['url'].lstrip('/') / 'index.html'
        reader = path.read_text(encoding='utf-8')
        original = self.site.routes['authors']['af'][ORIGINAL_AUTHOR]
        current = self.site.routes['authors']['af'][CURRENT_AUTHOR]
        reader = reader.replace(f'class="author-link" href="{original}"',
                                f'class="author-link" href="{current}"', 1)
        path.write_text(reader, encoding='utf-8')
        self.assertTrue(any('author byline links do not match' in error for error in self.check().errors))

    def test_checker_rejects_retained_article_on_current_author_profile(self):
        path = self.site.output / self.site.routes['authors']['af'][CURRENT_AUTHOR].lstrip('/') / 'index.html'
        original_path = self.site.output / self.site.routes['authors']['af'][ORIGINAL_AUTHOR].lstrip('/') / 'index.html'
        original = original_path.read_text(encoding='utf-8')
        works = re.search(r'<section class="author-works">.*?</section>', original, re.S)[0]
        page = path.read_text(encoding='utf-8').replace('</main>', works + '</main>')
        path.write_text(page, encoding='utf-8')
        self.assertTrue(any('author article inventory/order' in error for error in self.check().errors))

    def test_checker_rejects_current_author_in_retained_search_metadata(self):
        path = self.site.output / 'af/search-index.json'
        records = json.loads(path.read_text())
        records[0]['authors'] = [{'name': CURRENT_AUTHOR, 'url': self.site.routes['authors']['af'][CURRENT_AUTHOR],
                                  'aliases': [CURRENT_AUTHOR]}]
        path.write_text(json.dumps(records), encoding='utf-8')
        self.assertTrue(any('search author links differ' in error for error in self.check().errors))

    def test_checker_rejects_current_author_in_retained_jsonld(self):
        article = self.site.articles['af'][0]
        path = self.site.output / article['url'].lstrip('/') / 'index.html'
        reader = path.read_text(encoding='utf-8')
        match = re.search(r'(<script type="application/ld\+json">)(.*?)(</script>)', reader, re.S)
        structured = json.loads(match[2])
        structured['author'] = [{'@type': 'Person', 'name': CURRENT_AUTHOR,
                                 'url': ORIGIN + self.site.routes['authors']['af'][CURRENT_AUTHOR]}]
        reader = reader[:match.start(2)] + json.dumps(structured) + reader[match.end(2):]
        path.write_text(reader, encoding='utf-8')
        self.assertTrue(any('structured author attribution differs' in error for error in self.check().errors))


if __name__ == '__main__':
    unittest.main()
