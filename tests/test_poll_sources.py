"""Offline checks for hourly polling, immutable inputs, and success-only state."""
import copy
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import deployment
import poll_sources
import prepare_sources

ROOT = Path(__file__).resolve().parents[1]


class PollingTests(unittest.TestCase):
    def setUp(self):
        self.selection = {'site': 'a' * 40, 'english': 'b' * 40,
                          'translations': 'c' * 40, 'theme': prepare_sources.THEME_REVISION}
        self.live = {'schema': 1, 'display_fingerprint': 'd' * 64,
                     'revisions': dict(self.selection), 'translation_status': 'ready'}

    def test_unchanged_successful_deployed_pins_skip_without_mutation(self):
        before = copy.deepcopy(self.live)
        result = poll_sources.poll_plan(self.selection, self.live)
        self.assertFalse(result['build'])
        self.assertEqual(result['reason'], 'unchanged-deployed-revisions')
        self.assertEqual(self.live, before)

    def test_each_source_or_site_revision_change_requests_build(self):
        for source in ('english', 'translations', 'site'):
            with self.subTest(source=source):
                selected = {**self.selection, source: 'e' * 40}
                self.assertTrue(poll_sources.poll_plan(selected, self.live)['build'])
        # A theme update is reviewed in website code; its deployed pin differs.
        previous = {**self.live, 'revisions': {**self.selection, 'theme': 'e' * 40}}
        self.assertTrue(poll_sources.poll_plan(self.selection, previous)['build'])

    def test_bootstrap_unknown_or_malformed_live_state_never_skips(self):
        for previous in (None, {}, [], {'schema': 2}, {**self.live, 'revisions': {}},
                         {**self.live, 'revisions': {**self.selection, 'english': 'main'}}):
            with self.subTest(previous=previous):
                self.assertTrue(poll_sources.poll_plan(self.selection, previous)['build'])
        for response in (b'not-json', b'[]', b'{}'):
            self.assertIsNone(deployment.live_deployment(Mock(return_value=(200, response))))
        self.assertIsNone(deployment.live_deployment(Mock(side_effect=TimeoutError())))
        self.assertIsNone(deployment.live_deployment(Mock(side_effect=http.client.IncompleteRead(b'partial'))))

    def test_manual_and_pr_always_build_when_pins_match(self):
        self.assertTrue(poll_sources.poll_plan(self.selection, self.live, force=True)['build'])
        result = poll_sources.poll_plan(self.selection, self.live, review=True)
        self.assertTrue(result['build'])
        self.assertEqual(result['reason'], 'pull-request-validation')

    def test_failed_translation_acquisition_or_export_is_retried_at_same_pins(self):
        for status in ('failed', 'unavailable', 'not_attempted', None):
            with self.subTest(status=status):
                result = poll_sources.poll_plan(self.selection, {**self.live, 'translation_status': status})
                self.assertTrue(result['build'])
                self.assertEqual(result['reason'], 'retry-translation-acquisition-or-export')
        unavailable = {**self.selection, 'translations': None}
        self.assertTrue(poll_sources.poll_plan(unavailable, {**self.live, 'revisions': unavailable})['build'])

    def test_failed_build_or_deploy_cannot_advance_poll_baseline(self):
        selected = {**self.selection, 'english': 'e' * 40}
        for _ in range(3):
            self.assertTrue(poll_sources.poll_plan(selected, self.live)['build'])
        # Only serving the successfully deployed artifact changes this outcome.
        published = {**self.live, 'revisions': selected}
        self.assertFalse(poll_sources.poll_plan(selected, published)['build'])
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / 'index.html').write_text('validated candidate')
            report = {'site_revision': selected['site'],
                      'sources': {name: {'revision': selected[name]} for name in prepare_sources.REPOSITORIES},
                      'export': {'translation_status': 'ready'}}
            deployment.deployment_plan(output, report, previous=self.live)
            # Merely creating candidate deployment metadata does not advance live state.
            self.assertTrue(poll_sources.poll_plan(selected, self.live)['build'])

    def test_selection_rejects_untrusted_shapes_refs_and_theme_changes(self):
        for value in (None, [], {}, {**self.selection, 'extra': 'x'},
                      {**self.selection, 'site': 'main'},
                      {**self.selection, 'english': 'a' * 40 + '\n'},
                      {**self.selection, 'english': None},
                      {**self.selection, 'translations': '$(echo injected)'},
                      {**self.selection, 'theme': 'e' * 40}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                poll_sources.validate_selection(value)
        with self.assertRaisesRegex(ValueError, 'website revision'):
            poll_sources.validate_selection(self.selection, site_revision='f' * 40)

    def test_poll_resolves_only_two_allowlisted_heads_without_checkouts(self):
        with patch.object(poll_sources, 'git', return_value=self.selection['site']), \
             patch.object(poll_sources, 'resolve_main', side_effect=['b' * 40, 'c' * 40]) as resolve, \
             patch.object(prepare_sources, 'checkout_fixed') as checkout:
            self.assertEqual(poll_sources.select_revisions(), self.selection)
            self.assertEqual([c.args[0] for c in resolve.call_args_list],
                             ['trueChristian/berean-voice', 'trueChristian/berean-translation'])
            checkout.assert_not_called()
        with patch.object(poll_sources, 'git', return_value=self.selection['site']), \
             patch.object(poll_sources, 'resolve_main', side_effect=['b' * 40, OSError('offline')]):
            self.assertIsNone(poll_sources.select_revisions()['translations'])
        with patch.object(poll_sources, 'git', return_value=self.selection['site']), \
             patch.object(poll_sources, 'resolve_main', side_effect=OSError('offline')), self.assertRaises(OSError):
            poll_sources.select_revisions()

    def test_cli_writes_safe_job_outputs_and_does_not_contact_live_for_pr(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report, output, summary = (root / name for name in ('report.json', 'output', 'summary'))
            args = ['poll_sources.py', '--review', '--report', str(report)]
            with patch.object(sys, 'argv', args), \
                 patch.object(poll_sources, 'select_revisions', return_value=self.selection), \
                 patch.object(poll_sources, 'live_deployment') as live, \
                 patch.dict(os.environ, {'GITHUB_OUTPUT': str(output), 'GITHUB_STEP_SUMMARY': str(summary)}):
                poll_sources.main()
            live.assert_not_called()
            outputs = dict(line.split('=', 1) for line in output.read_text().splitlines())
            self.assertEqual(outputs['build'], 'true')
            self.assertEqual(json.loads(outputs['selection']), self.selection)
            self.assertEqual(json.loads(report.read_text())['selection'], self.selection)

    @staticmethod
    def fake_checkout(repository, revision, destination, local=None):
        if repository.endswith('/berean-translation'):
            config = destination / 'config'
            config.mkdir(parents=True)
            (config / 'languages.json').write_text('{}')

    def test_build_uses_preflight_pins_even_if_source_main_moves(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(prepare_sources, 'git', return_value=self.selection['site']), \
             patch.object(prepare_sources, 'resolve_main', side_effect=AssertionError('must not re-resolve')), \
             patch.object(prepare_sources, 'checkout_fixed', side_effect=self.fake_checkout) as checkout, \
             patch('export_sources.export_sources', return_value={'translation_status': 'ready'}):
            result = prepare_sources.prepare(Path(temp), selection=self.selection)
            self.assertEqual(result['site_revision'], self.selection['site'])
            self.assertEqual({name: source['revision'] for name, source in result['sources'].items()},
                             {name: self.selection[name] for name in prepare_sources.REPOSITORIES})
            self.assertEqual([call.args[1] for call in checkout.call_args_list],
                             [self.selection[name] for name in prepare_sources.REPOSITORIES])

    def test_mismatched_website_checkout_fails_before_source_export(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(prepare_sources, 'git', return_value='f' * 40), \
             patch.object(prepare_sources, 'checkout_fixed') as checkout, self.assertRaises(ValueError):
            prepare_sources.prepare(Path(temp), selection=self.selection)
        checkout.assert_not_called()


class PollWorkflowTests(unittest.TestCase):
    def test_hourly_preflight_skips_expensive_jobs_and_manual_always_forces(self):
        text = (ROOT / '.github/workflows/pages.yml').read_text()
        check, build = text.split('\n  build:\n', 1)
        self.assertIn("- cron: '17 * * * *'", check)
        self.assertIn('  workflow_dispatch:\n', check)
        self.assertNotIn('inputs.force_rebuild', text)
        self.assertEqual(text.count("FORCE_REBUILD: ${{ github.event_name == 'workflow_dispatch' }}"), 2)
        self.assertNotIn('repository_dispatch:', text)
        self.assertNotIn('npm ci', check)
        self.assertNotIn('prepare_sources.py', check)
        self.assertNotIn('secrets.', text)
        self.assertNotIn('cache/', text)
        self.assertIn("if: needs.check.outputs.build == 'true'", build)
        self.assertIn('ref: ${{ needs.check.outputs.site_revision }}', build)
        self.assertIn('SOURCE_SELECTION: ${{ needs.check.outputs.selection }}', build)
        self.assertIn('prepare_sources.py --selection "$SOURCE_SELECTION"', build)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", text)
        self.assertIn("|| 'production'", text)
        self.assertIn('python3 scripts/deployment.py', build)
        self.assertFalse((ROOT / 'scripts/dispatch.py').exists())
        self.assertFalse((ROOT / 'integrations').exists())


if __name__ == '__main__':
    unittest.main()
