"""Offline website deployment and recovery state machine tests."""
import copy
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import deployment


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        (self.output / 'index.html').write_text('<h1>English</h1>')
        self.report = {'site_revision': 'a' * 40, 'sources': {
            key: {'revision': value * 40} for key, value in [('english', 'b'), ('translations', 'c'), ('theme', 'd')]},
            'export': {'translation_status': 'ready'}}
        self.article_id = '00000000-0000-4000-8000-000000000001'
        (self.output / 'en/read').mkdir(parents=True)
        (self.output / 'af').mkdir()
        (self.output / 'en/read/index.html').write_text(f'<article data-article-id="{self.article_id}">Source</article>')
        (self.output / 'en/search-index.json').write_text(json.dumps([{'id': self.article_id, 'url': '/en/read/'}]))
        (self.output / 'af/search-index.json').write_text('[]')
        self.live = {'schema': 1, 'display_fingerprint': '0' * 64,
                     'revisions': {'site': 'a'*40, 'english': 'b'*40, 'translations': 'c'*40, 'theme': 'd'*40},
                     'translation_status': 'ready', 'article_inventory': {'en': [self.article_id], 'af': []}}
        self.built = {'article_counts': {'en': 1, 'af': 0}, 'site_revision': 'a' * 40, 'theme_revision': 'd' * 40,
                      'source': {'source_revision': 'b' * 40, 'translation_revision': 'c' * 40,
                                 'translation_status': 'ready'}}

    def tearDown(self):
        self.temp.cleanup()

    def test_duplicate_output_is_skipped_but_force_recovery_is_available(self):
        first = deployment.deployment_plan(self.output, self.report, self.built, previous=self.live)
        self.assertTrue(first['changed'])
        self.assertFalse(deployment.deployment_plan(self.output, self.report, self.built, previous=first)['changed'])
        self.assertTrue(deployment.deployment_plan(self.output, self.report, self.built, previous=first, force=True)['changed'])

    def test_stale_cdn_marker_cannot_suppress_a_new_revert_commit(self):
        previous = deployment.deployment_plan(self.output, self.report, self.built, previous=self.live)
        self.report['sources']['english']['revision'] = 'f' * 40
        self.built['source']['source_revision'] = 'f' * 40
        # Display can legitimately return to historical bytes at a new commit.
        self.assertTrue(deployment.deployment_plan(self.output, self.report, self.built, previous=previous)['changed'])

    def test_provenance_only_changes_do_not_trigger_deployment(self):
        before = deployment.display_fingerprint(self.output)
        (self.output / 'build-report.json').write_text('{"time": "later"}')
        (self.output / 'deployment.json').write_text('{"revision": "new"}')
        self.assertEqual(before, deployment.display_fingerprint(self.output))

    def test_failed_translations_preserve_previous_manifest_and_healthy_recovery_works(self):
        (self.output / 'af.html').write_text('<h1>Afrikaans</h1>')
        ready = deployment.deployment_plan(self.output, self.report, self.built, previous=self.live)
        previous_manifest = (self.output / 'deployment.json').read_bytes()
        (self.output / 'af.html').unlink()
        self.report['export']['translation_status'] = 'failed'
        with self.assertRaisesRegex(ValueError, 'Refusing publication'):
            deployment.deployment_plan(self.output, self.report, self.built, previous=ready)
        self.assertEqual((self.output / 'deployment.json').read_bytes(), previous_manifest)
        (self.output / 'af.html').write_text('<h1>Afrikaans</h1>')
        self.report['export']['translation_status'] = 'ready'
        self.assertFalse(deployment.deployment_plan(self.output, self.report, self.built, previous=ready)['changed'])
        self.report['sources']['translations']['revision'] = 'f' * 40
        self.built['source']['translation_revision'] = 'f' * 40
        self.assertTrue(deployment.deployment_plan(self.output, self.report, self.built, previous=ready)['changed'])

    def test_unavailable_translation_revision_can_never_be_a_publication_candidate(self):
        self.report['sources']['translations'] = {'revision': None, 'acquisition': 'unavailable'}
        self.built['source']['translation_revision'] = None
        for status in ('ready', 'failed'):
            self.report['export']['translation_status'] = status
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, 'complete fixed-revision'):
                deployment.deployment_plan(self.output, self.report, self.built, force=True)

    def test_each_unhealthy_stage_blocks_before_fingerprinting_even_with_force(self):
        for force in (False, True):
            for stage in ('export', 'source'):
                for status in ('failed', 'unavailable', 'not_attempted', 'unknown', None, '', False, ['ready']):
                    exported, built = copy.deepcopy(self.report), copy.deepcopy(self.built)
                    report = exported if stage == 'export' else built
                    report[stage]['translation_status'] = status
                    with self.subTest(stage=stage, status=status, force=force), \
                         patch.object(deployment, 'display_fingerprint') as fingerprint, \
                         self.assertRaisesRegex(ValueError, 'Refusing publication'):
                        deployment.deployment_plan(self.output, exported, built, force=force)
                    fingerprint.assert_not_called()
                    self.assertFalse((self.output / 'deployment.json').exists())

    def test_missing_or_malformed_health_reports_fail_closed(self):
        for stage in ('export', 'source'):
            for value in ({}, None, [], 'ready', {'translation_status': 1}):
                exported, built = copy.deepcopy(self.report), copy.deepcopy(self.built)
                report = exported if stage == 'export' else built
                report[stage] = value
                with self.subTest(stage=stage, value=value), self.assertRaisesRegex(ValueError, 'Refusing publication'):
                    deployment.deployment_plan(self.output, exported, built)
            exported, built = copy.deepcopy(self.report), copy.deepcopy(self.built)
            del (exported if stage == 'export' else built)[stage]
            with self.assertRaisesRegex(ValueError, 'Refusing publication'):
                deployment.deployment_plan(self.output, exported, built)
        for built in (None, [], 'ready', {}):
            with self.subTest(built=built), self.assertRaisesRegex(ValueError, 'Refusing publication'):
                deployment.deployment_plan(self.output, self.report, built)

    def test_stale_healthy_build_report_cannot_authorize_new_sources(self):
        for field in ('site_revision', 'theme_revision', 'source_revision', 'translation_revision'):
            built = copy.deepcopy(self.built)
            container = built if field in ('site_revision', 'theme_revision') else built['source']
            container[field] = 'e' * 40
            with self.subTest(field=field), patch.object(deployment, 'display_fingerprint') as fingerprint, \
                 self.assertRaisesRegex(ValueError, 'build report revisions'):
                deployment.deployment_plan(self.output, self.report, built, force=True)
            fingerprint.assert_not_called()

    def test_ready_empty_translation_export_and_english_growth_are_valid(self):
        self.report['export']['translated_articles'] = 0
        self.built['article_counts'] = {'en': 1, 'af': 0}
        self.assertTrue(deployment.deployment_plan(self.output, self.report, self.built, previous=self.live)['changed'])
        self.assertEqual(json.loads((self.output / 'deployment.json').read_text())['translation_status'], 'ready')

    def test_retention_failure_never_overwrites_manifest_even_when_forced(self):
        previous = deployment.deployment_plan(self.output, self.report, self.built, previous=self.live)
        original = (self.output / 'deployment.json').read_bytes()
        previous['article_inventory']['af'] = [self.article_id]
        for force in (False, True):
            with self.subTest(force=force), patch.object(deployment, 'display_fingerprint') as fingerprint, \
                 self.assertRaises(ValueError):
                deployment.deployment_plan(self.output, self.report, self.built, previous=previous, force=force)
            fingerprint.assert_not_called()
            self.assertEqual((self.output / 'deployment.json').read_bytes(), original)

    def test_manual_cli_requires_live_inventory_and_cannot_bootstrap_from_missing_live_state(self):
        source_file, build_file, plan, migration = (self.output / name for name in
                                                  ('sources.json', 'build.json', 'plan.json', 'baseline.json'))
        source_file.write_text(json.dumps(self.report))
        build_file.write_text(json.dumps(self.built))
        migration.write_text(json.dumps({'deployment': {k: v for k, v in self.live.items() if k != 'article_inventory'},
                                         'article_inventory': self.live['article_inventory']}))
        argv = ['deployment.py', '--site-output', str(self.output), '--source-report', str(source_file),
                '--build-report', str(build_file), '--migration-baseline', str(migration), '--report', str(plan), '--force']
        with patch.object(sys, 'argv', argv), patch.object(deployment, 'live_deployment', return_value=None) as live, \
             patch.object(deployment, 'display_fingerprint') as fingerprint, self.assertRaises(ValueError):
            deployment.main()
        live.assert_called_once_with(fresh=True)
        fingerprint.assert_not_called()
        self.assertFalse(plan.exists())
        self.assertFalse((self.output / 'deployment.json').exists())

    def test_cli_rejection_writes_no_plan_or_workflow_output(self):
        source_file, build_file, plan, workflow_output = (self.output / name for name in
                                                        ('sources.json', 'build.json', 'plan.json', 'workflow-output'))
        source_file.write_text(json.dumps(self.report))
        workflow_output.write_text('existing=value\n')
        self.built['source']['translation_status'] = 'failed'
        build_file.write_text(json.dumps(self.built))
        script = Path(deployment.__file__)
        for extra in ([], ['--force']):
            result = subprocess.run([sys.executable, str(script), '--site-output', str(self.output),
                                     '--source-report', str(source_file), '--build-report', str(build_file),
                                     '--report', str(plan), *extra], capture_output=True, text=True,
                                    env={**os.environ, 'GITHUB_OUTPUT': str(workflow_output)})
            with self.subTest(extra=extra):
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Refusing publication', result.stderr)
                self.assertFalse(plan.exists())
                self.assertFalse((self.output / 'deployment.json').exists())
                self.assertEqual(workflow_output.read_text(), 'existing=value\n')
        build_file.unlink()
        result = subprocess.run([sys.executable, str(script), '--site-output', str(self.output),
                                 '--source-report', str(source_file), '--build-report', str(build_file),
                                 '--report', str(plan)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(plan.exists())

    def test_modern_live_inventory_does_not_depend_on_legacy_snapshot_file(self):
        source_file, build_file, plan = (self.output / name for name in ('sources.json', 'build.json', 'plan.json'))
        source_file.write_text(json.dumps(self.report))
        build_file.write_text(json.dumps(self.built))
        argv = ['deployment.py', '--site-output', str(self.output), '--source-report', str(source_file),
                '--build-report', str(build_file), '--migration-baseline', str(self.output / 'absent-baseline.json'),
                '--report', str(plan), '--force']
        with patch.object(sys, 'argv', argv), patch.object(deployment, 'live_deployment', return_value=self.live) as live, \
             patch.dict(os.environ, {'GITHUB_OUTPUT': str(self.output / 'workflow-output')}), \
             patch('builtins.print'):
            deployment.main()
        live.assert_called_once_with(fresh=True)
        self.assertEqual(json.loads(plan.read_text())['article_inventory'], self.live['article_inventory'])

    def test_live_marker_network_failure_never_suppresses_a_build(self):
        self.assertIsNone(deployment.live_deployment(Mock(side_effect=TimeoutError())))
        for content in [b'not json', b'[]', b'{"schema":1,"display_fingerprint":"bad"}']:
            self.assertIsNone(deployment.live_deployment(Mock(return_value=(200, content))))
        value = 'e' * 64
        request = Mock(return_value=(200, json.dumps({'schema': 1, 'display_fingerprint': value}).encode()))
        self.assertEqual(deployment.live_deployment(request)['display_fingerprint'], value)
        self.assertEqual(request.call_args.args[0].full_url, deployment.PRODUCTION_MANIFEST)
        deployment.live_deployment(request, fresh=True)
        checked = request.call_args.args[0]
        self.assertRegex(checked.full_url, r'/deployment\.json\?publication-check=[a-f0-9]{32}$')
        self.assertIn('no-store', checked.get_header('Cache-control'))

    def test_redirects_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'Redirects'):
            deployment.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://attacker.example')


if __name__ == '__main__':
    unittest.main()
