"""Locale-aware homepage payload contracts and editorial provenance."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build import Site
from test_site import fixture, I, J


class HomePayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.model, self.locales, self.routes, self.theme, self.output = fixture(Path(self.temp.name), count=12)

    def tearDown(self):
        self.temp.cleanup()

    def render(self, tag):
        site = Site(self.model, self.locales, self.routes, self.theme, self.output, {})
        site.home(tag)
        text = (self.output / tag / 'index.html').read_text()
        from check_site import PageParser
        config = PageParser(f'/{tag}/', text).page.config
        return text, json.loads((self.output / config['homeData'].lstrip('/')).read_text())

    def test_pair_uses_source_section_and_uuid_not_translated_title(self):
        editor = self.model['articles']['en'][0]
        editor.update(title='Opening the Ancient Wells', section='From the EDITOR')
        other = self.model['articles']['en'][1]
        other.update(title='Questions & Answers and Letters to the Editor', section=None)
        _, en = self.render('en')
        _, af = self.render('af')
        for data in (en, af):
            self.assertEqual([(row['id'], row['articleId']) for row in data['features']], [(I, editor['id'])])
            self.assertIn(self.routes['issues'][data['locale']][I], data['features'][0]['html'])
            self.assertNotIn(self.routes['issues'][data['locale']][J], data['features'][0]['html'])
        self.assertIn('Afrikaanse opskrif', af['features'][0]['html'])
        self.assertNotIn('Opening the Ancient Wells', af['features'][0]['html'])

    def test_archive_precedes_latest_then_categories_without_latest_hero_labels(self):
        text, data = self.render('en')
        self.assertLess(text.index('data-home-feature'), text.index('data-home-archive'))
        self.assertLess(text.index('data-home-archive'), text.index('data-home-latest'))
        self.assertLess(text.index('data-home-latest'), text.index('data-home-categories'))
        hero = text.split('data-home-feature', 1)[1].split('</section>', 1)[0]
        self.assertNotIn('Latest articles', hero)
        self.assertNotIn('Latest issue', hero)
        self.assertTrue(set(data['latestIds']).isdisjoint(row['id'] for row in data['articles']))
        self.assertEqual(len(data['latestIds']), 6)

    def test_empty_locale_uses_real_issue_links_and_localized_notice(self):
        text, data = self.render('fr')
        self.assertEqual(data['articles'], [])
        self.assertTrue(all(row['articleId'] is None for row in data['features']))
        self.assertIn(self.locales['fr']['ui']['coming_soon'], text)
        for row in data['features']:
            self.assertIn(self.routes['issues']['fr'][row['id']], row['html'])
            self.assertIn(self.routes['issues']['en'][row['id']], row['html'])

    def test_tiny_locale_keeps_available_archive_without_duplicate_ids(self):
        text, data = self.render('af')
        self.assertEqual(len(data['articles']), 1)
        self.assertEqual(data['latestIds'], [])
        self.assertIn('data-home-archive', text)

    def test_preview_contains_no_article_body_and_has_stable_digest(self):
        _, data = self.render('en')
        for row in data['articles']:
            self.assertEqual(set(row), {'id', 'issueId', 'html'})
            self.assertNotIn('data-article-id=', row['html'])
        first, _ = self.render('en')
        second, _ = self.render('en')
        self.assertEqual(first, second)
