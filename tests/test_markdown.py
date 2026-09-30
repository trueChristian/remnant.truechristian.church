from pathlib import Path
import html
import re
import unittest

from scripts.markdown import Tree, generate_markdown, html_to_markdown
from scripts.content import load_content


class MarkdownTests(unittest.TestCase):
    def test_semantic_fixture_exact_expected(self):
        html = '<article><h2>A heading</h2><p>Exact <em>emphasis</em> and <strong>weight</strong>.</p><blockquote><p>Quoted words.</p></blockquote><p class="poem">First line<br>Second line</p><p class="poem">Next stanza</p></article>'
        expected = '## A heading\n\nExact *emphasis* and **weight**\\.\n\n> Quoted words\\.\n\nFirst line  \nSecond line\n\nNext stanza\n'
        self.assertEqual(html_to_markdown(html), expected)

    def test_exact_notice_is_never_rewritten(self):
        notice = '<aside data-translation-notice="ai" lang="af">\n  <p>Presiese kennisgewing.</p>\n\n\n  <a href="/en/articles/id/">Engels</a>\n</aside>'
        self.assertIn(notice, html_to_markdown('<article><p>Body</p></article>' + notice))

    def test_tables_spans_underline_superscripts_and_typed_lists_preserved(self):
        for fragment in ['<table><tr><th colspan="2">Title</th></tr><tr><td>A</td><td>B</td></tr></table>', '<u>Underlined</u>', '<sup>1</sup>', '<ol type="i"><li>First</li><li>Second</li></ol>', '<h2 id="footnotes">Notes</h2>', '<pre>A\n\n\n  B</pre>']:
            self.assertIn(fragment, html_to_markdown('<article>' + fragment + '</article>'))

    def test_nested_lists_and_ordered_start(self):
        result = html_to_markdown('<article><ol start="3"><li>One<ul><li>Nested</li></ul></li><li>Two</li></ol></article>')
        self.assertIn('3. One', result)
        self.assertIn('   - Nested', result)
        self.assertIn('4. Two', result)

    def test_images_captions_and_absolute_url(self):
        result = html_to_markdown('<article><figure><img src="/images/p.jpg" alt="Exact image"><figcaption>An exact caption.</figcaption></figure></article>', 'https://example.test/en/faith/title/')
        self.assertIn('![Exact image](<https://example.test/images/p.jpg>)', result)
        self.assertIn('An exact caption\\.', result)

    def test_special_punctuation_never_becomes_unintended_markdown(self):
        result = html_to_markdown('<article><p># not a heading; [not a link]; 1. source; &amp;copy;</p></article>')
        self.assertIn(r'\# not a heading', result)
        self.assertIn(r'\[not a link\]', result)
        self.assertIn(r'1\. source', result)
        self.assertIn('&amp;copy;', result)

    def test_emphasis_keeps_meaningful_boundary_spaces(self):
        self.assertEqual(html_to_markdown('<article><p>A<em> word </em>B</p></article>'), 'A *word* B\n')

    def test_reader_metadata_and_only_actual_issue_facts(self):
        article = {'id': 'stable-id', 'locale': 'en', 'title': 'Printed title', 'subtitle': 'A subtitle', 'section': 'A section', 'byline': {'raw': 'Printed Author\nPrinted Location'}, 'source_pages': {'start': 2, 'end': 4}, 'issue': {'publication': 'The Heartbeat of the Remnant', 'issue_number': None, 'source': {'filename': 'issue.pdf'}}, 'html': '<article><p>Complete article.</p></article>', 'images': [{'public_path': '/images/a.jpg', 'alt': 'Image', 'credit': 'Printed Photo Credit'}]}
        result = generate_markdown(article, 'https://example.test/en/faith/printed-title/', 'Summer 2024')
        for value in ['# Printed title', 'A subtitle', 'A section', 'Printed Author  \nPrinted Location', 'The Heartbeat of the Remnant, Summer 2024', '2–4', 'Printed Photo Credit', 'Complete article\\.']:
            self.assertIn(value, result)
        self.assertNotIn('Issue number:', result)
        self.assertNotIn('2024-07-01', result)
        self.assertNotIn('https://example.test/issue.pdf', result)
        qualified = generate_markdown(article, 'https://example.test/en/article/', 'The Heartbeat of the Remnant, Summer 2024')
        self.assertEqual(qualified.count('The Heartbeat of the Remnant'), 1)

    def test_missing_title_fallback_never_mutates_source(self):
        article = {'title': None, 'locale': 'en', 'html': '<article><p>Body</p></article>', 'images': []}
        self.assertTrue(generate_markdown(article, 'https://example.test/', '2007').startswith('# [Untitled article]'))
        self.assertIsNone(article['title'])

    def test_null_byline(self):
        article = {'title': 'Title', 'locale': 'en', 'byline': None, 'html': '<article><p>Body</p></article>', 'images': []}
        self.assertIn('Body', generate_markdown(article, 'https://example.test/', '2007'))

    def test_all_available_articles_generate_complete_reader_markdown(self):
        english = Path('.build/english')
        if not english.exists():
            self.skipTest('Optional real-export verification; fixture tests always run')
        model = load_content(english, Path('.build/translations'))
        for locale, articles in model['articles'].items():
            for article in articles:
                with self.subTest(locale=locale, article=article['id']):
                    result = generate_markdown(article, f"https://remnant.truechristian.church/{locale}/articles/{article['id']}/", article['issue']['date']['label'])
                    self.assertTrue(result.startswith('# '))
                    self.assertIn(article['issue']['publication'], result)
                    if article['ai_notice_required']:
                        notice = re.search(r'<aside\b[^>]*data-translation-notice="ai".*?</aside>', article['html'], re.S).group(0)
                        self.assertIn(notice, result)

    def test_all_available_archive_fragments_convert(self):
        root = Path('.build/english/content/articles')
        if not root.exists():
            self.skipTest('Optional real-export verification; fixture tests always run')
        files = list(root.glob('*.html'))
        self.assertTrue(files)
        for path in files:
            with self.subTest(article=path.stem):
                result = html_to_markdown(path.read_text(), 'https://remnant.truechristian.church/en/example/')
                self.assertTrue(result.strip())
                self.assertNotIn('\x00RAW', result)
                # Every original visible text leaf must survive intact in the
                # portable representation, including raw-HTML structures. The
                # exact semantic fixtures above verify lineation and wrappers.
                unescaped = re.sub(r'\\([\\`*_{}\[\]<>#!|~.()+\-=])', r'\1', html.unescape(result))
                portable = re.sub(r'\s+', ' ', unescaped)
                def leaves(node):
                    if isinstance(node, str):
                        yield node
                    else:
                        for child in node.children:
                            yield from leaves(child)
                for leaf in leaves(Tree(path.read_text()).root):
                    phrase = re.sub(r'\s+', ' ', leaf).strip()
                    if phrase:
                        self.assertIn(phrase, portable)


if __name__ == '__main__':
    unittest.main()
