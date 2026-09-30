"""Offline security and current-main coalescing contract checks."""
import copy
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_sources
from validate_event import EVENT_TYPE, SITE_REPOSITORY, validate_event, validate_payload


class EventTests(unittest.TestCase):
    def setUp(self):
        self.payload = {'schema': 1, 'repository': 'trueChristian/berean-translation',
                        'revision': 'a' * 40, 'display_fingerprint': 'b' * 64}
        self.event = {'action': EVENT_TYPE, 'client_payload': self.payload}

    @staticmethod
    def fake_checkout(repository, revision, destination, local=None):
        if repository.endswith('/berean-translation'):
            config = destination / 'config'
            config.mkdir(parents=True)
            (config / 'languages.json').write_text(json.dumps({
                'fra': {'name': 'French', 'native_name': 'Français', 'tag': 'fr', 'dir': 'ltr'}}))

    def test_bot_notification_accepted_only_as_bounded_metadata(self):
        self.event['sender'] = {'login': 'github-actions[bot]'}
        result = validate_event('repository_dispatch', self.event, 'refs/heads/main', SITE_REPOSITORY)
        self.assertTrue(result['production'])
        self.assertEqual(result['notification']['revision'], 'a' * 40)

    def test_all_supported_events_and_pr_is_never_production(self):
        for name, event in [('push', {'ref': 'refs/heads/main'}), ('workflow_dispatch', {})]:
            self.assertTrue(validate_event(name, event, 'refs/heads/main', SITE_REPOSITORY)['production'])
        self.assertFalse(validate_event('pull_request', {}, 'refs/pull/3/merge', SITE_REPOSITORY)['production'])

    def test_untrusted_event_forms_rejected(self):
        cases = [
            ('pull_request_target', {}, 'refs/heads/main', SITE_REPOSITORY),
            ('workflow_run', {}, 'refs/heads/main', SITE_REPOSITORY),
            ('push', {'ref': 'refs/heads/main', 'deleted': True}, 'refs/heads/main', SITE_REPOSITORY),
            ('workflow_dispatch', {}, 'refs/heads/feature', SITE_REPOSITORY),
            ('repository_dispatch', self.event, 'refs/heads/main', 'attacker/website'),
            ('repository_dispatch', {'action': 'other', 'client_payload': self.payload}, 'refs/heads/main', SITE_REPOSITORY),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                validate_event(*args)

    def test_payloads_are_exact_bounded_and_do_not_accept_refs_or_shell(self):
        for key, value in [('schema', True), ('schema', 2), ('repository', 'attacker/berean-voice'),
                           ('repository', []), ('revision', 'main'), ('revision', '../main'),
                           ('revision', 'a' * 40 + '\n'), ('revision', '$(touch /tmp/pwn)'),
                           ('revision', 'a' * 41), ('revision', 'A' * 40),
                           ('display_fingerprint', 'a' * 65), ('display_fingerprint', None)]:
            payload = {**self.payload, key: value}
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_payload(payload)
        for payload in [None, [], {**self.payload, 'checkout': 'attacker/ref'}, {'schema': 1}]:
            with self.assertRaises(ValueError):
                validate_payload(payload)

    def test_resolve_main_uses_only_allowlisted_constant_url(self):
        with patch.object(prepare_sources, 'git', return_value='c' * 40 + '\trefs/heads/main') as git:
            self.assertEqual(prepare_sources.resolve_main('trueChristian/berean-voice'), 'c' * 40)
            git.assert_called_once_with('ls-remote', '--exit-code',
                                       'https://github.com/trueChristian/berean-voice.git', 'refs/heads/main')
        with self.assertRaises(ValueError):
            prepare_sources.resolve_main('https://attacker.example/')

    def test_invalid_or_multiple_main_refs_fail_closed(self):
        for value in ['a' * 40 + '\trefs/heads/other', 'a' * 40 + '\trefs/heads/main\n' + 'b' * 40 + '\trefs/heads/main', 'main', '']:
            with patch.object(prepare_sources, 'git', return_value=value), self.assertRaises(ValueError):
                prepare_sources.resolve_main('trueChristian/berean-voice')

    def test_old_payload_does_not_choose_snapshot_or_replay_old_site(self):
        # The event handler only produces audit metadata. Preparation has no event/ref argument.
        validate_event('repository_dispatch', self.event, 'refs/heads/main', SITE_REPOSITORY)
        fake_export = {'translation_status': 'ready'}
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(prepare_sources, 'resolve_main', side_effect=['c' * 40, 'd' * 40]) as resolve, \
             patch.object(prepare_sources, 'checkout_fixed', side_effect=self.fake_checkout) as checkout, \
             patch.object(prepare_sources, 'git', return_value='e' * 40), \
             patch('export_sources.export_sources', return_value=fake_export):
            result = prepare_sources.prepare(Path(temp))
            self.assertEqual(resolve.call_count, 2)
            self.assertEqual(result['sources']['english']['revision'], 'c' * 40)
            self.assertEqual(result['sources']['translations']['revision'], 'd' * 40)
            self.assertEqual(result['sources']['theme']['revision'], prepare_sources.THEME_REVISION)
            self.assertNotIn('a' * 40, str(checkout.call_args_list))

    def test_translation_acquisition_failure_is_explicit_and_english_continues(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(prepare_sources, 'resolve_main', side_effect=['c' * 40, OSError('offline')]), \
             patch.object(prepare_sources, 'checkout_fixed', side_effect=self.fake_checkout), \
             patch.object(prepare_sources, 'git', return_value='e' * 40), \
             patch('export_sources.export_sources', return_value={'translation_status': 'failed'}):
            result = prepare_sources.prepare(Path(temp))
            self.assertIsNone(result['sources']['translations']['revision'])
            self.assertEqual(result['sources']['translations']['acquisition'], 'unavailable')
            self.assertEqual(result['export']['translation_status'], 'failed')
            self.assertEqual(result['language_registry']['status'], 'unavailable')
            self.assertFalse((Path(temp) / 'languages.json').exists())

    def test_partial_failed_translation_export_is_never_given_to_generator(self):
        def failed_export(english, translations, english_output, translation_output):
            translation_output.mkdir()
            (translation_output / 'partial.html').write_text('must never publish')
            return {'translation_status': 'failed'}
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(prepare_sources, 'resolve_main', side_effect=['c' * 40, 'd' * 40]), \
             patch.object(prepare_sources, 'checkout_fixed', side_effect=self.fake_checkout), \
             patch.object(prepare_sources, 'git', return_value='e' * 40), \
             patch('export_sources.export_sources', side_effect=failed_export):
            prepare_sources.prepare(Path(temp))
            self.assertFalse((Path(temp) / 'translations').exists())
            self.assertTrue((Path(temp) / 'translations-unusable/partial.html').is_file())
            # Configured zero-article locales remain checkable despite article-export failure.
            self.assertEqual(json.loads((Path(temp) / 'languages.json').read_text())['fra']['tag'], 'fr')

    def test_registry_snapshot_is_byte_exact_and_rejects_stale_or_symlink_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkout = root / 'checkout'
            self.fake_checkout('trueChristian/berean-translation', 'a' * 40, checkout)
            target = root / 'languages.json'
            prepare_sources.snapshot_languages(checkout, target)
            self.assertEqual(target.read_bytes(), (checkout / 'config/languages.json').read_bytes())
            with self.assertRaisesRegex(ValueError, 'stale input'):
                prepare_sources.snapshot_languages(checkout, target)
            target.unlink()
            source = checkout / 'config/languages.json'
            source.unlink()
            source.symlink_to(root / 'outside.json')
            with self.assertRaisesRegex(ValueError, 'regular language registry'):
                prepare_sources.snapshot_languages(checkout, target)

    def test_invalid_english_stops_before_export(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(prepare_sources, 'resolve_main', side_effect=ValueError('bad English')), \
             patch('export_sources.export_sources') as export, self.assertRaises(ValueError):
            prepare_sources.prepare(Path(temp))
        export.assert_not_called()


class WorkflowContractTests(unittest.TestCase):
    def test_main_workflow_keeps_pr_and_deployment_privileges_separate(self):
        text = (Path(__file__).resolve().parents[1] / '.github/workflows/pages.yml').read_text()
        build, deploy = text.split('\n  deploy:\n', 1)
        self.assertNotIn('secrets.', text)
        self.assertNotIn('pull_request_target:', text)
        self.assertNotIn('pages: write', build)
        self.assertIn('pages: write', deploy)
        self.assertIn('id-token: write', deploy)
        self.assertIn("vars.PAGES_DEPLOY_ENABLED == 'true'", deploy)
        self.assertIn("github.event_name != 'pull_request'", deploy)
        self.assertIn('name: github-pages', deploy)
        self.assertIn("|| 'main'", build)
        self.assertIn("|| 'production'", build)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", build)
        self.assertNotIn('client_payload.', text)
        for ref in re.findall(r'uses: (\S+)', text):
            self.assertRegex(ref, r'^[\w/-]+@[0-9a-f]{40}$')

    def test_source_hooks_are_explicit_after_validation_and_use_success_state(self):
        directory = Path(__file__).resolve().parents[1] / 'integrations'
        translation = (directory / 'berean-translation.patch').read_text()
        english = (directory / 'berean-voice.patch').read_text()
        self.assertIn('Validate the resulting runtime records', translation)
        self.assertIn('Notify Remnant from the durable publishing path', translation)
        self.assertIn('REMNANT_DISPATCH_TOKEN', translation)
        self.assertIn('python3 -m berean_translation export', translation)
        self.assertIn("steps.remnant_notify.outputs.sent == 'true'", translation)
        self.assertIn('refs/heads/main', english)
        self.assertIn('REMNANT_NOTIFICATIONS_ENABLED', english)
        self.assertNotIn('pull_request_target:', translation)


if __name__ == '__main__':
    unittest.main()
