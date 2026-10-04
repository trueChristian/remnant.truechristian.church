"""Offline, identity-based regressions for preserving every published article."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from publication_inventory import (assert_retains, baseline_inventory,
                                   candidate_inventory, validate_inventory)


def identity(number):
    return f'00000000-0000-4000-8000-{number:012x}'


ONE, TWO, THREE = (identity(number) for number in (1, 2, 3))


def manifest():
    return {'schema': 1, 'display_fingerprint': 'e' * 64,
            'revisions': {'site': 'a' * 40, 'english': 'b' * 40,
                          'translations': 'c' * 40, 'theme': 'd' * 40},
            'translation_status': 'ready'}


class ValidateInventoryTests(unittest.TestCase):
    def test_returns_sorted_copy_and_allows_empty_translations(self):
        inventory = {'zh-Hans': [], 'en': [TWO, ONE], 'af': [ONE]}
        original = copy.deepcopy(inventory)
        actual = validate_inventory(inventory)
        self.assertEqual(list(actual), ['af', 'en', 'zh-Hans'])
        self.assertEqual(actual['en'], [ONE, TWO])
        actual['en'].append(THREE)
        self.assertEqual(inventory, original)

    def test_missing_or_empty_english_is_rejected(self):
        for inventory in ({}, {'af': [ONE]}, {'en': []}, {'en': [], 'af': [ONE]}):
            with self.subTest(inventory=inventory), self.assertRaisesRegex(ValueError, 'English'):
                validate_inventory(inventory)

    def test_invalid_inventory_shapes_and_uuid_forms_are_rejected(self):
        for inventory in (None, [], 'en', {'en': ONE}, {'en': {ONE}}, {'en': [None]},
                          {'en': [1]}, {'en': [{}]}, {'en': ['not-a-uuid']},
                          {'en': [ONE.replace('-', '')]}, {'en': ['{' + ONE + '}']},
                          {'en': ['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'.upper()]},
                          {'en': [ONE, ONE]}):
            with self.subTest(inventory=inventory), self.assertRaises(ValueError):
                validate_inventory(inventory)

    def test_unsafe_or_malformed_locale_tags_are_rejected(self):
        for locale in ('', '../en', '/en', 'en/af', 'en_af', 'EN', 'en--GB',
                       'en\n', 'e', 'english', 'en-' + 'a' * 100, 1, None):
            with self.subTest(locale=locale), self.assertRaisesRegex(ValueError, 'locale tag'):
                validate_inventory({'en': [ONE], locale: []})


class RetentionTests(unittest.TestCase):
    def test_nonzero_translation_drop_1951_to_1930_is_rejected(self):
        previous = {'en': [ONE], 'af': [identity(number) for number in range(1, 1952)]}
        candidate = {'en': [ONE], 'af': previous['af'][:1930]}
        with self.assertRaisesRegex(ValueError, 'af: 21 published article UUID') as raised:
            assert_retains(previous, candidate)
        self.assertIn('whole last successful publication', str(raised.exception))
        self.assertLess(len(str(raised.exception)), 500)

    def test_one_replaced_uuid_at_same_count_is_rejected(self):
        with self.assertRaisesRegex(ValueError, f'af: 1 published article UUID.*{ONE}'):
            assert_retains({'en': [ONE, TWO], 'af': [ONE]}, {'en': [ONE, TWO], 'af': [TWO]})

    def test_growth_in_other_locale_cannot_hide_loss(self):
        with self.assertRaisesRegex(ValueError, 'af: 1 published article UUID'):
            assert_retains({'en': [ONE, TWO], 'af': [ONE]}, {'en': [ONE, TWO, THREE], 'af': []})

    def test_english_loss_is_also_rejected(self):
        with self.assertRaisesRegex(ValueError, 'en: 1 published article UUID'):
            assert_retains({'en': [ONE, TWO]}, {'en': [TWO]})

    def test_missing_locale_is_rejected_even_if_it_was_empty(self):
        for prior in ([], [ONE]):
            with self.subTest(prior=prior), self.assertRaisesRegex(ValueError, 'af: locale disappeared'):
                assert_retains({'en': [ONE], 'af': prior}, {'en': [ONE]})

    def test_retention_allows_updates_reordering_and_additions(self):
        previous = {'en': [TWO, ONE], 'af': [ONE], 'fr': []}
        candidate = {'en': [ONE, TWO, THREE], 'af': [TWO, ONE], 'fr': [], 'zh-Hans': [ONE]}
        self.assertIsNone(assert_retains(previous, candidate))
        self.assertIsNone(assert_retains(previous, copy.deepcopy(previous)))

    def test_both_inventories_must_be_valid(self):
        for previous, candidate in ((None, {'en': [ONE]}), ({'en': [ONE]}, None),
                                    ({'en': [ONE, ONE]}, {'en': [ONE]}),
                                    ({'en': [ONE]}, {'en': [ONE, ONE]})):
            with self.subTest(previous=previous, candidate=candidate), self.assertRaises(ValueError):
                assert_retains(previous, candidate)

    def test_errors_are_bounded_across_many_affected_locales(self):
        previous = {'en': [ONE], **{f'aa-{number:03}': [ONE, TWO, THREE] for number in range(100)}}
        with self.assertRaises(ValueError) as raised:
            assert_retains(previous, {'en': [ONE]})
        self.assertIn('+95 more affected locales', str(raised.exception))
        self.assertLess(len(str(raised.exception)), 500)


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.live = manifest()
        self.inventory = {'en': [TWO, ONE], 'af': [ONE], 'fr': []}
        self.snapshot = {'deployment': copy.deepcopy(self.live),
                         'article_inventory': copy.deepcopy(self.inventory)}

    def test_healthy_live_inventory_is_authoritative(self):
        self.live['article_inventory'] = self.inventory
        self.assertEqual(baseline_inventory(self.live), validate_inventory(self.inventory))
        self.assertEqual(baseline_inventory(self.live, {'malformed': True}), validate_inventory(self.inventory))

    def test_exactly_matching_legacy_snapshot_is_accepted(self):
        self.assertEqual(baseline_inventory(self.live, self.snapshot), validate_inventory(self.inventory))

    def test_present_but_bad_live_inventory_never_falls_back(self):
        for value in (None, [], {}, {'en': []}, {'en': [ONE, ONE]}, {'en': ['bad']}):
            self.live['article_inventory'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                baseline_inventory(self.live, self.snapshot)

    def test_missing_live_manifest_or_unverified_snapshot_fails_closed(self):
        for live, snapshot in ((None, self.snapshot), ({}, self.snapshot), (self.live, None),
                               (self.live, {}), (self.live, []),
                               (self.live, {'deployment': copy.deepcopy(self.live)})):
            with self.subTest(live=live, snapshot=snapshot), self.assertRaises(ValueError):
                baseline_inventory(live, snapshot)

    def test_every_valid_but_different_revision_invalidates_snapshot(self):
        for revision in ('site', 'english', 'translations', 'theme'):
            snapshot = copy.deepcopy(self.snapshot)
            snapshot['deployment']['revisions'][revision] = 'f' * 40
            with self.subTest(revision=revision), self.assertRaisesRegex(ValueError, 'does not match'):
                baseline_inventory(self.live, snapshot)

    def test_different_valid_fingerprint_invalidates_snapshot(self):
        self.snapshot['deployment']['display_fingerprint'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'does not match'):
            baseline_inventory(self.live, self.snapshot)

    def test_malformed_pins_rejected_in_both_live_and_migration_manifest(self):
        for target in ('live', 'migration'):
            for field in ('site', 'english', 'translations', 'theme'):
                for bad in (None, 'main', 'a' * 39, 'A' * 40, 'a' * 40 + '\n', 1):
                    live, snapshot = copy.deepcopy(self.live), copy.deepcopy(self.snapshot)
                    deployment = live if target == 'live' else snapshot['deployment']
                    deployment['revisions'][field] = bad
                    with self.subTest(target=target, field=field, bad=bad), \
                         self.assertRaisesRegex(ValueError, 'fixed revisions'):
                        baseline_inventory(live, snapshot)

    def test_missing_extra_or_malformed_revision_mappings_rejected(self):
        for pins in (None, [], {}, {'site': 'a' * 40}, {**self.live['revisions'], 'extra': 'f' * 40}):
            live = copy.deepcopy(self.live)
            live['revisions'] = pins
            live['article_inventory'] = self.inventory
            with self.subTest(pins=pins), self.assertRaisesRegex(ValueError, 'fixed revisions'):
                baseline_inventory(live)

    def test_bad_schema_fingerprint_and_health_are_never_verified(self):
        for target in ('live', 'migration'):
            for field, values in (('schema', [None, 0, 2, True, '1']),
                                  ('display_fingerprint', [None, 'e' * 63, 'E' * 64, 'e' * 64 + '\n']),
                                  ('translation_status', [None, 'failed', 'not_attempted', ['ready'], True])):
                for bad in values:
                    live, snapshot = copy.deepcopy(self.live), copy.deepcopy(self.snapshot)
                    deployment = live if target == 'live' else snapshot['deployment']
                    deployment[field] = bad
                    with self.subTest(target=target, field=field, bad=bad), self.assertRaises(ValueError):
                        baseline_inventory(live, snapshot)

    def test_matching_but_invalid_deployments_do_not_verify_each_other(self):
        self.live['revisions']['translations'] = None
        self.snapshot['deployment'] = copy.deepcopy(self.live)
        with self.assertRaisesRegex(ValueError, 'fixed revisions'):
            baseline_inventory(self.live, self.snapshot)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.write_locale('en', [ONE, TWO])
        self.write_locale('af', [ONE])
        self.write_locale('fr', [])
        self.counts = {'en': 2, 'af': 1, 'fr': 0}

    def index(self, locale):
        return self.output / locale / 'search-index.json'

    def reader(self, locale, identity):
        return self.output / locale / 'articles' / identity / 'index.html'

    def write_locale(self, locale, identities):
        self.index(locale).parent.mkdir(parents=True, exist_ok=True)
        records = []
        for article_id in identities:
            reader = self.reader(locale, article_id)
            reader.parent.mkdir(parents=True, exist_ok=True)
            reader.write_text(f'<article data-article-id="{article_id}"><p>Text</p></article>', encoding='utf-8')
            records.append({'id': article_id, 'url': f'/{locale}/articles/{article_id}/'})
        self.index(locale).write_text(json.dumps(records), encoding='utf-8')

    def test_complete_candidate_and_empty_translation_locale(self):
        self.assertEqual(candidate_inventory(self.output, self.counts),
                         {'af': [ONE], 'en': [ONE, TWO], 'fr': []})

    def test_actual_generated_readers_and_indexes_are_accepted(self):
        from test_site import fixture
        _, _, _, _, output = fixture(self.output / 'generated')
        self.assertEqual({locale: len(ids) for locale, ids in candidate_inventory(
            output, {'en': 3, 'af': 1, 'fr': 0}).items()}, {'af': 1, 'en': 3, 'fr': 0})

    def test_report_must_cover_exact_indexed_locale_set(self):
        for counts in ({'en': 2, 'af': 1}, {**self.counts, 'de': 0}):
            with self.subTest(counts=counts), self.assertRaisesRegex(ValueError, 'locale sets'):
                candidate_inventory(self.output, counts)
        self.index('fr').unlink()
        with self.assertRaisesRegex(ValueError, 'locale sets'):
            candidate_inventory(self.output, self.counts)

    def test_counts_cannot_be_missing_false_negative_fractional_or_strings(self):
        for counts in (None, [], {}, {**self.counts, 'en': True}, {**self.counts, 'en': -1},
                       {**self.counts, 'en': 2.0}, {**self.counts, 'en': '2'}):
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                candidate_inventory(self.output, counts)

    def test_count_disagreement_cannot_publish(self):
        with self.assertRaisesRegex(ValueError, 'count 2 differs from build count 3'):
            candidate_inventory(self.output, {**self.counts, 'en': 3})

    def test_bad_json_record_shapes_ids_and_duplicates_cannot_publish(self):
        record = {'id': ONE, 'url': f'/af/articles/{ONE}/'}
        for raw in ('{', '{}', '[null]', '["article"]', '[{}]',
                    json.dumps([{**record, 'id': 'invalid'}]), json.dumps([record, record]),
                    '[{"id":"' + ONE + '","id":"' + TWO + '","url":"/af/a/"}]'):
            self.index('af').write_text(raw, encoding='utf-8')
            count = 2 if raw == json.dumps([record, record]) else 1
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                candidate_inventory(self.output, {**self.counts, 'af': count})

    def test_stale_index_with_missing_reader_cannot_publish(self):
        self.reader('af', ONE).unlink()
        with self.assertRaisesRegex(ValueError, 'missing its local file'):
            candidate_inventory(self.output, self.counts)

    def test_placeholders_comments_scripts_wrong_ids_or_duplicate_markers_are_rejected(self):
        for html in ('<p>Translation coming soon</p>', f'<!-- <article data-article-id="{ONE}"> -->',
                     f'<script>"<article data-article-id=\"{ONE}\">"</script>',
                     f'<article data-article-id="{TWO}">Text</article>',
                     f'<article data-article-id="{ONE}" data-article-id="{ONE}">Text</article>',
                     f'<article data-article-id="{ONE}"></article><div data-article-id="{ONE}"></div>'):
            self.reader('af', ONE).write_text(html, encoding='utf-8')
            with self.subTest(html=html), self.assertRaisesRegex(ValueError, 'data-article-id'):
                candidate_inventory(self.output, self.counts)

    def test_external_wrong_locale_traversal_and_non_reader_routes_are_rejected(self):
        for url in (None, 1, 'https://example.com/af/article/', '//example.com/af/article/',
                    'af/article/', f'/en/articles/{ONE}/', '/af/../en/article/', '/af/%2e%2e/en/article/',
                    '/af/..%5cen/article/', '/af/article/?skip=1', '/af/article/#anchor',
                    '/af/article.md', '/af/%00article/', '/af/\narticle/', '/af/%ff/'):
            self.index('af').write_text(json.dumps([{'id': ONE, 'url': url}]), encoding='utf-8')
            with self.subTest(url=url), self.assertRaises(ValueError):
                candidate_inventory(self.output, self.counts)

    def test_unicode_encoded_readable_route_is_accepted(self):
        target = self.output / 'af' / 'geloof' / 'getrouë-woorde' / 'index.html'
        target.parent.mkdir(parents=True)
        self.reader('af', ONE).rename(target)
        self.index('af').write_text(json.dumps([{'id': ONE, 'url': '/af/geloof/getrou%C3%AB-woorde/'}]))
        self.assertEqual(candidate_inventory(self.output, self.counts)['af'], [ONE])

    def test_symlinked_reader_index_and_parent_directory_are_rejected(self):
        for kind in ('reader', 'index', 'directory'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as destination:
                original = self.reader('af', ONE) if kind == 'reader' else self.index('af')
                if kind == 'directory':
                    original = original.parent
                saved = Path(destination) / original.name
                original.rename(saved)
                original.symlink_to(saved, target_is_directory=kind == 'directory')
                try:
                    with self.assertRaisesRegex(ValueError, 'symlinks'):
                        candidate_inventory(self.output, self.counts)
                finally:
                    original.unlink()
                    saved.rename(original)

    def test_missing_or_symlinked_output_is_rejected(self):
        missing = self.output / 'missing'
        linked = self.output / 'linked'
        linked.symlink_to(self.output, target_is_directory=True)
        for path in (missing, linked):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'real output directory'):
                candidate_inventory(path, self.counts)


if __name__ == '__main__':
    unittest.main()
