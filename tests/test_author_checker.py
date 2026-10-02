"""Mutation tests for author inventories, canonical links, and locale navigation."""
import gzip
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_author_site import author_site_fixture, PRIMARY, COAUTHOR, VARIANT
from tests.test_site import uuid_for
from check_site import SiteChecker
from build import Site
from routes import initialize_routes


class AuthorCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model, self.locales, self.routes, self.theme, self.output = author_site_fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def page_path(self, route):
        return self.output / route.lstrip('/') / 'index.html'

    def mutate(self, route, old, new):
        path = self.page_path(route)
        text = path.read_text(encoding='utf-8')
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding='utf-8')

    def errors(self):
        return SiteChecker(self.output).run(model=self.model, locales=self.locales,
                                            routes=self.routes, theme=self.theme)

    def assert_error(self, expected):
        errors = self.errors()
        self.assertTrue(any(expected in error for error in errors), errors)

    def merge_variants(self):
        """Migrate previously separate profiles and a doubly credited article."""
        self.old_variant_routes = {tag: records[VARIANT] for tag, records in self.routes['authors'].items()}
        for tag in ('en', 'af'):
            article = self.model['articles'][tag][0]
            article['byline']['authors'].append({'name': VARIANT, 'location': 'Hilltown'})
            article['byline']['raw'] = f'Written by {PRIMARY} & {VARIANT} — as printed'
            article['source_metadata']['byline'] = copy.deepcopy(article['byline'])
        self.routes = initialize_routes(self.model, self.locales,
                                        self.root / 'authors-route-source.json', update=True,
                                        author_aliases={PRIMARY: PRIMARY, VARIANT: PRIMARY})
        Site(self.model, self.locales, self.routes, self.theme, self.output, {}).build()

    def test_valid_author_output_passes(self):
        self.assertEqual(self.errors(), [])

    def test_merged_inventory_counts_article_union_and_accepts_printed_alias_links(self):
        self.merge_variants()
        self.assertEqual(self.errors(), [])
        checker = SiteChecker(self.output)
        checker.run(model=self.model, locales=self.locales, routes=self.routes, theme=self.theme)
        directory = checker.pages['/en/authors/']
        self.assertEqual([card['name'] for card in directory.author_cards], [COAUTHOR, PRIMARY])
        profile = checker.pages[self.routes['authors']['en'][PRIMARY]]
        self.assertIn(self.locales['en']['ui']['author_total_articles'].format(count=4), profile.author_counts_text)
        self.assertEqual(profile.author_article_links, [self.routes['articles']['en'][uuid_for(index)]
                                                       for index in (4, 3, 2, 1)])
        variant_article = checker.pages[self.routes['articles']['en'][uuid_for(3)]]
        self.assertEqual(variant_article.author_byline_links,
                         [(VARIANT, self.routes['authors']['en'][PRIMARY])])
        doubly_credited = checker.pages[self.routes['articles']['en'][uuid_for(1)]]
        self.assertEqual(doubly_credited.author_byline_links,
                         [(PRIMARY, self.routes['authors']['en'][PRIMARY])])
        self.assertIn(f'Written by {PRIMARY} & {VARIANT} — as printed', doubly_credited.main_text)
        for tag, old in self.old_variant_routes.items():
            self.assertEqual(checker.pages[old].redirect, self.routes['authors'][tag][PRIMARY])

    def test_detects_alias_credit_counted_as_an_additional_article(self):
        self.merge_variants()
        route = self.routes['authors']['en'][PRIMARY]
        self.mutate(route, '<span>' + self.locales['en']['ui']['author_total_articles'].format(count=4) + '</span>',
                    '<span>' + self.locales['en']['ui']['author_total_articles'].format(count=5) + '</span>')
        self.assert_error('count disagrees with source or locale availability')

    def test_detects_duplicate_article_in_merged_profile(self):
        self.merge_variants()
        route = self.routes['authors']['en'][PRIMARY]
        original = self.routes['articles']['en'][uuid_for(3)]
        duplicate = self.routes['articles']['en'][uuid_for(1)]
        self.mutate(route, f'<h2><a href="{original}">', f'<h2><a href="{duplicate}">')
        self.assert_error('author article inventory/order or canonical category links differ')

    def test_detects_alias_link_pointing_to_other_canonical_author(self):
        self.merge_variants()
        article = self.routes['articles']['en'][uuid_for(3)]
        self.mutate(article, f'class="author-link" href="{self.routes["authors"]["en"][PRIMARY]}"',
                    f'class="author-link" href="{self.routes["authors"]["en"][COAUTHOR]}"')
        self.assert_error('author byline links do not match the original named contributors')

    def test_detects_duplicate_canonical_link_for_two_printed_aliases(self):
        self.merge_variants()
        article = self.routes['articles']['en'][uuid_for(3)]
        path = self.page_path(article)
        original = path.read_text(encoding='utf-8')
        credit = re.search(r'<a class="author-link"[^>]*>.*?</a>', original).group(0)
        path.write_text(original.replace(credit, credit + credit, 1), encoding='utf-8')
        self.assert_error('author byline links do not match the original named contributors')

    def test_detects_missing_search_aliases_and_duplicate_canonical_contributors(self):
        self.merge_variants()
        path = self.output / 'en/search-index.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        for mutation in ('missing alias', 'duplicate contributor'):
            with self.subTest(mutation=mutation):
                records = copy.deepcopy(original)
                record = next(row for row in records if row['id'] == uuid_for(1))
                self.assertEqual(len(record['authors']), 1)
                self.assertEqual(set(record['authors'][0]['aliases']), {PRIMARY, VARIANT})
                if mutation == 'missing alias':
                    record['authors'][0]['aliases'] = [PRIMARY]
                else:
                    record['authors'].append(copy.deepcopy(record['authors'][0]))
                payload = json.dumps(records, ensure_ascii=False).encode('utf-8')
                path.write_bytes(payload)
                path.with_suffix('.json.gz').write_bytes(gzip.compress(payload, mtime=0))
                self.assert_error('search author links differ from original contributors or canonical author routes')

    def test_detects_retired_alias_redirecting_to_another_author(self):
        self.merge_variants()
        old = self.old_variant_routes['af']
        self.mutate(old, self.routes['authors']['af'][PRIMARY], self.routes['authors']['af'][COAUTHOR])
        self.assert_error('registered redirect does not directly identify canonical destination')

    def test_detects_missing_directory_card_even_when_profile_remains(self):
        route = '/en/authors/'
        path = self.page_path(route)
        original = path.read_text(encoding='utf-8')
        modified, count = re.subn(r'<article class="author-card">.*?</article>', '', original, count=1, flags=re.S)
        self.assertEqual(count, 1)
        path.write_text(modified, encoding='utf-8')
        self.assert_error('author directory inventory/order differs')

    def test_detects_names_swapped_between_canonical_profiles(self):
        route = '/en/authors/'
        old = f'class="author-name" href="{self.routes["authors"]["en"][COAUTHOR]}"'
        new = f'class="author-name" href="{self.routes["authors"]["en"][PRIMARY]}"'
        self.mutate(route, old, new)
        self.assert_error('author directory inventory/order differs')

    def test_detects_wrong_original_and_translated_counts(self):
        route = self.routes['authors']['af'][PRIMARY]
        self.mutate(route, '<span>' + self.locales['af']['ui']['author_total_articles'].format(count=3) + '</span>',
                    '<span>' + self.locales['af']['ui']['author_total_articles'].format(count=30) + '</span>')
        self.mutate(route, '<span>' + self.locales['af']['ui']['author_available_articles'].format(count=2) + '</span>',
                    '<span>' + self.locales['af']['ui']['author_available_articles'].format(count=20) + '</span>')
        errors = self.errors()
        self.assertEqual(sum(route in error and 'count disagrees' in error for error in errors), 2)

    def test_detects_wrong_author_article_at_valid_category_address(self):
        route = self.routes['authors']['en'][COAUTHOR]
        expected = self.routes['articles']['en'][uuid_for(2)]
        wrong = self.routes['articles']['en'][uuid_for(3)]
        self.mutate(route, f'<h2><a href="{expected}">', f'<h2><a href="{wrong}">')
        self.assert_error('author article inventory/order or canonical category links differ')

    def test_detects_repeated_work_even_when_links_resolve(self):
        route = self.routes['authors']['en'][PRIMARY]
        first = self.routes['articles']['en'][uuid_for(4)]
        second = self.routes['articles']['en'][uuid_for(2)]
        self.mutate(route, f'<h2><a href="{second}">', f'<h2><a href="{first}">')
        self.assert_error('author article inventory/order or canonical category links differ')

    def test_detects_missing_historical_context_for_author_details(self):
        route = self.routes['authors']['en'][PRIMARY]
        self.mutate(route, self.locales['en']['ui']['author_recorded_details'], 'Current personal details')
        self.assert_error('author details lack their historical-publication label')

    def test_detects_removed_recorded_author_detail(self):
        route = self.routes['authors']['en'][PRIMARY]
        self.mutate(route, '<bdi>Old Town</bdi>', '<bdi>Another Place</bdi>')
        self.assert_error('recorded author detail location is missing or relabeled')

    def test_detects_wrong_english_shortcut_for_empty_translation(self):
        route = self.routes['authors']['fr'][PRIMARY]
        self.mutate(route, f'class="button" href="{self.routes["authors"]["en"][PRIMARY]}"',
                    f'class="button" href="{self.routes["authors"]["en"][COAUTHOR]}"')
        self.assert_error('empty author profile lacks a localized notice or English author shortcut')

    def test_detects_missing_shared_navigation_even_on_unrelated_page(self):
        self.mutate('/en/search/', '<a href="/en/authors/">Authors</a>', '<a href="/en/articles/">Articles</a>')
        self.assert_error('shared navigation is missing the Authors directory')

    def test_detects_untranslated_authors_navigation(self):
        self.mutate('/fr/search/', '<a href="/fr/authors/">Auteurs</a>', '<a href="/fr/authors/">Authors</a>')
        self.assert_error('Authors navigation label is not localized')

    def test_detects_wrong_original_contributor_link_on_article(self):
        article = self.routes['articles']['en'][uuid_for(1)]
        self.mutate(article, f'class="author-link" href="{self.routes["authors"]["en"][PRIMARY]}"',
                    f'class="author-link" href="{self.routes["authors"]["en"][VARIANT]}"')
        self.assert_error('author byline links do not match the original named contributors')

    def test_detects_search_links_to_another_author_or_language(self):
        path = self.output / 'af/search-index.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        for wrong in (self.routes['authors']['af'][VARIANT], self.routes['authors']['en'][PRIMARY]):
            with self.subTest(destination=wrong):
                records = json.loads(json.dumps(original))
                record = next(row for row in records if row['id'] == uuid_for(1))
                record['authors'][0]['url'] = wrong
                payload = json.dumps(records, ensure_ascii=False).encode('utf-8')
                path.write_bytes(payload)
                path.with_suffix('.json.gz').write_bytes(gzip.compress(payload, mtime=0))
                self.assert_error('search author links differ from original contributors or canonical author routes')

    def test_detects_missing_search_contributor_and_fabricated_raw_credit_author(self):
        path = self.output / 'en/search-index.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        for identity, authors in ((uuid_for(2), []),
                                  (uuid_for(5), [{'name': PRIMARY, 'url': self.routes['authors']['en'][PRIMARY]}])):
            with self.subTest(article=identity):
                records = json.loads(json.dumps(original))
                next(row for row in records if row['id'] == identity)['authors'] = authors
                payload = json.dumps(records, ensure_ascii=False).encode('utf-8')
                path.write_bytes(payload)
                path.with_suffix('.json.gz').write_bytes(gzip.compress(payload, mtime=0))
                self.assert_error('search author links differ from original contributors or canonical author routes')

    def test_detects_wrong_paginated_article_and_author_language_identity(self):
        self.model, self.locales, self.routes, self.theme, self.output = author_site_fixture(self.root / 'pagination', count=29)
        route = self.routes['authors']['en'][PRIMARY] + 'page/2/'
        self.assertEqual(self.errors(), [])
        self.mutate(route, f'<h2><a href="{self.routes["articles"]["en"][uuid_for(4)]}">',
                    f'<h2><a href="{self.routes["articles"]["en"][uuid_for(28)]}">')
        expected = self.routes['authors']['fr'][PRIMARY]
        wrong = self.routes['authors']['fr'][COAUTHOR]
        self.mutate(route, f'value="{expected}" data-locale="fr"', f'value="{wrong}" data-locale="fr"')
        errors = self.errors()
        self.assertTrue(any('author article inventory/order' in error for error in errors), errors)
        self.assertTrue(any('author language selector changes identity' in error for error in errors), errors)

    def test_detects_extra_unregistered_author_profile(self):
        source = self.page_path(self.routes['authors']['en'][PRIMARY])
        extra = self.page_path('/en/authors/invented-person/')
        extra.parent.mkdir(parents=True)
        extra.write_text(source.read_text(encoding='utf-8'), encoding='utf-8')
        self.assert_error('unexpected author directory/profile or pagination page')


if __name__ == '__main__':
    unittest.main()
