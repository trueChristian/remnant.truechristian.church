"""Reviewed author merges must retain durable readable paths and redirects."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.route_registry import RegistryError, merge_registries, migrate_author_registry, prepare_registry, validate_registry
from scripts.routes import RouteError, UUID_PATTERN, author_url, initialize_routes

A = '00000000-0000-4000-8000-000000000001'
B = '00000000-0000-4000-8000-000000000002'
C = '00000000-0000-4000-8000-000000000003'


def model(names=('John Smith',)):
    return {
        'articles': {'en': [{'id': A, 'title': 'Faithful life',
                            'categories': {'primary': C},
                            'byline': {'authors': [{'name': name} for name in names]}}]},
        'categories': [{'id': C, 'slug': 'faith'}], 'issues': [],
    }


def empty_registry():
    return {'version': 1, 'categories': {}, 'issues': {}, 'articles': {}}


class AuthorRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'routes.json'

    def save(self, registry):
        self.path.write_text(json.dumps(registry), encoding='utf-8')

    def test_names_are_readable_in_all_locales_and_do_not_change_article_routes(self):
        source = model()
        routes = initialize_routes(source, ['af', 'en', 'ar'], self.path)
        for tag in ('en', 'af', 'ar'):
            self.assertEqual(author_url(routes, tag, 'John Smith'), f'/{tag}/authors/john-smith/')
            self.assertFalse(UUID_PATTERN.search(author_url(routes, tag, 'John Smith')))
        self.assertEqual(source['articles']['en'][0]['url'], '/en/faith/faithful-life/')
        self.assertNotIn('authors', source)
        self.assertFalse(self.path.exists())
        self.assertEqual(routes['cross_locale_aliases']['/authors/john-smith/'],
                         {'kind': 'authors', 'id': 'John Smith'})
        validate_registry(routes['registry'])

    def test_exact_spelling_variants_get_distinct_deterministic_numeric_aliases(self):
        names = ['John Smith', 'John  Smith', 'john smith', 'John-Smith']
        first = initialize_routes(model(names), ['en', 'af'], self.path)
        second = initialize_routes(model(list(reversed(names))), ['en', 'af'], self.path)
        self.assertEqual(first['authors'], second['authors'])
        self.assertEqual(set(first['authors']['en']), set(names))
        self.assertEqual(set(first['authors']['en'].values()), {
            '/en/authors/john-smith/', '/en/authors/john-smith-2/',
            '/en/authors/john-smith-3/', '/en/authors/john-smith-4/',
        })
        for name in names:
            self.assertEqual(first['authors']['af'][name], first['authors']['en'][name].replace('/en/', '/af/', 1))

    def test_durable_published_aliases_survive_new_collision_and_source_reordering(self):
        self.save(empty_registry())
        published = initialize_routes(model(['John Smith']), ['en', 'af'], self.path)
        snapshot = self.path.parent / 'prepared.json'
        report = prepare_registry(self.path, snapshot, published=published['registry'])
        self.assertEqual(report['counts']['authors'], 2)
        self.assertNotIn('authors', json.loads(self.path.read_text()))
        added = initialize_routes(model(['John  Smith', 'John Smith']), ['en', 'af'], snapshot)
        self.assertEqual(added['authors']['en']['John Smith'], '/en/authors/john-smith/')
        self.assertEqual(added['authors']['en']['John  Smith'], '/en/authors/john-smith-2/')
        self.assertEqual(added['registry']['authors']['en']['John Smith']['slug'], 'john-smith')

    def test_update_persists_aliases_and_retired_names_reserve_old_paths(self):
        first = initialize_routes(model(['John Smith']), ['en', 'af'], self.path, update=True)
        self.assertEqual(json.loads(self.path.read_text())['authors'], first['registry']['authors'])
        next_build = initialize_routes(model(['john smith']), ['en', 'af'], self.path)
        self.assertNotIn('John Smith', next_build['authors']['en'])
        self.assertEqual(next_build['authors']['en']['john smith'], '/en/authors/john-smith-2/')
        self.assertIn('John Smith', next_build['registry']['authors']['en'])
        self.assertNotIn('/en/authors/john-smith/', next_build['redirects'])

    def test_editorial_history_redirects_in_every_language_and_new_locales_use_english_alias(self):
        original = initialize_routes(model(), ['en', 'af'], self.path)
        original['registry']['authors']['en']['John Smith'].update(
            slug='john-smith-author', history=['/en/authors/john-smith/'])
        original['registry']['authors']['af']['John Smith'].update(
            slug='john-smith-skrywer', history=['/af/authors/john-smith/'])
        self.save(original['registry'])
        routes = initialize_routes(model(), ['en', 'af', 'de'], self.path)
        self.assertEqual(routes['authors']['de']['John Smith'], '/de/authors/john-smith-author/')
        for tag in ('en', 'af', 'de'):
            for slug in ('john-smith', 'john-smith-author', 'john-smith-skrywer'):
                candidate = f'/{tag}/authors/{slug}/'
                canonical = routes['authors'][tag]['John Smith']
                if candidate != canonical:
                    self.assertEqual(routes['redirects'][candidate], canonical)
                    self.assertNotIn(canonical, routes['redirects'])

    def test_retired_history_is_never_allocated_to_new_author(self):
        first = initialize_routes(model(), ['en'], self.path)
        first['registry']['authors']['en']['John Smith'].update(
            slug='john-smith-renamed', history=['/en/authors/john-smith/'])
        self.save(first['registry'])
        next_build = initialize_routes(model(['JOHN SMITH']), ['en'], self.path)
        self.assertEqual(next_build['authors']['en']['JOHN SMITH'], '/en/authors/john-smith-2/')

    def test_uuid_text_punctuation_and_unicode_names_are_safe_readable_aliases(self):
        names = ['Author ' + A, A, '信仰作者', '!!!', 'Page']
        routes = initialize_routes(model(names), ['en', 'zh-Hans'], self.path)
        for tag, authors in routes['authors'].items():
            for path in authors.values():
                self.assertFalse(UUID_PATTERN.search(path))
                self.assertTrue(path.startswith(f'/{tag}/authors/'))
            self.assertEqual(authors['信仰作者'], f'/{tag}/authors/信仰作者/')
            self.assertEqual(authors['Page'], f'/{tag}/authors/author-page/')

    def test_authors_namespace_cannot_be_a_category(self):
        source = model()
        source['categories'][0]['slug'] = 'authors'
        routes = initialize_routes(source, ['en'], self.path)
        self.assertEqual(routes['categories']['en'][C], '/en/category-authors/')

    def test_translated_bylines_do_not_create_author_route_identities(self):
        source = model()
        source['articles']['af'] = copy.deepcopy(source['articles']['en'])
        source['articles']['af'][0]['byline']['authors'] = [{'name': 'Unrelated translation credit'}]
        routes = initialize_routes(source, ['en', 'af'], self.path)
        self.assertEqual(set(routes['authors']['af']), {'John Smith'})

    def test_malformed_author_records_fail_before_registry_write(self):
        first = initialize_routes(model(), ['en'], self.path)['registry']
        cases = [('', {'slug': 'person'}), (' ', {'slug': 'person'}),
                 ('Bad\nName', {'slug': 'person'}), ('x' * 1025, {'slug': 'person'}),
                 ('Name', {'slug': 'page'}), ('Name', {'slug': 'PAGE'}),
                 ('Name', {'slug': A}), ('Name', {'slug': '../bad'}),
                 ('Name', {'slug': 'safe', 'history': 'not-a-list'}),
                 ('Name', {'slug': 'safe', 'unknown': True})]
        for name, entry in cases:
            with self.subTest(name=name, entry=entry):
                bad = copy.deepcopy(first)
                bad['authors']['en'] = {name: entry}
                self.save(bad)
                before = self.path.read_bytes()
                with self.assertRaises(RouteError):
                    initialize_routes(model(), ['en'], self.path, update=True)
                self.assertEqual(self.path.read_bytes(), before)
                with self.assertRaises(RegistryError):
                    validate_registry(bad)

    def test_unsafe_author_history_is_rejected_by_runtime_and_durable_validation(self):
        first = initialize_routes(model(), ['en'], self.path)['registry']
        histories = ['/af/authors/old/', '/en/faith/old/', '/en/authors/page/',
                     '/en/authors/name/page/2/', '/en/authors/%2e%2e/',
                     '/en/authors/a%2fb/', '/en/authors/%255c/',
                     '/en/authors/%FF/', '/en/authors/bad%/', '/en/authors//']
        for path in histories:
            with self.subTest(path=path):
                bad = copy.deepcopy(first)
                bad['authors']['en']['John Smith']['history'] = [path]
                self.save(bad)
                with self.assertRaises(RouteError):
                    initialize_routes(model(), ['en'], self.path)
                with self.assertRaises(RegistryError):
                    validate_registry(bad)

    def test_encoded_unicode_history_is_retained_and_redirected(self):
        first = initialize_routes(model(['René']), ['en', 'af'], self.path)
        first['registry']['authors']['en']['René']['history'] = ['/en/authors/ren%C3%A9/']
        self.save(first['registry'])
        validate_registry(first['registry'])
        second = initialize_routes(model(['René']), ['en', 'af'], self.path)
        self.assertEqual(second['redirects']['/af/authors/ren%C3%A9/'], '/af/authors/rené/')

    def test_author_histories_do_not_enter_uuid_only_client_recovery_index(self):
        first = initialize_routes(model(), ['en', 'af'], self.path)
        first['registry']['authors']['en']['John Smith']['history'] = [f'/en/authors/{A}/']
        self.save(first['registry'])
        second = initialize_routes(model(), ['en', 'af'], self.path)
        for tag in ('en', 'af'):
            self.assertEqual(second['redirects'][f'/{tag}/authors/{A}/'],
                             f'/{tag}/authors/john-smith/')
        self.assertNotIn(f'/authors/{A}/', second['legacy_aliases'])


class DurableAuthorRegistryTests(unittest.TestCase):
    def test_old_v1_schema_remains_valid_and_unchanged(self):
        old = empty_registry()
        self.assertIs(validate_registry(old), old)
        self.assertEqual(merge_registries(old, old), old)
        self.assertEqual(merge_registries(old, None), old)

    def test_optional_author_map_merges_both_directions_without_losing_history(self):
        old = empty_registry()
        published = {**old, 'authors': {'en': {'John Smith': {
            'slug': 'john-smith', 'history': ['/en/authors/js/']}}}}
        self.assertEqual(merge_registries(old, published), published)
        self.assertEqual(merge_registries(published, old), published)
        edited = copy.deepcopy(published)
        edited['authors']['en']['John Smith'].update(slug='john-smith-author', history=[])
        merged = merge_registries(edited, published)
        self.assertEqual(merged['authors']['en']['John Smith'], {
            'slug': 'john-smith-author', 'history': ['/en/authors/john-smith/', '/en/authors/js/']})

    def test_durable_author_alias_cannot_be_reassigned_to_another_spelling(self):
        published = {**empty_registry(), 'authors': {'en': {'John Smith': {
            'slug': 'john-smith', 'history': []}}}}
        committed = copy.deepcopy(published)
        committed['authors']['en'] = {'john smith': {'slug': 'john-smith', 'history': []}}
        with self.assertRaisesRegex(RegistryError, 'collision'):
            merge_registries(committed, published)

    def test_optional_schema_rejects_unrecognized_kinds_or_wrong_map_types(self):
        for extra in ({'authors': None}, {'authors': []}, {'author': {}},
                      {'authors': {'en': []}}):
            with self.subTest(extra=extra), self.assertRaises(RegistryError):
                validate_registry({**empty_registry(), **extra})


class MergedAuthorRoutesTests(unittest.TestCase):
    aliases = {'A.W. Tozer': 'A. W. Tozer', 'A W Tozer': 'A. W. Tozer',
               'Unknown': 'Anonymous', 'anonymous': 'Anonymous',
               'Brother Dean': 'Dean Taylor',
               'George Bronk II': 'George R. Bronk II'}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'routes.json'

    def save(self, registry):
        self.path.write_text(json.dumps(registry), encoding='utf-8')

    def before_merge(self, names, locales=('en', 'af')):
        return initialize_routes(model(names), locales, self.path, author_aliases={})

    def after_merge(self, names, locales=('en', 'af')):
        return initialize_routes(model(names), locales, self.path, author_aliases=self.aliases)

    def test_existing_canonical_wins_and_every_old_path_redirects_in_all_locales(self):
        names = ['A.W. Tozer', 'A W Tozer', 'A. W. Tozer', 'Unknown', 'Anonymous']
        before = self.before_merge(names)
        before['registry']['authors']['af']['A.W. Tozer']['history'] = ['/af/authors/tozer-previous/']
        self.save(before['registry'])
        after = self.after_merge(names, ('en', 'af', 'ar'))
        for locale in ('en', 'af', 'ar'):
            self.assertEqual(set(after['authors'][locale]), {'A. W. Tozer', 'Anonymous'})
            for source_locale in ('en', 'af'):
                for name in names:
                    old = before['authors'][source_locale][name].replace(f'/{source_locale}/', f'/{locale}/', 1)
                    canonical = self.aliases.get(name, name)
                    new = after['authors'][locale][canonical]
                    if old != new:
                        self.assertEqual(after['redirects'][old], new)
                    self.assertEqual(author_url(after, locale, name), new)
            self.assertEqual(after['redirects'][f'/{locale}/authors/tozer-previous/'],
                             after['authors'][locale]['A. W. Tozer'])
        for locale in ('en', 'af'):
            self.assertEqual(after['authors'][locale]['A. W. Tozer'], before['authors'][locale]['A. W. Tozer'])
            self.assertEqual(after['articles'][locale], before['articles'][locale])
            self.assertEqual(after['registry']['articles'][locale], before['registry']['articles'][locale])
        self.assertEqual(after['cross_locale_aliases']['/authors/tozer-previous/'],
                         {'kind': 'authors', 'id': 'A. W. Tozer'})
        validate_registry(after['registry'])

    def test_canonical_without_an_existing_record_keeps_deterministic_member_route(self):
        before = self.before_merge(['A.W. Tozer', 'A W Tozer'])
        self.save(before['registry'])
        first = self.after_merge(['A.W. Tozer', 'A W Tozer'])
        second = self.after_merge(['A W Tozer', 'A.W. Tozer'])
        self.assertEqual(first['registry'], second['registry'])
        for locale in ('en', 'af'):
            self.assertEqual(first['authors'][locale]['A. W. Tozer'], before['authors'][locale]['A W Tozer'])
            self.assertEqual(first['redirects'][before['authors'][locale]['A.W. Tozer']],
                             first['authors'][locale]['A. W. Tozer'])

    def test_repeated_builds_keep_canonical_history_and_never_recreate_alias_identities(self):
        names = ['Dean Taylor', 'Brother Dean']
        before = self.before_merge(names)
        self.save(before['registry'])
        first = self.after_merge(names)
        self.save(first['registry'])
        # The canonical spelling can disappear from content without changing
        # the published identity or URL of its remaining recorded spelling.
        second = self.after_merge(['Brother Dean'])
        self.assertEqual(first['authors'], second['authors'])
        self.assertEqual(first['registry'], second['registry'])
        self.assertEqual(second['redirects']['/en/authors/brother-dean/'], '/en/authors/dean-taylor/')

    def test_retired_merged_addresses_remain_reserved_and_unrelated_names_stay_distinct(self):
        before = self.before_merge(['Dean Taylor', 'Brother Dean', 'George Bronk II',
                                    'George R. Bronk II', 'George R. Bronk Sr.'])
        self.save(before['registry'])
        after = self.after_merge(['BROTHER DEAN', 'George Bronk II', 'George R. Bronk Sr.'])
        self.assertEqual(set(after['authors']['en']),
                         {'BROTHER DEAN', 'George R. Bronk II', 'George R. Bronk Sr.'})
        self.assertEqual(after['authors']['en']['BROTHER DEAN'], '/en/authors/brother-dean-2/')
        self.assertNotIn('/en/authors/brother-dean/', after['redirects'])
        self.assertEqual(after['registry']['authors']['en']['Dean Taylor']['history'], ['/en/authors/brother-dean/'])
        self.assertEqual(after['redirects']['/en/authors/george-bronk-ii/'], '/en/authors/george-r-bronk-ii/')
        self.assertEqual(after['authors']['en']['George R. Bronk Sr.'], '/en/authors/george-r-bronk-sr/')

    def test_migration_is_copy_only_and_rejects_conflicting_or_malformed_old_records(self):
        before = self.before_merge(['A.W. Tozer', 'A. W. Tozer'])['registry']
        snapshot = copy.deepcopy(before)
        migrated = migrate_author_registry(before, self.aliases)
        self.assertEqual(before, snapshot)
        self.assertEqual(set(migrated['authors']['en']), {'A. W. Tozer'})
        for corruption in ({'slug': 'a-w-tozer'}, {'slug': 'page'},
                           {'slug': 'safe', 'history': ['/en/authors/name/page/2/']}):
            bad = copy.deepcopy(before)
            bad['authors']['en']['A.W. Tozer'] = corruption
            with self.subTest(corruption=corruption), self.assertRaises(RegistryError):
                migrate_author_registry(bad, self.aliases)

    def test_stale_committed_aliases_do_not_revert_published_canonical_route(self):
        old = self.before_merge(['A.W. Tozer'])['registry']
        published = self.before_merge(['A. W. Tozer', 'A.W. Tozer'])['registry']
        published = migrate_author_registry(published, self.aliases)
        for locale in ('en', 'af'):
            published['authors'][locale]['A. W. Tozer'].update(
                slug='tozer-author', history=[f'/{locale}/authors/a-w-tozer/', f'/{locale}/authors/a-w-tozer-2/'])
        merged = merge_registries(old, published, author_aliases=self.aliases)
        for locale in ('en', 'af'):
            self.assertEqual(set(merged['authors'][locale]), {'A. W. Tozer'})
            self.assertEqual(merged['authors'][locale]['A. W. Tozer']['slug'], 'tozer-author')
            self.assertEqual(merged['authors'][locale]['A. W. Tozer']['history'],
                             [f'/{locale}/authors/a-w-tozer-2/', f'/{locale}/authors/a-w-tozer/'])
        self.assertEqual(merge_registries(old, merged, author_aliases=self.aliases), merged)
        self.assertEqual(merge_registries(merged, old, author_aliases=self.aliases), merged)

    def test_committed_canonical_edit_merges_published_old_identities_without_collisions(self):
        old = self.before_merge(['A.W. Tozer', 'A. W. Tozer'])['registry']
        committed = copy.deepcopy(old)
        for locale in ('en', 'af'):
            committed['authors'][locale] = {'A. W. Tozer': {'slug': 'tozer-reviewed', 'history': []}}
        merged = merge_registries(committed, old, author_aliases=self.aliases)
        for locale in ('en', 'af'):
            self.assertEqual(merged['authors'][locale]['A. W. Tozer'], {
                'slug': 'tozer-reviewed',
                'history': [f'/{locale}/authors/a-w-tozer-2/', f'/{locale}/authors/a-w-tozer/']})


if __name__ == '__main__':
    unittest.main()
