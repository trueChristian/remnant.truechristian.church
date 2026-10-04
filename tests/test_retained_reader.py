"""Small reader/Markdown regressions for truthful retained-publication notes.

These fixtures call article_page directly; they never build the complete site,
read a real source checkout, fetch content, or change a source repository.
"""
import copy
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from build import Site
from i18n import UI_KEYS, load_locales
from routes import initialize_routes


ROOT = Path(__file__).resolve().parents[1]
A = '00000000-0000-4000-8000-000000000001'
I = '00000000-0000-4000-8000-000000000002'
ORIGINAL, DEPLOYED, CURRENT = (char * 40 for char in 'abc')
RETAINED_KEYS = {'retained_english', 'retained_translation_stale',
                 'retained_translation_removed', 'retained_source_link'}
AI_BODY = (f'<article data-article-id="{A}">\r\n'
           '<p>Goedgekeurde woorde: café &amp; 信仰.</p>\r\n'
           '<p><em>Presiese beklemtoning</em> bly behoue.</p>\r\n</article>\r\n')
HUMAN_BODY = (f'<article data-article-id="{A}">\r\n'
              '<p>Menslik hersiene woorde: café &amp; 信仰.</p>\r\n'
              '<p><strong>Presiese redaksionele keuse</strong> bly behoue.</p>\r\n</article>\r\n')


