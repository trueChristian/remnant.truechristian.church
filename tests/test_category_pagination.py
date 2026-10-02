"""Language-prefix redirects preserve category identity through pagination."""
from pathlib import Path
import tempfile
import unittest

from tests.test_site import fixture
from check_site import PageParser


class CategoryPaginationTests(unittest.TestCase):
    def test_target_without_second_page_redirects_to_same_localized_category(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, locales, routes, theme, output = fixture(Path(temporary), count=27)
            identity = model['categories'][0]['id']
            english = routes['categories']['en'][identity]
            requested = '/af/' + english.split('/', 2)[2] + 'page/2/'
            source = (output / requested.lstrip('/') / 'index.html').read_text()
            page = PageParser(requested, source).page
            self.assertEqual(page.redirect, routes['categories']['af'][identity])
            self.assertTrue(page.noindex)
            self.assertEqual(page.article_ids, [])

    def test_existing_english_second_page_remains_the_canonical_listing(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, locales, routes, theme, output = fixture(Path(temporary), count=27)
            identity = model['categories'][0]['id']
            route = routes['categories']['en'][identity] + 'page/2/'
            page = PageParser(route, (output / route.lstrip('/') / 'index.html').read_text()).page
            self.assertIsNone(page.redirect)
            self.assertTrue(page.noindex)


if __name__ == '__main__':
    unittest.main()
