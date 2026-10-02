import copy
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import quote

from scripts.routes import RouteError, initialize_routes, set_article_alias, slugify

A = '00000000-0000-4000-8000-000000000001'
B = '00000000-0000-4000-8000-000000000002'
C = '00000000-0000-4000-8000-000000000003'
D = '00000000-0000-4000-8000-000000000004'
I = '00000000-0000-4000-8000-000000000005'
J = '00000000-0000-4000-8000-000000000006'
E = '00000000-0000-4000-8000-000000000007'


def model():
    return {'articles': {'en': [{'id': A, 'title': 'A faithful life', 'categories': {'primary': C}}]},
            'categories': [{'id': C, 'slug': 'faith'}, {'id': D, 'slug': 'prayer'}],
            'issues': [{'id': I, 'slug': 'spring-2024'}]}


class RoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'routes.json'
        self.model = model()
        self.config = {'en': {}, 'af': {'categories': {C: {'slug': 'geloof'}, D: {'slug': 'gebed'}}},
                       'de': {'categories': {C: {'slug': 'glaube'}, D: {'slug': 'gebet'}}}}

    def tearDown(self):
        self.temp.cleanup()

    def translate(self, tag, title='A translated title', identity=A):
        original = next(article for article in self.model['articles']['en'] if article['id'] == identity)
        article = copy.deepcopy(original)
        article['title'] = title
        self.model['articles'].setdefault(tag, []).append(article)
        return article

    def save(self, registry):
        self.path.write_text(json.dumps(registry), encoding='utf-8')

    def assert_no_uuid_canonicals(self, routes):
        for kind in ('articles', 'categories', 'issues'):
            for values in routes[kind].values():
                for path in values.values():
                    for identity in (A, B, C, D, E, I, J):
                        self.assertNotIn(identity, path)

    def test_bootstrap_is_persisted_and_title_category_changes_do_not_break_links(self):
        self.translate('af', 'Die getroue lewe')
        routes = initialize_routes(self.model, self.config, self.path, update=True)
        self.assertEqual(routes['articles']['en'][A], '/en/faith/a-faithful-life/')
        self.assertEqual(routes['articles']['af'][A], '/af/geloof/die-getroue-lewe/')
        self.model['articles']['en'][0]['title'] = 'Corrected title'
        self.model['articles']['en'][0]['categories']['primary'] = D
        self.model['articles']['af'][0]['title'] = 'Gewysigde titel'
        self.model['articles']['af'][0]['categories']['primary'] = D
        rerun = initialize_routes(self.model, self.config, self.path)
        self.assertEqual(rerun['articles'], routes['articles'])
        self.assertEqual(self.model['articles']['en'][0]['markdown_url'], '/en/faith/a-faithful-life.md')

    def test_normal_build_allocates_readable_alias_without_writing_checkout(self):
        self.translate('af', 'Die getroue lewe')
        routes = initialize_routes(self.model, self.config, self.path)
        self.assertFalse(self.path.exists())
        self.assertEqual(routes['articles']['en'][A], '/en/faith/a-faithful-life/')
        self.assertEqual(routes['articles']['af'][A], '/af/geloof/die-getroue-lewe/')
        self.assertFalse(routes['registry']['articles']['af'][A]['fallback'])
        self.assertEqual(routes['redirects'][f'/af/geloof/article-{A}/'], routes['articles']['af'][A])
        self.assertNotIn(f'/de/geloof/article-{A}/', routes['redirects'])
        self.assertEqual(routes['legacy_aliases'][f'/geloof/article-{A}/'], {'kind': 'articles', 'id': A})
        self.assert_no_uuid_canonicals(routes)
        # Save the returned deployment registry to make the aliases permanent.
        self.save(routes['registry'])
        self.model['articles']['af'][0]['title'] = 'Gewysigde titel'
        self.assertEqual(initialize_routes(self.model, self.config, self.path)['articles'], routes['articles'])

    def test_prefix_replacement_redirects_both_category_and_article_in_one_step(self):
        self.translate('af', 'Die getroue lewe')
        self.translate('de', 'Ein treues Leben')
        routes = initialize_routes(self.model, self.config, self.path)
        for source_tag in self.config:
            for target_tag in self.config:
                for kind, identity in (('articles', A), ('categories', C), ('issues', I)):
                    canonical = routes[kind][source_tag][identity]
                    replacement = '/' + target_tag + '/' + canonical.split('/', 2)[2]
                    target = routes[kind][target_tag][identity]
                    if replacement != target:
                        self.assertEqual(routes['redirects'][replacement], target)
                        self.assertNotIn(target, routes['redirects'])

    def test_english_first_even_when_locale_configuration_starts_with_translation(self):
        self.translate('af', 'Die getroue lewe')
        config = {'af': self.config['af'], 'de': self.config['de'], 'en': {}}
        routes = initialize_routes(self.model, config, self.path)
        self.assertEqual(routes['articles']['de'][A], '/de/articles/a-faithful-life/')
        self.assertEqual(routes['redirects']['/de/geloof/die-getroue-lewe/'], routes['articles']['de'][A])

    def test_missing_translation_has_readable_availability_path_and_is_promoted(self):
        routes = initialize_routes(self.model, self.config, self.path, update=True)
        missing = routes['articles']['af'][A]
        self.assertEqual(missing, '/af/articles/a-faithful-life/')
        self.assertEqual(routes['articles']['de'][A], '/de/articles/a-faithful-life/')
        self.assertEqual(routes['registry']['articles']['af'][A]['category_id'], C)
        self.assertTrue(routes['registry']['articles']['af'][A]['placeholder'])
        self.assertNotIn('af', self.model['articles'])
        self.assertEqual(routes['redirects']['/af/faith/a-faithful-life/'], missing)
        self.translate('af', 'Die getroue lewe')
        ready = initialize_routes(self.model, self.config, self.path, update=True)
        self.assertEqual(ready['articles']['af'][A], '/af/geloof/die-getroue-lewe/')
        self.assertNotIn('placeholder', ready['registry']['articles']['af'][A])
        self.assertEqual(ready['redirects'][missing], ready['articles']['af'][A])
        self.assertEqual(ready['redirects']['/de/geloof/die-getroue-lewe/'], ready['articles']['de'][A])

    def test_existing_category_placeholder_moves_to_shared_tail_with_history(self):
        routes = initialize_routes(self.model, self.config, self.path)
        record = routes['registry']['articles']['af'][A]
        record['category_slug'] = 'geloof'
        old = '/af/geloof/' + record['alias'] + '/'
        self.save(routes['registry'])
        migrated = initialize_routes(self.model, self.config, self.path, update=True)
        self.assertEqual(migrated['articles']['af'][A], '/af/articles/a-faithful-life/')
        self.assertIn(old, migrated['registry']['articles']['af'][A]['history'])
        self.assertEqual(migrated['redirects'][old], migrated['articles']['af'][A])
        self.translate('af', 'Die getroue lewe')
        published = initialize_routes(self.model, self.config, self.path)
        self.assertEqual(published['articles']['af'][A], '/af/geloof/die-getroue-lewe/')
        self.assertEqual(published['redirects'][old], published['articles']['af'][A])
        self.assertEqual(published['redirects']['/af/articles/a-faithful-life/'], published['articles']['af'][A])

    def test_legacy_paths_are_static_only_in_source_locales_but_all_have_lookup_metadata(self):
        self.translate('af', 'Die getroue lewe')
        routes = initialize_routes(self.model, self.config, self.path)
        legacy = f'/geloof/article-{A}/'
        self.assertEqual(routes['redirects']['/af' + legacy], routes['articles']['af'][A])
        self.assertNotIn('/de' + legacy, routes['redirects'])
        self.assertEqual(routes['legacy_aliases'][legacy], {'kind': 'articles', 'id': A})
        self.assertEqual(routes['cross_locale_aliases'][legacy], {'kind': 'articles', 'id': A})
        # The old UUID-only route actually existed in every locale, so each has
        # its own direct static redirect without needing the runtime fallback.
        for tag in self.config:
            self.assertEqual(routes['redirects'][f'/{tag}/articles/{A}/'], routes['articles'][tag][A])
        self.assertEqual(routes['redirects']['/de/geloof/die-getroue-lewe/'], routes['articles']['de'][A])

    def test_localized_categories_are_frozen_by_identity(self):
        config = {'en': {}, 'zh-Hans': {'categories': {C: {'slug': '信仰'}}}}
        routes = initialize_routes(self.model, config, self.path, update=True)
        self.assertEqual(routes['categories']['zh-Hans'][C], '/zh-Hans/信仰/')
        config['zh-Hans']['categories'][C]['slug'] = '新的标题'
        self.assertEqual(initialize_routes(self.model, config, self.path)['categories']['zh-Hans'][C], '/zh-Hans/信仰/')

    def test_article_collisions_use_incrementing_suffix_and_do_not_renumber(self):
        self.model['articles']['en'].append({'id': B, 'title': 'A faithful life', 'categories': {'primary': C}})
        self.model['articles']['en'].append({'id': E, 'title': 'A faithful life', 'categories': {'primary': C}})
        routes = initialize_routes(self.model, ['en'], self.path, update=True)
        self.assertEqual(routes['articles']['en'][A], '/en/faith/a-faithful-life/')
        self.assertEqual(routes['articles']['en'][B], '/en/faith/a-faithful-life-2/')
        self.assertEqual(routes['articles']['en'][E], '/en/faith/a-faithful-life-3/')
        self.model['articles']['en'].pop(1)
        rerun = initialize_routes(self.model, ['en'], self.path)
        self.assertEqual(rerun['articles']['en'][E], routes['articles']['en'][E])
        self.assert_no_uuid_canonicals(rerun)

    def test_collisions_skip_reserved_retired_routes_and_history(self):
        routes = initialize_routes(self.model, ['en'], self.path, update=True)
        set_article_alias(routes['registry'], 'en', A, 'updated-alias')
        self.save(routes['registry'])
        self.model['articles']['en'] = [{'id': B, 'title': 'A faithful life', 'categories': {'primary': C}}]
        changed = initialize_routes(self.model, ['en'], self.path)
        self.assertEqual(changed['articles']['en'][B], '/en/faith/a-faithful-life-2/')
        self.assertNotIn('/en/faith/a-faithful-life/', changed['redirects'])

    def test_category_and_issue_collisions_use_numbers_without_uuid(self):
        self.model['categories'][1]['slug'] = 'faith'
        self.model['issues'].append({'id': J, 'slug': 'spring-2024'})
        routes = initialize_routes(self.model, ['en'], self.path)
        self.assertEqual(routes['categories']['en'][D], '/en/faith-2/')
        self.assertEqual(routes['issues']['en'][J], '/en/issues/spring-2024-2/')
        self.assert_no_uuid_canonicals(routes)

    def test_missing_titles_use_locale_title_and_safe_numeric_disambiguation(self):
        self.model['articles']['en'][0]['title'] = None
        self.model['articles']['en'].append({'id': B, 'title': None, 'categories': {'primary': C}})
        self.translate('af', None)
        self.config['af']['ui'] = {'untitled_article': 'Artikel sonder titel'}
        routes = initialize_routes(self.model, self.config, self.path)
        self.assertEqual(routes['articles']['en'][A], '/en/faith/article/')
        self.assertEqual(routes['articles']['en'][B], '/en/faith/article-2/')
        self.assertEqual(routes['articles']['af'][A], '/af/geloof/artikel-sonder-titel/')
        self.assert_no_uuid_canonicals(routes)

    def test_reserved_namespaces_and_unicode(self):
        self.model['categories'][0]['slug'] = 'issues'
        result = initialize_routes(self.model, ['en'], self.path)
        self.assertEqual(result['categories']['en'][C], '/en/category-issues/')
        self.assertEqual(slugify('信仰：生命'), '信仰-生命')
        self.assertEqual(slugify('  ŉ nuwe lewe!  '), 'ʼn-nuwe-lewe')

    def test_unicode_encoded_historical_path_is_matched_without_duplicate_owner(self):
        config = {'en': {}, 'zh-Hans': {'categories': {C: {'slug': '信仰'}}}}
        self.translate('zh-Hans', '信仰的生命')
        routes = initialize_routes(self.model, config, self.path, update=True)
        canonical = routes['articles']['zh-Hans'][A]
        encoded = quote(canonical, safe='/')
        routes['registry']['articles']['zh-Hans'][A]['history'] = [encoded]
        self.save(routes['registry'])
        ready = initialize_routes(self.model, config, self.path)
        self.assertEqual(ready['redirects']['/en/' + encoded.split('/', 2)[2]], routes['articles']['en'][A])

    def test_uuid_fallback_migration_preserves_category_moves_and_legacy_links(self):
        routes = initialize_routes(self.model, self.config, self.path)
        registry = routes['registry']
        registry['articles']['en'][A].update(alias='article-' + A, fallback=True)
        self.save(registry)
        self.model['articles']['en'][0]['categories']['primary'] = D
        migrated = initialize_routes(self.model, self.config, self.path)
        canonical = '/en/faith/a-faithful-life/'
        self.assertEqual(migrated['articles']['en'][A], canonical)
        for slug in ('faith', 'prayer'):
            self.assertEqual(migrated['redirects'][f'/en/{slug}/article-{A}/'], canonical)
            self.assertNotIn(f'/af/{slug}/article-{A}/', migrated['redirects'])
            self.assertEqual(migrated['legacy_aliases'][f'/{slug}/article-{A}/'], {'kind': 'articles', 'id': A})
            self.assertEqual(migrated['cross_locale_aliases'][f'/{slug}/article-{A}/'], {'kind': 'articles', 'id': A})
        self.assertEqual(migrated['redirects'][f'/en/articles/{A}/'], canonical)
        self.assert_no_uuid_canonicals(migrated)

    def test_legacy_uuid_suffix_and_category_uuid_migration_are_readable(self):
        routes = initialize_routes(self.model, self.config, self.path)
        registry = routes['registry']
        registry['categories']['en'][C]['slug'] = 'faith-' + C
        registry['articles']['en'][A].update(alias='a-faithful-life-' + A, category_slug='faith-' + C)
        old = f'/en/faith-{C}/a-faithful-life-{A}/'
        self.save(registry)
        migrated = initialize_routes(self.model, self.config, self.path)
        self.assertEqual(migrated['categories']['en'][C], '/en/faith/')
        self.assertEqual(migrated['articles']['en'][A], '/en/faith/a-faithful-life/')
        self.assertEqual(migrated['redirects'][old], migrated['articles']['en'][A])
        self.assertNotIn(old.replace('/en/', '/af/', 1), migrated['redirects'])
        self.assertEqual(migrated['legacy_aliases']['/' + old.split('/', 2)[2]], {'kind': 'articles', 'id': A})
        self.assertEqual(migrated['redirects'][f'/en/faith-{C}/'], '/en/faith/')
        self.assertEqual(migrated['legacy_aliases'][f'/faith-{C}/'], {'kind': 'categories', 'id': C})
        self.assert_no_uuid_canonicals(migrated)

    def test_explicit_alias_and_category_migration_preserve_cross_language_history(self):
        self.translate('af', 'Die getroue lewe')
        routes = initialize_routes(self.model, self.config, self.path, update=True)
        old = routes['articles']['en'][A]
        registry = routes['registry']
        set_article_alias(registry, 'en', A, 'deliberate-new-alias', 'prayer')
        old_category = registry['categories']['af'][C]['slug']
        registry['categories']['af'][C].update(slug='geloofslewe', history=['/af/' + old_category + '/'])
        self.save(registry)
        changed = initialize_routes(self.model, self.config, self.path)
        self.assertEqual(changed['redirects'][old], '/en/prayer/deliberate-new-alias/')
        self.assertEqual(changed['redirects'][old.replace('/en/', '/af/', 1)], changed['articles']['af'][A])
        self.assertEqual(changed['redirects']['/de/geloof/'], changed['categories']['de'][C])

    def test_editorial_alias_migration_rejects_public_uuid(self):
        routes = initialize_routes(self.model, ['en'], self.path)
        with self.assertRaisesRegex(RouteError, 'UUIDs'):
            set_article_alias(routes['registry'], 'en', A, 'article-' + A)

    def test_manually_edited_local_collision_fails_before_write(self):
        self.model['articles']['en'].append({'id': B, 'title': 'Other', 'categories': {'primary': C}})
        result = initialize_routes(self.model, ['en'], self.path, update=True)
        result['registry']['articles']['en'][B]['alias'] = 'a-faithful-life'
        self.save(result['registry'])
        prior = self.path.read_bytes()
        with self.assertRaisesRegex(RouteError, 'collision'):
            initialize_routes(self.model, ['en'], self.path, update=True)
        self.assertEqual(self.path.read_bytes(), prior)

    def test_existing_cross_locale_tail_ambiguity_fails_clearly(self):
        self.model['articles']['en'].append({'id': B, 'title': 'Other', 'categories': {'primary': C}})
        self.translate('af', 'Eerste artikel', A)
        self.translate('af', 'Die getroue lewe', B)
        self.config['af']['categories'][C]['slug'] = 'faith'
        result = initialize_routes(self.model, self.config, self.path)
        # Article B in Afrikaans claims the frozen English address of article A.
        result['registry']['articles']['af'][B]['alias'] = 'a-faithful-life'
        self.save(result['registry'])
        with self.assertRaisesRegex(RouteError, 'Ambiguous language-prefix alias'):
            initialize_routes(self.model, self.config, self.path)

    def test_new_cross_locale_tail_collision_allocates_numeric_suffix(self):
        self.model['articles']['en'].append({'id': B, 'title': 'Other', 'categories': {'primary': C}})
        self.translate('af', 'A faithful life', B)
        self.config['af']['categories'][C]['slug'] = 'faith'
        result = initialize_routes(self.model, self.config, self.path)
        self.assertEqual(result['articles']['af'][B], '/af/faith/a-faithful-life-2/')
        self.assertEqual(result['redirects']['/en/faith/a-faithful-life-2/'], result['articles']['en'][B])

    def test_issue_and_category_paths_do_not_collide(self):
        self.model['categories'][0]['slug'] = 'spring-2024'
        result = initialize_routes(self.model, ['en'], self.path)
        self.assertEqual(result['categories']['en'][C], '/en/spring-2024/')
        self.assertEqual(result['issues']['en'][I], '/en/issues/spring-2024/')

    def test_unknown_exported_locale_and_orphan_translation_are_rejected(self):
        self.model['articles']['zz'] = []
        with self.assertRaisesRegex(RouteError, 'not configured'):
            initialize_routes(self.model, ['en'], self.path)
        self.model['articles'].pop('zz')
        self.model['articles']['af'] = [{'id': B, 'title': 'Orphan', 'categories': {'primary': C}}]
        with self.assertRaisesRegex(RouteError, 'no English identity'):
            initialize_routes(self.model, self.config, self.path)

    def test_unsafe_encoded_history_is_rejected(self):
        result = initialize_routes(self.model, ['en'], self.path)
        for path in ('/en/faith/%2e%2e/', '/en/faith/%5c/', '/en/faith/%3f/', '/en//broken/'):
            result['registry']['articles']['en'][A]['history'] = [path]
            self.save(result['registry'])
            with self.assertRaisesRegex(RouteError, 'Unsafe redirect history'):
                initialize_routes(self.model, ['en'], self.path)


if __name__ == '__main__':
    unittest.main()