class RetentionNoteParser(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.notes, self.current = [], None
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'aside' and 'data-retained-publication' in attributes:
            self.current = {'status': attributes['data-retained-publication'], 'text': [], 'links': []}
        if tag == 'a' and self.current is not None:
            self.current['links'].append(attributes.get('href'))

    def handle_data(self, data):
        if self.current is not None:
            self.current['text'].append(data)

    def handle_endtag(self, tag):
        if tag == 'aside' and self.current is not None:
            self.current['text'] = ''.join(self.current['text'])
            self.notes.append(self.current)
            self.current = None


def readable_markdown(value):
    return re.sub(r'\\([\\`*_{}\[\]<>#!|~.()+\-=])', r'\1', unescape(value))


class RetainedReaderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.all_locales = load_locales(ROOT / 'locales')
        self.fixture_number = 0

    def fixture(self, *, tags=('en', 'af'), status='stale', human=False,
                human_notice=False, english_removed=False):
        self.fixture_number += 1
        root = self.root / str(self.fixture_number)
        locales = {tag: copy.deepcopy(self.all_locales[tag]) for tag in tags}
        category_id = next(iter(locales['en']['categories']))
        category = {'id': category_id, **locales['en']['categories'][category_id]}
        issue = {'id': I, 'slug': 'summer-2024', 'publication': 'The Heartbeat of the Remnant',
                 'date': {'year': 2024, 'season': 'Summer', 'precision': 'season'}}
        english = {'id': A, 'issue_id': I, 'issue': copy.deepcopy(issue), 'sequence': 1,
                   'title': 'Last published original' if english_removed else 'Current original',
                   'subtitle': None, 'section': '', 'byline': {'raw': 'Printed Author'},
                   'source_pages': {'start': 3, 'end': 5},
                   'categories': {'primary': category_id, 'additional': []},
                   'topics': [], 'images': [], 'locale': 'en', 'language': 'en', 'direction': 'ltr',
                   'human_reviewed': True, 'ai_notice_required': False,
                   'source_revision': DEPLOYED if english_removed else CURRENT,
                   'text': 'Exact English words.', 'excerpt': 'Exact English words.',
                   'html': f'<article data-article-id="{A}"><p>Exact English words.</p></article>'}
        if english_removed:
            english['retention'] = {'status': 'source_removed', 'kind': 'english', 'source_revision': DEPLOYED}
        english['source_metadata'] = {'id': A, 'byline': copy.deepcopy(english['byline'])}
        articles = {'en': [english]}
        for tag in tags:
            if tag == 'en':
                continue
            article = copy.deepcopy(english)
            article.update(locale=tag, language=tag, direction=locales[tag]['meta']['dir'],
                           title='Goedgekeurde titel ' + tag, human_reviewed=human,
                           ai_notice_required=not human, source_revision=ORIGINAL,
                           html=HUMAN_BODY if human else AI_BODY,
                           retention={'status': status, 'kind': 'translation', 'source_revision': ORIGINAL})
            if human:
                article.update(human_edit={'commit': 'd' * 40, 'author': 'Repository Editor',
                                           'email': 'editor@example.test', 'time': '2026-10-01T12:00:00+00:00'},
                               notice_present=human_notice)
            if not human or human_notice:
                kind = 'human' if human else 'ai'
                article['html'] += (
                    f'<aside data-translation-notice="{kind}" lang="{tag}">\n'
                    f'<p>{locales[tag]["ui"]["english_authoritative"]} '
                    f'<a href="/en/articles/{A}/">{locales[tag]["ui"]["read_english"]}</a></p>\n</aside>')
            article['notice_count'] = int(not human or human_notice)
            articles[tag] = [article]
        model = {'issues': [issue], 'categories': [category], 'topics': [], 'series': [], 'articles': articles}
        routes = initialize_routes(model, locales, root / 'routes.json', update=True)
        footer = root / 'theme/src/html/site-footer.html'
        footer.parent.mkdir(parents=True, exist_ok=True)
        footer.write_text('<footer data-tcc-directory-footer>Archive footer</footer>', encoding='utf-8')
        site = Site(model, locales, routes, root / 'theme', root / 'output', {})
        return site

    def render(self, site, tag):
        article = site.articles[tag][0]
        source_html = article['html']
        site.article_page(tag, article)
        reader = (site.output / article['url'].lstrip('/') / 'index.html').read_bytes().decode('utf-8')
        markdown = (site.output / article['markdown_url'].lstrip('/')).read_bytes().decode('utf-8')
        self.assertEqual(article['html'], source_html)
        return article, reader, markdown

    def assert_note(self, site, tag, article, reader, markdown, key, revision):
        expected = site.ui(tag, key)
        source_label = site.ui(tag, 'retained_source_link')
        source_url = f'https://github.com/trueChristian/berean-voice/blob/{revision}/content/articles/{A}.html'
        notes = RetentionNoteParser(reader).notes
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['status'], article['retention']['status'])
        self.assertEqual(notes[0]['links'], [source_url])
        self.assertEqual(notes[0]['text'], expected + ' ' + source_label)
        portable = readable_markdown(markdown)
        self.assertIn(expected, portable)
        self.assertIn(source_label, portable)
        self.assertIn('](<' + source_url + '>)', portable)
        self.assertLess(portable.index(expected), portable.index(source_url))
        for other in RETAINED_KEYS - {key, 'retained_source_link'}:
            self.assertNotIn(site.ui(tag, other), notes[0]['text'])
            self.assertNotIn(site.ui(tag, other), portable)

    def test_stale_ai_reader_and_markdown_keep_body_notice_and_original_revision(self):
        site = self.fixture()
        article, reader, markdown = self.render(site, 'af')
        self.assert_note(site, 'af', article, reader, markdown, 'retained_translation_stale', ORIGINAL)
        self.assertIn(AI_BODY, reader)
        self.assertEqual(reader.count('data-translation-notice="ai"'), 1)
        self.assertEqual(markdown.count('data-translation-notice="ai"'), 1)
        expected_notice = article['html'][len(AI_BODY):].replace(
            f'/en/articles/{A}/', site.routes['articles']['en'][A])
        self.assertIn(expected_notice, reader)
        self.assertIn(expected_notice, markdown)
        self.assertNotIn(f'href="/en/articles/{A}/"', reader)
        self.assertNotIn(f'href="/en/articles/{A}/"', markdown)
        self.assertIn('Goedgekeurde woorde: café & 信仰.', readable_markdown(markdown))
        self.assertIn('*Presiese beklemtoning* bly behoue.', readable_markdown(markdown))
        self.assertLess(reader.index('data-retained-publication="stale"'), reader.index(AI_BODY))

    def test_removed_ai_translation_and_english_have_distinct_truthful_source_links(self):
        site = self.fixture(status='source_removed', english_removed=True)
        english, english_reader, english_markdown = self.render(site, 'en')
        translated, reader, markdown = self.render(site, 'af')
        self.assert_note(site, 'en', english, english_reader, english_markdown, 'retained_english', DEPLOYED)
        self.assert_note(site, 'af', translated, reader, markdown, 'retained_translation_removed', ORIGINAL)
        self.assertIn(english['html'], english_reader)
        self.assertIn('Exact English words.', readable_markdown(english_markdown))
        self.assertIn(AI_BODY, reader)
        self.assertNotIn('data-translation-notice', english_reader)
        self.assertNotIn('data-translation-notice', english_markdown)
        self.assertIn(f'href="{site.routes["articles"]["en"][A]}"', markdown)

    def test_human_body_and_optional_human_notice_survive_both_retention_states(self):
        for status in ('stale', 'source_removed'):
            for has_notice in (False, True):
                with self.subTest(status=status, human_notice=has_notice):
                    site = self.fixture(status=status, human=True, human_notice=has_notice,
                                        english_removed=status == 'source_removed')
                    article, reader, markdown = self.render(site, 'af')
                    key = 'retained_translation_stale' if status == 'stale' else 'retained_translation_removed'
                    self.assert_note(site, 'af', article, reader, markdown, key, ORIGINAL)
                    self.assertIn(HUMAN_BODY, reader)
                    self.assertNotIn('data-translation-notice="ai"', reader)
                    self.assertNotIn('data-translation-notice="ai"', markdown)
                    self.assertEqual(reader.count('data-translation-notice="human"'), int(has_notice))
                    self.assertEqual(markdown.count('data-translation-notice="human"'), int(has_notice))
                    self.assertIn('Menslik hersiene woorde: café & 信仰.', readable_markdown(markdown))
                    self.assertIn('**Presiese redaksionele keuse** bly behoue.', readable_markdown(markdown))
                    self.assertTrue(article['human_reviewed'])
                    self.assertFalse(article['ai_notice_required'])
                    if has_notice:
                        notice = article['html'][len(HUMAN_BODY):].replace(
                            f'/en/articles/{A}/', site.routes['articles']['en'][A])
                        self.assertIn(notice, reader)
                        self.assertIn(notice, markdown)

    def test_current_english_has_no_historical_retention_note(self):
        site = self.fixture()
        article, reader, markdown = self.render(site, 'en')
        self.assertEqual(RetentionNoteParser(reader).notes, [])
        self.assertNotIn('retained_notice', article)
        self.assertNotIn('github.com/trueChristian/berean-voice/blob/', reader)
        self.assertNotIn('github.com/trueChristian/berean-voice/blob/', markdown)

    def test_all_locales_require_and_render_each_retention_label(self):
        self.assertTrue(RETAINED_KEYS <= UI_KEYS)
        self.assertGreaterEqual(len(self.all_locales), 21)
        for tag, locale in self.all_locales.items():
            with self.subTest(locale=tag):
                for key in RETAINED_KEYS:
                    self.assertIsInstance(locale['ui'][key], str)
                    self.assertTrue(locale['ui'][key].strip())
                self.assertEqual(len({locale['ui'][key] for key in RETAINED_KEYS}), 4)
        for status in ('stale', 'source_removed'):
            site = self.fixture(tags=tuple(self.all_locales), status=status,
                                english_removed=status == 'source_removed')
            for tag in self.all_locales:
                with self.subTest(locale=tag, status=status):
                    article, reader, markdown = self.render(site, tag)
                    if tag == 'en' and status == 'stale':
                        self.assertEqual(RetentionNoteParser(reader).notes, [])
                        continue
                    key = ('retained_english' if tag == 'en' else
                           ('retained_translation_stale' if status == 'stale' else 'retained_translation_removed'))
                    self.assert_note(site, tag, article, reader, markdown, key,
                                     DEPLOYED if tag == 'en' else ORIGINAL)
                    if tag != 'en':
                        self.assertIn(AI_BODY, reader)
                        self.assertIn(f'href="{site.routes["articles"]["en"][A]}"', markdown)


if __name__ == '__main__':
    unittest.main()
