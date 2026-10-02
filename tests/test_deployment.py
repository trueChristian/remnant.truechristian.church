"""Offline website deployment and recovery state machine tests."""
import json
from pathlib import Path
import sys
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

    def tearDown(self):
        self.temp.cleanup()

    def test_duplicate_output_is_skipped_but_force_recovery_is_available(self):
        first = deployment.deployment_plan(self.output, self.report)
        self.assertTrue(first['changed'])
        self.assertFalse(deployment.deployment_plan(self.output, self.report, previous=first)['changed'])
        self.assertTrue(deployment.deployment_plan(self.output, self.report, previous=first, force=True)['changed'])

    def test_stale_cdn_marker_cannot_suppress_a_new_revert_commit(self):
        previous = deployment.deployment_plan(self.output, self.report)
        self.report['sources']['english']['revision'] = 'f' * 40
        # Display can legitimately return to historical bytes at a new commit.
        self.assertTrue(deployment.deployment_plan(self.output, self.report, previous=previous)['changed'])

    def test_provenance_only_changes_do_not_trigger_deployment(self):
        before = deployment.display_fingerprint(self.output)
        (self.output / 'build-report.json').write_text('{"time": "later"}')
        (self.output / 'deployment.json').write_text('{"revision": "new"}')
        self.assertEqual(before, deployment.display_fingerprint(self.output))

    def test_degraded_english_and_recovery_are_new_display_snapshots(self):
        (self.output / 'af.html').write_text('<h1>Afrikaans</h1>')
        ready = deployment.deployment_plan(self.output, self.report)
        (self.output / 'af.html').unlink()
        self.report['export']['translation_status'] = 'failed'
        failed = deployment.deployment_plan(self.output, self.report, previous=ready)
        self.assertTrue(failed['changed'])
        self.assertEqual(failed['translation_status'], 'failed')
        (self.output / 'af.html').write_text('<h1>Afrikaans</h1>')
        self.report['export']['translation_status'] = 'ready'
        self.assertTrue(deployment.deployment_plan(self.output, self.report, previous=failed)['changed'])

    def test_unavailable_translation_revision_is_honest_only_when_acquisition_failed(self):
        self.report['sources']['translations'] = {'revision': None, 'acquisition': 'unavailable'}
        self.report['export']['translation_status'] = 'failed'
        self.assertIsNone(deployment.deployment_plan(self.output, self.report)['revisions']['translations'])
        self.report['sources']['translations']['acquisition'] = 'ready'
        with self.assertRaises(ValueError):
            deployment.deployment_plan(self.output, self.report)

    def test_live_marker_network_failure_never_suppresses_a_build(self):
        self.assertIsNone(deployment.live_deployment(Mock(side_effect=TimeoutError())))
        for content in [b'not json', b'[]', b'{"schema":1,"display_fingerprint":"bad"}']:
            self.assertIsNone(deployment.live_deployment(Mock(return_value=(200, content))))
        value = 'e' * 64
        request = Mock(return_value=(200, json.dumps({'schema': 1, 'display_fingerprint': value}).encode()))
        self.assertEqual(deployment.live_deployment(request)['display_fingerprint'], value)
        self.assertEqual(request.call_args.args[0].full_url, deployment.PRODUCTION_MANIFEST)

    def test_redirects_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'Redirects'):
            deployment.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://attacker.example')


if __name__ == '__main__':
    unittest.main()
