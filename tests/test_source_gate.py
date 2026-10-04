"""Offline pre-generator checks using only small synthetic source exports."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_sources
from test_content import A, SHA, fixture as export_fixture, inventory, write_json

B = '00000000-0000-4000-8000-000000000004'


class SourceGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.english, self.translations = self.root / 'english', self.root / 'translations'
        export_fixture(self.english)
        export_fixture(self.translations, translated=True)
        self.languages = self.root / 'languages.json'
        write_json(self.languages, {
            'afr': {'name': 'Afrikaans', 'native_name': 'Afrikaans', 'tag': 'af', 'dir': 'ltr'},
            'jpn': {'name': 'Japanese', 'native_name': '日本語', 'tag': 'ja', 'dir': 'ltr'},
        })
        self.report = {
            'site_revision': 'b' * 40,
            'sources': {name: {'revision': revision} for name, revision in
                        [('english', SHA), ('translations', 'c' * 40), ('theme', 'd' * 40)]},
            'export': {'english_status': 'ready', 'translation_status': 'ready'},
        }
        self.live = {
            'schema': 1, 'display_fingerprint': 'e' * 64,
            'revisions': {'site': 'b' * 40, 'english': SHA,
                          'translations': 'c' * 40, 'theme': 'd' * 40},
            'translation_status': 'ready',
            'article_inventory': {'en': [A], 'af': [A], 'ja': []},
        }

    def check(self, **kwargs):
        return check_sources.check_inputs(
            self.report, self.english, self.translations, self.languages,
            **({'previous': self.live} | kwargs))

    def refresh_manifest(self, root):
        path = root / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['files'] = inventory(root)
        write_json(path, manifest)

    def add_article(self, root, *, translated=False):
        index_path = root / 'index.json'
        index = json.loads(index_path.read_text())
        article = json.loads(json.dumps(index['articles'][0]).replace(A, B))
        html_path = article['html'] if translated else article['html']['repository_path']
        original_path = html_path.replace(B, A)
        html = (root / original_path).read_text().replace(A, B)
        (root / html_path).write_text(html)
        if translated:
            import hashlib
            article['html_sha256'] = hashlib.sha256(html.encode()).hexdigest()
            write_json(root / article['metadata'],
                       json.loads((root / article['metadata'].replace(B, A)).read_text()))
        index['articles'].append(article)
        write_json(index_path, index)
        manifest_path = root / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        if translated:
            manifest['article_count'] = len(index['articles'])
        else:
            manifest['counts']['articles'] = len(index['articles'])
        write_json(manifest_path, manifest)
        self.refresh_manifest(root)

    def test_healthy_exports_include_empty_registry_locales_without_writing_pages(self):
        before = inventory(self.root)
        result = self.check()
        self.assertTrue(result['ready'])
        self.assertEqual(result['revisions'], self.live['revisions'])
        self.assertEqual(result['article_counts'], {'en': 1, 'af': 1, 'ja': 0})
        self.assertEqual(inventory(self.root), before)
        self.assertFalse((self.root / 'dist').exists())

    def test_failed_upstream_is_rejected_before_loading_exports(self):
        for field in ('english_status', 'translation_status'):
            with self.subTest(field=field):
                report = copy.deepcopy(self.report)
                report['export'][field] = 'failed'
                with patch.object(check_sources, 'load_content') as load:
                    with self.assertRaisesRegex(ValueError, 'export'):
                        check_sources.check_inputs(report, self.english, self.translations,
                                                   self.languages, previous=self.live)
                    load.assert_not_called()

    def test_failed_export_cli_stops_before_network_unusable_inputs_or_output(self):
        report_path = self.root / 'source-report.json'
        for field in ('english_status', 'translation_status'):
            with self.subTest(field=field):
                report = copy.deepcopy(self.report)
                report['export'][field] = 'failed'
                write_json(report_path, report)
                argv = ['check_sources.py', '--source-report', str(report_path),
                        '--english', str(self.root / 'absent-english'),
                        '--translations', str(self.root / 'absent-translations'),
                        '--languages', str(self.root / 'absent-languages.json'),
                        '--migration-baseline', str(self.root / 'absent-baseline.json')]
                before = inventory(self.root)
                with patch.object(sys, 'argv', argv), \
                     patch.object(check_sources, 'live_deployment') as fetch, \
                     patch.object(check_sources, 'load_content') as load, \
                     patch('sys.stdout', new_callable=io.StringIO) as stdout:
                    with self.assertRaisesRegex(ValueError, 'export'):
                        check_sources.main()
                    fetch.assert_not_called()
                    load.assert_not_called()
                    self.assertEqual(stdout.getvalue(), '')
                self.assertEqual(inventory(self.root), before)
                self.assertFalse((self.root / 'dist').exists())

    def test_ready_report_cannot_hide_a_corrupt_export_checksum(self):
        (self.translations / f'content/afr/articles/{A}.html').write_text('corruption')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.check()

    def test_ready_report_cannot_hide_rehashed_sidecar_index_disagreement(self):
        write_json(self.translations / f'content/afr/articles/{A}.json',
                   {'title': 'Different title', 'subtitle': None, 'section': ''})
        self.refresh_manifest(self.translations)
        with self.assertRaisesRegex(ValueError, 'sidecar/index mismatch'):
            self.check()

    def test_ready_report_cannot_hide_rehashed_html_fingerprint_disagreement(self):
        path = self.translations / f'content/afr/articles/{A}.html'
        path.write_text(path.read_text().replace('Exact words', 'Changed words'))
        self.refresh_manifest(self.translations)
        with self.assertRaisesRegex(ValueError, 'HTML fingerprint mismatch'):
            self.check()

    def test_healthy_export_at_an_old_selected_source_pin_is_rejected(self):
        for source in ('english', 'translations'):
            with self.subTest(source=source):
                report = copy.deepcopy(self.report)
                report['sources'][source]['revision'] = 'f' * 40
                with self.assertRaisesRegex(ValueError, 'selected healthy source revisions|different .*revision'):
                    check_sources.check_inputs(report, self.english, self.translations,
                                               self.languages, previous=self.live)

    def test_partial_translation_loss_is_rejected_while_retained_count_is_nonzero(self):
        self.add_article(self.english)
        self.live['article_inventory'].update(en=[A, B], af=[A, B])
        with self.assertRaisesRegex(ValueError, f'af: 1 published article UUID.*{B}'):
            self.check()

    def test_equal_count_uuid_replacement_is_rejected(self):
        self.add_article(self.english)
        self.live['article_inventory'].update(en=[A, B], af=[B])
        with self.assertRaisesRegex(ValueError, f'af: 1 published article UUID.*{B}'):
            self.check()

    def test_previously_empty_locale_disappearing_from_registry_is_rejected(self):
        registry = json.loads(self.languages.read_text())
        del registry['jpn']
        write_json(self.languages, registry)
        with self.assertRaisesRegex(ValueError, 'ja: locale disappeared'):
            self.check()

    def test_missing_language_registry_is_rejected(self):
        self.languages.unlink()
        with self.assertRaisesRegex(ValueError, 'Cannot read languages.json'):
            self.check()

    def test_missing_live_or_migration_baseline_fails_closed(self):
        legacy = {key: value for key, value in self.live.items() if key != 'article_inventory'}
        for previous in (None, legacy):
            with self.subTest(previous=previous), self.assertRaisesRegex(ValueError, 'baseline|snapshot'):
                self.check(previous=previous)

    def test_matching_migration_baseline_is_accepted_but_stale_identity_is_rejected(self):
        legacy = {key: value for key, value in self.live.items() if key != 'article_inventory'}
        snapshot = {'deployment': copy.deepcopy(legacy),
                    'article_inventory': copy.deepcopy(self.live['article_inventory'])}
        self.assertTrue(self.check(previous=legacy, migration_snapshot=snapshot)['ready'])
        snapshot['deployment']['revisions']['site'] = 'f' * 40
        with self.assertRaisesRegex(ValueError, 'does not match the live publication identity'):
            self.check(previous=legacy, migration_snapshot=snapshot)

    def test_article_and_locale_additions_are_allowed(self):
        self.add_article(self.english)
        self.add_article(self.translations, translated=True)
        del self.live['article_inventory']['ja']
        result = self.check()
        self.assertEqual(result['article_counts'], {'en': 2, 'af': 2, 'ja': 0})

    def test_healthy_cli_records_private_context_without_generating_site_pages(self):
        report_path = self.root / 'source-report.json'
        write_json(report_path, self.report)
        argv = ['check_sources.py', '--source-report', str(report_path),
                '--english', str(self.english), '--translations', str(self.translations),
                '--languages', str(self.languages),
                '--retention-context', str(self.root / 'retention-context.json'),
                '--migration-baseline', str(self.root / 'unused-baseline.json')]
        before = inventory(self.root)
        with patch.object(sys, 'argv', argv), \
             patch.object(check_sources, 'live_deployment', return_value=self.live) as fetch, \
             patch('sys.stdout', new_callable=io.StringIO) as stdout:
            check_sources.main()
            fetch.assert_called_once_with(fresh=True)
            self.assertEqual(json.loads(stdout.getvalue())['article_counts'],
                             {'en': 1, 'af': 1, 'ja': 0})
        after = inventory(self.root)
        after.pop('retention-context.json')
        self.assertEqual(after, before)


if __name__ == '__main__':
    unittest.main()
