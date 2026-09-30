import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.routes import RouteError, initialize_routes, set_article_alias, slugify

A = '00000000-0000-4000-8000-000000000001'
B = '00000000-0000-4000-8000-000000000002'
C = '00000000-0000-4000-8000-000000000003'
D = '00000000-0000-4000-8000-000000000004'
I = '00000000-0000-4000-8000-000000000005'


def model():
    return {'articles': {'en': [{'id': A, 'title': 'A faithful life', 'categories': {'primary': C}}]}, 'categories': [{'id': C, 'slug': 'faith'}, {'id': D, 'slug': 'prayer'}], 'issues': [{'id': I, 'slug': 'spring-2024'}]}


class RoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'routes.json'
        self.model = model()

    def tearDown(self):
        self.temp.cleanup()

    def test_bootstrap_is_persisted_and_title_changes_do_not_break_links(self):
        routes = initialize_routes(self.model, ['en'], self.path, update=True)
        original = routes['articles']['en'][A]
        self.assertEqual(original, '/en/faith/a-faithful-life/')
        self.model['articles']['en'][0]['title'] = 'Corrected title'
        self.model['articles']['en'][0]['categories']['primary'] = D
        rerun = initialize_routes(self.model, ['en'], self.path)
        self.assertEqual(rerun['articles']['en'][A], original)
        self.assertEqual(rerun['redirects'][f'/en/articles/{A}/'], original)
        self.assertEqual(self.model['articles']['en'][0]['markdown_url'], f'/en/articles/{A}.md')

    def test_unregistered_uuid_fallback_survives_title_and_category_change(self):
        first = initialize_routes(self.model, ['en'], self.path)
        old = first['articles']['en'][A]
        self.assertFalse(self.path.exists())
        self.model['articles']['en'][0]['title'] = 'New title'
        self.model['articles']['en'][0]['categories']['primary'] = D
        second = initialize_routes(self.model, ['en'], self.path)
        self.assertEqual(second['redirects'][old], second['articles']['en'][A])
        self.assertTrue(second['articles']['en'][A].endswith(f'article-{A}/'))

    def test_localized_categories_are_frozen_by_uuid(self):
        config = {'en': {}, 'zh-Hans': {'categories': {C: {'slug': '信仰'}}}}
        routes = initialize_routes(self.model, config, self.path, update=True)
        self.assertEqual(routes['categories']['zh-Hans'][C], '/zh-Hans/信仰/')
        config['zh-Hans']['categories'][C]['slug'] = '新的标题'
        self.assertEqual(initialize_routes(self.model, config, self.path)['categories']['zh-Hans'][C], '/zh-Hans/信仰/')

    def test_collision_resolution_and_missing_title(self):
        self.model['articles']['en'] += [{'id': B, 'title': 'A faithful life', 'categories': {'primary': C}}]
        routes = initialize_routes(self.model, ['en'], self.path, update=True)
        self.assertNotEqual(routes['articles']['en'][A], routes['articles']['en'][B])
        self.assertIn(B, routes['articles']['en'][B])
        self.model['articles']['en'][0]['title'] = None
        fresh = initialize_routes(self.model, ['en'], self.path.parent / 'fresh.json', update=True)
        self.assertEqual(fresh['articles']['en'][A], '/en/faith/article/')

    def test_reserved_namespaces_and_unicode(self):
        self.model['categories'][0]['slug'] = 'issues'
        result = initialize_routes(self.model, ['en'], self.path)
        self.assertEqual(result['categories']['en'][C], '/en/category-issues/')
        self.assertEqual(slugify('信仰：生命'), '信仰-生命')
        self.assertEqual(slugify('  ŉ nuwe lewe!  '), 'ʼn-nuwe-lewe')

    def test_explicit_alias_migration_has_redirect_history(self):
        routes = initialize_routes(self.model, ['en'], self.path, update=True)
        old = routes['articles']['en'][A]
        registry = routes['registry']
        set_article_alias(registry, 'en', A, 'deliberate-new-alias')
        self.path.write_text(json.dumps(registry))
        changed = initialize_routes(self.model, ['en'], self.path)
        self.assertEqual(changed['redirects'][old], '/en/faith/deliberate-new-alias/')

    def test_alias_migration_preserves_all_fallback_paths(self):
        routes = initialize_routes(self.model, ['en'], self.path)
        registry = routes['registry']
        set_article_alias(registry, 'en', A, 'approved-alias')
        self.path.write_text(json.dumps(registry))
        changed = initialize_routes(self.model, ['en'], self.path)
        self.assertIn(f'/en/prayer/article-{A}/', changed['redirects'])

    def test_manually_edited_collision_fails_before_write(self):
        self.model['articles']['en'] += [{'id': B, 'title': 'Other', 'categories': {'primary': C}}]
        result = initialize_routes(self.model, ['en'], self.path, update=True)
        result['registry']['articles']['en'][B]['alias'] = 'a-faithful-life'
        self.path.write_text(json.dumps(result['registry']))
        with self.assertRaisesRegex(RouteError, 'collision'):
            initialize_routes(self.model, ['en'], self.path)

    def test_issue_and_category_paths_do_not_collide(self):
        self.model['categories'][0]['slug'] = 'spring-2024'
        result = initialize_routes(self.model, ['en'], self.path)
        self.assertEqual(result['categories']['en'][C], '/en/spring-2024/')
        self.assertEqual(result['issues']['en'][I], '/en/issues/spring-2024/')

    def test_unknown_exported_locale_is_rejected(self):
        self.model['articles']['zz'] = []
        with self.assertRaises(RouteError):
            initialize_routes(self.model, ['en'], self.path)


if __name__ == '__main__':
    unittest.main()
