"""Keep the real browser suite a source-backed, read-only pull-request check."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/browser-review.yml'


class BrowserReviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text()

    def test_reviews_the_pr_revision_with_independent_cancelable_concurrency(self):
        header = self.workflow.split('\njobs:\n', 1)[0]
        events = header.split('\non:\n', 1)[1].split('\n\n', 1)[0]
        self.assertEqual(events, '  pull_request:')
        self.assertIn("if: github.event_name == 'pull_request'", self.workflow)
        self.assertIn('ref: ${{ github.sha }}', self.workflow)
        self.assertNotRegex(self.workflow, r'(?m)^\s+ref: main\s*$')
        self.assertIn('persist-credentials: false', self.workflow)
        self.assertIn('group: remnant-browser-review-${{ github.event.pull_request.number }}', header)
        self.assertIn('cancel-in-progress: true', header)
        self.assertIn('timeout-minutes: 45', self.workflow)
        self.assertIn('python3 scripts/validate_event.py', self.workflow)

    def test_has_only_read_permissions_and_no_publication_actions(self):
        self.assertEqual(self.workflow.count('permissions:'), 1)
        permissions = self.workflow.split('\npermissions:\n', 1)[1].split('\n\n', 1)[0]
        self.assertEqual(set(permissions.splitlines()), {
            '  contents: read', '  actions: read', '  deployments: read',
        })
        actions = re.findall(r'(?m)^\s+uses: (\S+)', self.workflow)
        self.assertEqual(actions, [
            'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1',
            'actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9',
        ])
        for forbidden in ('pages:', 'id-token:', 'environment:', 'secrets.',
                          'scripts/deployment.py', 'publication_state.py record',
                          'upload-pages-artifact', 'deploy-pages', 'git push'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.workflow)

    def test_uses_one_source_selection_and_the_verified_publication_before_building(self):
        ordered_commands = [
            'python3 scripts/publication_state.py fetch --output .build/published',
            'python3 scripts/poll_sources.py --review --published-deployment .build/published/deployment.json',
            'python3 scripts/prepare_sources.py --selection "$SOURCE_SELECTION"',
            'python3 scripts/check_sources.py --published-deployment .build/published/deployment.json',
            'cp .build/published/scripture/manifest.json .build/scripture-manifest.json',
            'python3 scripts/route_registry.py --published .build/published/routes.json',
            'python3 scripts/build.py --english .build/english --translations .build/translations --theme .build/theme --languages .build/languages.json --registry .build/routes.json --output dist',
            'python3 scripts/check_site.py dist --registry .build/routes.json',
            'npx playwright install --with-deps chromium',
            'npm run test:browser',
        ]
        positions = []
        for command in ordered_commands:
            with self.subTest(command=command):
                self.assertEqual(self.workflow.count(command), 1)
                positions.append(self.workflow.index(command))
        self.assertEqual(positions, sorted(positions))
        self.assertIn('id: poll', self.workflow)
        self.assertIn('SOURCE_SELECTION: ${{ steps.poll.outputs.selection }}', self.workflow)
        self.assertIn('GH_TOKEN: ${{ github.token }}', self.workflow)
        self.assertLess(self.workflow.index('run: npm ci'), positions[2])

    def test_runs_the_unfiltered_suite_and_propagates_failures(self):
        commands = re.findall(r'(?m)^\s+run: (.*test:browser.*)$', self.workflow)
        self.assertEqual(commands, ['npm run test:browser'])
        self.assertNotIn('continue-on-error:', self.workflow)
        self.assertNotIn('|| true', self.workflow)
        self.assertNotIn('python3 -m unittest discover', self.workflow)
        self.assertNotIn('node --test', self.workflow)

    def test_retains_results_and_provenance_even_when_checks_fail(self):
        upload = self.workflow.split('      - name: Retain browser results', 1)[1]
        self.assertIn('if: always()', upload)
        self.assertIn('include-hidden-files: true', upload)
        for path in ('.test-output/', '.build/event-report.json', '.build/poll-report.json',
                     '.build/source-report.json', '.build/site-build-report.json',
                     '.build/route-registry-report.json', '.build/scripture-report.json',
                     '.build/published/receipt.json'):
            with self.subTest(path=path):
                self.assertIn(path, upload)
        self.assertNotRegex(upload, r'(?m)^\s+dist/\s*$')
        self.assertNotRegex(upload, r'(?m)^\s+\.build/\s*$')


if __name__ == '__main__':
    unittest.main()
