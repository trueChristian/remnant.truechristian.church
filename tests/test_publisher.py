"""Original PDF identity and localized issue actions are independently verified."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from publisher import issue_pdf_links, DEFAULT_MAPPING, PUBLISHER_URL
from i18n import load_locales
from test_site import fixture, Site


class PublisherPdfTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(DEFAULT_MAPPING.read_text())
        self.records = self.data['issues']
        self.issues = [{'id': row['issueId'], 'source': {'sha256': row['sourceSha256']}} for row in self.records]

    def test_all_reviewed_issues_have_verified_unique_external_pdf_links(self):
        links = issue_pdf_links(self.issues)
        self.assertEqual(len(links), 65)
        self.assertEqual(len(set(links.values())), 65)
        self.assertEqual(self.data['coverage']['unresolved'], 0)
        self.assertEqual(self.data['coverage']['sourceSha256Matches'], 65)
        self.assertTrue(all(url.startswith('https://bereanvoice.com/wp-content/uploads/') for url in links.values()))

    def test_download_suffixes_are_not_guessed_from_local_names(self):
        renamed = [row for row in self.records if row['verification']['localFilenameHasDownloadSuffix']]
        self.assertEqual(len(renamed), 7)
        self.assertTrue(all(row['sourceFilename'] not in row['pdfUrl'] for row in renamed))

    def test_correct_issue_id_with_changed_source_is_rejected(self):
        self.issues[0]['source']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'no longer matches'):
            issue_pdf_links(self.issues)

    def test_unreviewed_new_issue_does_not_get_a_fabricated_pdf(self):
        self.assertEqual(issue_pdf_links([{'id': 'new-issue'}]), {})

    def test_untrusted_or_unverified_mapping_is_rejected(self):
        for field, value in [('pdfUrl', 'https://example.org/wrong.pdf'), ('sourceSha256', 'bad')]:
            data = copy.deepcopy(self.data)
            data['issues'][0][field] = value
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'mapping.json'; path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    issue_pdf_links(self.issues, path)
        data = copy.deepcopy(self.data); data['issues'][0]['verification']['sha256MatchesSource'] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mapping.json'; path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                issue_pdf_links(self.issues, path)

    def test_all_locales_have_publisher_and_download_labels(self):
        for locale in load_locales().values():
            self.assertTrue(locale['ui']['publisher'])
            self.assertTrue(locale['ui']['download'])

    def test_issue_action_order_and_pdf_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, locales, routes, theme, output = fixture(root)
            original_id = model['issues'][0]['id']
            record = self.records[0]
            model['issues'][0]['id'] = record['issueId']
            model['issues'][0]['source'] = {'sha256': record['sourceSha256']}
            for tag, articles in model['articles'].items():
                for article in articles:
                    if article['issue_id'] == original_id:
                        article['issue_id'] = record['issueId']
            # Routes are not part of PDF resolution; keep this test's fixture URL.
            for tag in locales:
                routes['issues'][tag][record['issueId']] = routes['issues'][tag].pop(original_id)
            site = Site(model, locales, routes, theme, output, {})
            for tag in locales:
                site.issue_page(tag, model['issues'][0])
                page = (output / routes['issues'][tag][record['issueId']].lstrip('/') / 'index.html').read_text()
                actions = page.split('<div class="issue-actions">', 1)[1].split('</div>', 1)[0]
                self.assertLess(actions.index('count-pill'), actions.index(PUBLISHER_URL))
                self.assertLess(actions.index(PUBLISHER_URL), actions.index(record['pdfUrl']))
                self.assertIn(locales[tag]['ui']['publisher'], actions)
                self.assertIn(locales[tag]['ui']['download'], actions)
                self.assertNotIn(' download', actions)

    def test_current_source_inventory_is_fully_covered_when_available(self):
        source = ROOT / '.build/english/catalogue.json'
        if not source.exists():
            self.skipTest('No full source export prepared')
        issues = json.loads(source.read_text())['issues']
        links = issue_pdf_links(issues)
        expected = {issue['id'] for issue in issues}
        self.assertTrue(set(links).issubset(expected))
        manifest = json.loads((ROOT / '.build/english/manifest.json').read_text())
        if manifest['source_revision'] == self.data['sourceCommit']:
            self.assertEqual(set(links), expected)
