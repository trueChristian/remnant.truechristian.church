"""No real credentials or network calls: notification/recovery state machine tests."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import dispatch


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.export = self.root / 'export'
        self.export.mkdir()
        self.state = self.root / 'marker/state.json'
        self.revision = 'a' * 40
        self.write('index.json', {'source_revision': 'b' * 40, 'translation_revision': self.revision,
                                 'articles': [{'id': 'one', 'title': 'A title', 'human_reviewed': False}]})
        self.write('manifest.json', {'translation_revision': self.revision, 'omitted': []})
        (self.export / 'article.html').write_text('<article>Text</article><aside>AI notice</aside>')
        self.request = Mock(return_value=(204, b''))
        self.repo = 'trueChristian/berean-translation'
        (self.root / 'config').mkdir()
        (self.root / 'config/languages.json').write_text(json.dumps({
            'afr': {'name': 'Afrikaans', 'native_name': 'Afrikaans', 'tag': 'af', 'dir': 'ltr', 'aliases': []}}))

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, value):
        (self.export / name).write_text(json.dumps(value))

    def send(self, token='test-placeholder'):
        with patch.object(dispatch, 'durable_revision', return_value=self.revision):
            return dispatch.notify(self.repo, self.root, self.export, self.state, token, self.request)

    def test_bot_durable_commit_dispatches_explicitly_then_deduplicates(self):
        self.assertTrue(self.send()['sent'])
        self.assertFalse(self.send()['sent'])
        self.request.assert_called_once()
        request = self.request.call_args.args[0]
        self.assertEqual(request.full_url, dispatch.DISPATCH_ENDPOINT)
        self.assertEqual(request.method, 'POST')
        self.assertEqual(json.loads(request.data)['event_type'], 'remnant-content-updated')
        self.assertNotIn('test-placeholder', self.state.read_text())

    def test_state_only_revision_changes_do_not_notify(self):
        self.send()
        previous = dispatch.display_fingerprint(self.export, exported=True)
        self.revision = 'c' * 40
        self.write('manifest.json', {'translation_revision': self.revision, 'omitted': ['pending candidate']})
        index = json.loads((self.export / 'index.json').read_text())
        index['translation_revision'] = self.revision
        index['source_revision'] = 'd' * 40
        self.write('index.json', index)
        self.assertEqual(dispatch.display_fingerprint(self.export, exported=True), previous)
        self.assertFalse(self.send()['sent'])

    def test_new_zero_article_locale_wakes_site_but_internal_guidance_does_not(self):
        self.send()
        path = self.root / 'config/languages.json'
        registry = json.loads(path.read_text())
        registry['afr']['guidance'] = 'Internal translation instructions changed'
        path.write_text(json.dumps(registry))
        self.assertFalse(self.send()['sent'])
        registry['fra'] = {'name': 'French', 'native_name': 'Français', 'tag': 'fr', 'dir': 'ltr', 'aliases': []}
        path.write_text(json.dumps(registry))
        self.assertTrue(self.send()['sent'])
        self.assertEqual(self.request.call_count, 2)

    def test_human_review_notice_removal_is_display_change(self):
        self.send()
        (self.export / 'article.html').write_text('<article>Text</article>')
        self.assertTrue(self.send()['sent'])
        self.assertEqual(self.request.call_count, 2)

    def test_withdrawal_triggers_new_dispatch(self):
        self.send()
        (self.export / 'article.html').unlink()
        self.write('index.json', {'translation_revision': self.revision, 'articles': []})
        self.assertTrue(self.send()['sent'])

    def test_delivery_failure_does_not_advance_marker_and_retry_recovers(self):
        self.send()
        old_state = self.state.read_bytes()
        (self.export / 'article.html').write_text('<article>Updated</article>')
        self.request.side_effect = TimeoutError('do not log credentials')
        with self.assertRaisesRegex(RuntimeError, 'no success marker'):
            self.send()
        self.assertEqual(old_state, self.state.read_bytes())
        self.request.side_effect = None
        self.assertTrue(self.send()['sent'])
        self.assertFalse(self.send()['sent'])

    def test_api_rejection_does_not_mark_success(self):
        self.request.return_value = (403, b'private error body')
        with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
            self.send()
        self.assertFalse(self.state.exists())

    def test_missing_credential_blocks_only_notification(self):
        with self.assertRaisesRegex(ValueError, 'Owner setup required'):
            self.send(token='')
        self.request.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_unpublished_commit_cannot_notify(self):
        with patch.object(dispatch, 'durable_revision', side_effect=ValueError('not published')), self.assertRaises(ValueError):
            dispatch.notify(self.repo, self.root, self.export, self.state, 'placeholder', self.request)
        self.request.assert_not_called()

    def test_export_from_another_revision_is_rejected(self):
        self.write('manifest.json', {'translation_revision': 'e' * 40})
        with self.assertRaisesRegex(ValueError, 'freshly validated'):
            self.send()
        self.request.assert_not_called()

    def test_marker_loss_or_corruption_safely_resends(self):
        self.send()
        self.state.write_text('incomplete')
        self.assertTrue(self.send()['sent'])

    def test_empty_and_symlink_display_trees_rejected(self):
        empty = self.root / 'empty'
        empty.mkdir()
        with self.assertRaises(ValueError):
            dispatch.display_fingerprint(empty)
        (self.export / 'link').symlink_to(self.root / 'secret')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            dispatch.display_fingerprint(self.export)

    def test_durable_revision_requires_clean_and_current_remote_main(self):
        good = [self.revision, '', self.revision + '\trefs/heads/main']
        with patch.object(dispatch.subprocess, 'check_output', side_effect=good):
            self.assertEqual(dispatch.durable_revision(self.root), self.revision)
        for values in [[self.revision, ' M content/x'], [self.revision, '', 'b' * 40 + '\trefs/heads/main']]:
            with patch.object(dispatch.subprocess, 'check_output', side_effect=values), self.assertRaises(ValueError):
                dispatch.durable_revision(self.root)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        (self.output / 'index.html').write_text('<h1>English</h1>')
        self.report = {'site_revision': 'a' * 40, 'sources': {
            key: {'revision': value * 40} for key, value in [('english', 'b'), ('translations', 'c'), ('theme', 'd')]},
            'export': {'translation_status': 'ready'}}

    def tearDown(self):
        self.temp.cleanup()

    def test_duplicate_output_is_skipped_but_force_recovery_is_available(self):
        first = dispatch.deployment_plan(self.output, self.report)
        self.assertTrue(first['changed'])
        self.assertFalse(dispatch.deployment_plan(self.output, self.report, previous=first)['changed'])
        self.assertTrue(dispatch.deployment_plan(self.output, self.report, previous=first, force=True)['changed'])

    def test_stale_cdn_marker_cannot_suppress_a_new_revert_commit(self):
        previous = dispatch.deployment_plan(self.output, self.report)
        self.report['sources']['english']['revision'] = 'f' * 40
        # Display can legitimately return to historical bytes at a new commit.
        self.assertTrue(dispatch.deployment_plan(self.output, self.report, previous=previous)['changed'])

    def test_provenance_only_changes_do_not_trigger_deployment(self):
        before = dispatch.display_fingerprint(self.output)
        (self.output / 'build-report.json').write_text('{"time": "later"}')
        (self.output / 'deployment.json').write_text('{"revision": "new"}')
        self.assertEqual(before, dispatch.display_fingerprint(self.output))

    def test_degraded_english_and_recovery_are_new_display_snapshots(self):
        (self.output / 'af.html').write_text('<h1>Afrikaans</h1>')
        ready = dispatch.deployment_plan(self.output, self.report)
        (self.output / 'af.html').unlink()
        self.report['export']['translation_status'] = 'failed'
        failed = dispatch.deployment_plan(self.output, self.report, previous=ready)
        self.assertTrue(failed['changed'])
        self.assertEqual(failed['translation_status'], 'failed')
        (self.output / 'af.html').write_text('<h1>Afrikaans</h1>')
        self.report['export']['translation_status'] = 'ready'
        self.assertTrue(dispatch.deployment_plan(self.output, self.report, previous=failed)['changed'])

    def test_unavailable_translation_revision_is_honest_only_when_acquisition_failed(self):
        self.report['sources']['translations'] = {'revision': None, 'acquisition': 'unavailable'}
        self.report['export']['translation_status'] = 'failed'
        self.assertIsNone(dispatch.deployment_plan(self.output, self.report)['revisions']['translations'])
        self.report['sources']['translations']['acquisition'] = 'ready'
        with self.assertRaises(ValueError):
            dispatch.deployment_plan(self.output, self.report)

    def test_live_marker_network_failure_never_suppresses_a_build(self):
        self.assertIsNone(dispatch.live_deployment(Mock(side_effect=TimeoutError())))
        for content in [b'not json', b'[]', b'{"schema":1,"display_fingerprint":"bad"}']:
            self.assertIsNone(dispatch.live_deployment(Mock(return_value=(200, content))))
        value = 'e' * 64
        request = Mock(return_value=(200, json.dumps({'schema': 1, 'display_fingerprint': value}).encode()))
        self.assertEqual(dispatch.live_deployment(request)['display_fingerprint'], value)
        self.assertEqual(request.call_args.args[0].full_url, dispatch.PRODUCTION_MANIFEST)

    def test_redirects_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'Redirects'):
            dispatch.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://attacker.example')


if __name__ == '__main__':
    unittest.main()
