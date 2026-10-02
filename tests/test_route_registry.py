"""Offline regression coverage for the last-successful-publication route state."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import urllib.error

from scripts import route_registry

A = '00000000-0000-4000-8000-000000000001'
B = '00000000-0000-4000-8000-000000000002'
C = '00000000-0000-4000-8000-000000000003'
I = '00000000-0000-4000-8000-000000000004'


def registry(alias='faithful-life', *, locale='en'):
    return {'version': 1, 'categories': {locale: {C: {'slug': 'faith', 'history': []}}},
            'issues': {locale: {I: {'slug': 'spring-2024', 'history': []}}},
            'articles': {locale: {A: {'category_id': C, 'category_slug': 'faith',
                'alias': alias, 'history': [], 'fallback': False}}}}


class RegistryMergeTests(unittest.TestCase):
    def test_published_additions_and_retired_records_remain_reserved(self):
        committed = registry()
        published = registry()
        published['articles']['en'][B] = {**published['articles']['en'][A], 'alias': 'second-life'}
        merged = route_registry.merge_registries(committed, published)
        self.assertEqual(merged['articles']['en'][B]['alias'], 'second-life')
        merged['articles']['en'][B]['alias'] = 'mutated'
        self.assertEqual(published['articles']['en'][B]['alias'], 'second-life')

    def test_editorial_alias_promotion_preserves_both_histories_and_previous_path(self):
        committed = registry('reviewed-alias')
        committed['articles']['en'][A]['history'] = ['/en/faith/editorial-history/']
        published = registry('article-' + A)
        published['articles']['en'][A].update(fallback=True, history=['/en/faith/published-history/'])
        result = route_registry.merge_registries(committed, published)['articles']['en'][A]
        self.assertEqual(result['alias'], 'reviewed-alias')
        self.assertEqual(set(result['history']), {'/en/faith/editorial-history/',
            '/en/faith/published-history/', f'/en/faith/article-{A}/'})
        self.assertFalse(result['fallback'])

    def test_stale_committed_fallback_cannot_revert_a_published_readable_migration(self):
        committed = registry('article-' + A)
        committed['articles']['en'][A]['fallback'] = True
        published = registry('published-readable-alias')
        result = route_registry.merge_registries(committed, published)['articles']['en'][A]
        self.assertEqual(result['alias'], 'published-readable-alias')
        self.assertIn(f'/en/faith/article-{A}/', result['history'])

    def test_category_and_issue_editorial_changes_keep_previous_routes(self):
        committed, published = registry(), registry()
        committed['categories']['en'][C].update(slug='belief', history=['/en/trust/'])
        committed['issues']['en'][I]['slug'] = 'spring-issue'
        result = route_registry.merge_registries(committed, published)
        self.assertEqual(result['categories']['en'][C]['history'], ['/en/faith/', '/en/trust/'])
        self.assertEqual(result['issues']['en'][I]['history'], ['/en/issues/spring-2024/'])

    def test_locales_with_the_same_identity_remain_independent(self):
        committed, published = registry(), registry('getroue-lewe', locale='af')
        result = route_registry.merge_registries(committed, published)
        self.assertEqual(result['articles']['en'][A]['alias'], 'faithful-life')
        self.assertEqual(result['articles']['af'][A]['alias'], 'getroue-lewe')

    def test_previous_route_reservations_prevent_alias_reassignment(self):
        committed, published = registry(), registry('previous-title')
        committed['articles']['en'][B] = {**committed['articles']['en'][A], 'alias': 'previous-title'}
        with self.assertRaisesRegex(route_registry.RegistryError, 'collision'):
            route_registry.merge_registries(committed, published)

    def test_snapshot_preparation_leaves_committed_registry_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            committed, output = Path(temp) / 'source.json', Path(temp) / '.build/routes.json'
            committed.write_text(json.dumps(registry()), encoding='utf-8')
            source_bytes = committed.read_bytes()
            published = registry()
            published['articles']['en'][B] = {**published['articles']['en'][A], 'alias': 'newly-published'}
            report = route_registry.prepare_registry(committed, output, published=published)
            self.assertEqual(report['baseline'], 'published')
            self.assertEqual(report['counts']['articles'], 2)
            self.assertEqual(route_registry.read_registry(output)['articles']['en'][B]['alias'], 'newly-published')
            self.assertEqual(committed.read_bytes(), source_bytes)
            with self.assertRaisesRegex(route_registry.RegistryError, 'overwrite'):
                route_registry.prepare_registry(committed, committed, published=published)

    def test_published_snapshot_freezes_generated_route_after_title_correction(self):
        from scripts.routes import initialize_routes
        with tempfile.TemporaryDirectory() as temp:
            source, snapshot = Path(temp) / 'source.json', Path(temp) / 'snapshot.json'
            empty = {'version': 1, 'categories': {}, 'issues': {}, 'articles': {}}
            source.write_text(json.dumps(empty), encoding='utf-8')
            model = {'articles': {'en': [{'id': A, 'title': 'First title', 'categories': {'primary': C}}]},
                     'categories': [{'id': C, 'slug': 'faith'}], 'issues': []}
            first = initialize_routes(copy.deepcopy(model), ['en'], source)
            route_registry.prepare_registry(source, snapshot, published=first['registry'])
            model['articles']['en'][0]['title'] = 'Corrected title'
            next_build = initialize_routes(model, ['en'], snapshot)
            self.assertEqual(next_build['articles']['en'][A], first['articles']['en'][A])


class PublishedRegistryTests(unittest.TestCase):
    def test_fetches_only_the_fixed_published_route_registry(self):
        request = Mock(return_value=(200, json.dumps(registry()).encode()))
        self.assertEqual(route_registry.live_registry(request), registry())
        self.assertEqual(request.call_args.args[0].full_url, route_registry.PRODUCTION_REGISTRY)
        self.assertEqual(request.call_args.args[0].get_header('Cache-control'), 'no-cache')

    def test_only_first_publication_404_allows_no_published_registry(self):
        self.assertIsNone(route_registry.live_registry(Mock(return_value=(404, b''))))
        missing = urllib.error.HTTPError(route_registry.PRODUCTION_REGISTRY, 404, 'missing', {}, None)
        self.assertIsNone(route_registry.live_registry(Mock(side_effect=missing)))
        for status in (403, 429, 500, 503):
            with self.subTest(status=status), self.assertRaises(route_registry.RegistryError):
                route_registry.live_registry(Mock(return_value=(status, b'')))

    def test_transient_failure_and_invalid_manifest_cannot_forget_live_aliases(self):
        for error in (TimeoutError(), urllib.error.URLError('unavailable')):
            with self.subTest(error=type(error)), self.assertRaises(route_registry.RegistryError):
                route_registry.live_registry(Mock(side_effect=error))
        for raw in (b'invalid', b'[]', b'{"version":2}', b'{"version":1,"version":1}'):
            with self.subTest(raw=raw), self.assertRaises(route_registry.RegistryError):
                route_registry.live_registry(Mock(return_value=(200, raw)))

    def test_redirects_and_oversized_responses_are_refused(self):
        with self.assertRaisesRegex(route_registry.RegistryError, 'Redirects'):
            route_registry.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example')
        with self.assertRaisesRegex(route_registry.RegistryError, 'bounded'):
            route_registry.decode_registry(b' ' * (route_registry.MAX_REGISTRY + 1))

    def test_unsafe_records_and_encoded_history_are_rejected(self):
        for field, value in [('alias', '../escape'), ('category_slug', 'faith/escape'),
                             ('category_id', 'not-a-uuid'), ('fallback', 'false')]:
            bad = registry()
            bad['articles']['en'][A][field] = value
            with self.subTest(field=field), self.assertRaises(route_registry.RegistryError):
                route_registry.validate_registry(bad)
        for path in ('https://attacker.example/', '/en/faith/%2e%2e/', '/en/faith/a%2fb/',
                     '/en/faith/%255c/', '/en/faith/name/?query', '/en//name/'):
            bad = registry()
            bad['articles']['en'][A]['history'] = [path]
            with self.subTest(path=path), self.assertRaises(route_registry.RegistryError):
                route_registry.validate_registry(bad)

    def test_unicode_and_encoded_unicode_history_share_the_same_reservation(self):
        value = registry()
        value['articles']['en'][A]['history'] = ['/en/faith/vertroue-%C3%A9/']
        self.assertIs(route_registry.validate_registry(value), value)
        value['articles']['en'][B] = {**value['articles']['en'][A], 'alias': 'vertroue-é', 'history': []}
        with self.assertRaisesRegex(route_registry.RegistryError, 'collision'):
            route_registry.validate_registry(value)

    def test_preparation_is_used_for_pull_requests_and_production(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/pages.yml').read_text()
        before, preparation = workflow.split('      - name: Reuse durable published route aliases\n', 1)
        step, rest = preparation.split('      - name:', 1)
        self.assertNotIn('        if:', step)
        self.assertIn('python3 scripts/route_registry.py', step)
        self.assertIn('Build the complete static site', rest)


if __name__ == '__main__':
    unittest.main()
