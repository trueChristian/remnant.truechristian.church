"""Presentation-only policies for the second reviewed article-layout batch."""
import copy
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from article_figures import arrange_article_figures, load_figure_rules, FigureElements

RULES = load_figure_rules(Path(__file__).resolve().parents[1] / 'data/article-image-layouts.json')
KIDS = '498f95c3-9cf2-4b3d-97c6-9d4d15b08972'
GOSPEL = '54d5a0ed-09dc-4e75-8447-b9e3ad2db302'
PAINFUL = 'e2717533-f2de-48a9-94a8-feee73a69a6f'
LETTERS = 'ff756543-8b73-4182-a901-596bfa199152'
VESSEL = '65cde85d-5f09-47af-ac75-0a3ea061d639'


def figure(identity, number, extension='png', caption=''):
    return (f'<figure><img src="/images/articles/{identity}-{number}.{extension}" alt="Unchanged &amp; original">'
            f'{caption}</figure>')


def article(identity, body):
    return f'<article data-article-id="{identity}">\n{body}\n</article>'


def nodes(source, tag):
    return [source[node.start:node.end] for node in FigureElements(source).elements if node.tag == tag]


class ReviewedOpeningTests(unittest.TestCase):
    def preserved(self, source, result):
        self.assertEqual(nodes(source, 'p'), nodes(result, 'p'))
        self.assertEqual(sorted(nodes(source, 'img')), sorted(nodes(result, 'img')))
        self.assertEqual(sorted(nodes(source, 'figcaption')), sorted(nodes(result, 'figcaption')))
        self.assertEqual(source.count('<br'), result.count('<br'))
        self.assertEqual(arrange_article_figures(result, RULES), result)

    def test_globe_stands_alone_while_the_prose_figure_follows_the_epigraph(self):
        cases = [('5a6259c0-5450-4502-b504-8db7b37e4cc1', 1, 2),
                 ('1fb1624e-5fee-4f45-9bb9-73728210ff1f', 1, 2),
                 ('635b775e-3815-4c17-9c75-bdab9ea88661', 2, 1)]
        for identity, globe, illustration in cases:
            source = article(identity, figure(identity, illustration, 'jpg') + figure(identity, globe) +
                             '<blockquote><p>A complete epigraph.<br>A reference.</p></blockquote>'
                             '<h2>Opening heading</h2><p>Opening prose remains complete.</p>')
            result = arrange_article_figures(source, RULES)
            self.preserved(source, result)
            parsed = FigureElements(result)
            images = [node for node in parsed.elements if node.tag == 'img']
            self.assertIn(f'-{globe}.png', images[0].attrs['src'])
            self.assertIn('article-figure--standalone', images[0].parent.attrs['class'])
            self.assertNotIn('article-gallery', result)
            self.assertLess(result.index('</h2>'), result.index(f'-{illustration}.jpg'))

    def test_goats_remain_a_distinct_centered_pair_before_child_and_prose(self):
        source = article(KIDS, figure(KIDS, 1) + figure(KIDS, 2) + figure(KIDS, 3, 'jpg') + '<p>First paragraph.</p>')
        result = arrange_article_figures(source, RULES)
        self.preserved(source, result)
        self.assertIn('article-gallery--paired', result)
        self.assertLess(result.index('</div>'), result.index(f'{KIDS}-3.jpg'))

    def test_gospel_pair_keeps_both_complete_figures_between_paragraphs_two_and_three(self):
        source = article(GOSPEL, figure(GOSPEL, 1) + figure(GOSPEL, 2) +
                         '<blockquote><p>Opening Scripture.</p></blockquote>'
                         '<p>First paragraph.</p><p>Second paragraph.</p><p>Third paragraph.</p>' +
                         figure(GOSPEL, 3, 'jpg', '<figcaption><strong>Full caption<br>with its second line.</strong></figcaption>'))
        result = arrange_article_figures(source, RULES)
        self.preserved(source, result)
        self.assertEqual(result.count('article-gallery--native'), 1)
        self.assertLess(result.index('Second paragraph.'), result.index(f'{GOSPEL}-1.png'))
        self.assertLess(result.index(f'{GOSPEL}-3.jpg'), result.index('Third paragraph.'))
        self.assertLess(result.index(f'{GOSPEL}-2.png'), result.index('<blockquote>'))

    def test_incomplete_hidden_nested_or_repeated_gallery_is_not_recomposed(self):
        normal = article(GOSPEL, figure(GOSPEL, 1) + figure(GOSPEL, 2) +
                         '<p>First.</p><p>Second.</p>' + figure(GOSPEL, 3, 'jpg'))
        changed = [normal.replace(figure(GOSPEL, 3, 'jpg'), ''),
                   normal.replace('<figure>', '<figure hidden>', 1),
                   normal.replace(figure(GOSPEL, 1), '<aside>' + figure(GOSPEL, 1) + '</aside>'),
                   normal.replace(figure(GOSPEL, 1), figure(GOSPEL, 1) * 2),
                   normal.replace('<p>Second.</p>', '')]
        for source in changed:
            self.assertNotIn('article-gallery--native', arrange_article_figures(source, RULES))

    def test_flower_moves_after_opening_paragraph_but_before_unchanged_bullets(self):
        listing = '<ul><li>First <em>request</em>.</li><li>Second request.</li></ul>'
        source = article(LETTERS, figure(LETTERS, 1) + figure(LETTERS, 2, 'jpg') + '<p>Introductory paragraph.</p>' + listing)
        result = arrange_article_figures(source, RULES)
        self.preserved(source, result)
        self.assertLess(result.index('Introductory paragraph.'), result.index(f'{LETTERS}-2.jpg'))
        self.assertLess(result.index(f'{LETTERS}-2.jpg'), result.index('<ul'))
        self.assertEqual(nodes(source, 'ul'), [part.replace(' data-reader-list-flow=""', '') for part in nodes(result, 'ul')])
        self.assertNotIn('article-gallery', result)

    def test_missing_or_hidden_list_does_not_move_the_flower(self):
        for listing in ['', '<ul hidden><li>Hidden list.</li></ul>']:
            source = article(LETTERS, figure(LETTERS, 1) + figure(LETTERS, 2, 'jpg') + '<p>Original opening.</p>' + listing)
            result = arrange_article_figures(source, RULES)
            self.assertLess(result.index(f'{LETTERS}-2.jpg'), result.index('Original opening.'))

    def test_only_the_approved_logo_acquires_bounded_enlargement_metadata(self):
        source = article(PAINFUL, figure(PAINFUL, 1, 'jpg') + figure(PAINFUL, 2) + '<p>First paragraph.</p>')
        result = arrange_article_figures(source, RULES)
        self.preserved(source, result)
        self.assertEqual(result.count('data-reader-enlarge="150"'), 1)
        self.assertIn('data-source-width="99" data-source-height="48"', result)
        self.assertEqual(nodes(source, 'img'), nodes(result, 'img'))

    def test_continuous_poem_changes_neither_stanza_nodes_nor_original_image_order(self):
        source = article(VESSEL, '<p class="poem">First line<br>Second line</p>' +
                         ''.join(figure(VESSEL, n, 'jpg' if n == 3 else 'png') +
                                 f'<p class="poem">Stanza {n}<br>Retained line</p>' for n in [1, 2, 3]))
        result = arrange_article_figures(source, RULES)
        self.preserved(source, result)
        self.assertIn('data-reader-continuous-verse', result)
        self.assertEqual(result.count('class="article-verse-row"'), 3)
        self.assertEqual(nodes(source, 'img'), nodes(result, 'img'))
        for changed in [source.replace('class="poem"', 'class="ordinary"', 1),
                        source.replace('<p class="poem">', '<p class="poem" hidden>', 1),
                        source.replace(figure(VESSEL, 2), ''),
                        source.replace(figure(VESSEL, 1), figure(VESSEL, 1) * 2),
                        source.replace('First line', 'First line<img src="/extra.png" alt="">')]:
            self.assertNotIn('data-reader-continuous-verse', arrange_article_figures(changed, RULES))

    def test_new_policy_values_reject_ambiguous_or_unsafe_configurations(self):
        policies = [
            {'list_positions': []}, {'list_positions': {'flower.jpg': True}},
            {'list_positions': {'../flower.jpg': 1}},
            {'list_positions': {'a.jpg': 1, 'b.jpg': 1}},
            {'list_positions': {'a.jpg': 1}, 'paragraph_positions': {'a.jpg': 1}},
            {'continuous_verse': {'images': ['a.jpg', 'a.jpg']}},
            {'continuous_verse': {'images': ['a.jpg', 'b.jpg']}, 'standalone': ['a.jpg']},
            {'continuous_verse': {'images': ['a.jpg', None]}},
            {'paragraph_gallery': {'images': ['a.jpg', 'b.jpg'], 'widths': [10, False], 'after_paragraph': 2}},
            {'paragraph_gallery': {'images': ['a.jpg', 'b.jpg'], 'widths': [10, 10], 'after_paragraph': 0}},
            {'enlarged_standalone': {'a.jpg': {'width': 150, 'source_size': [99, 48]}}},
            {'standalone': ['a.jpg'], 'enlarged_standalone': {'a.jpg': {'width': 300, 'source_size': [99, 48]}}},
            {'standalone': ['a.jpg'], 'enlarged_standalone': {'a.jpg': {'width': 90, 'source_size': [99, 48]}}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rules.json'
            for policy in policies:
                path.write_text(json.dumps({'version': 1, 'articles': {'fixture': policy}}))
                with self.subTest(policy=policy), self.assertRaises(ValueError):
                    load_figure_rules(path)

    def test_other_articles_never_acquire_these_reviewed_compositions(self):
        source = article('unreviewed', figure('unreviewed', 1) + '<p class="poem">A line<br>Another line</p>')
        result = arrange_article_figures(source, RULES)
        for marker in ['data-reader-continuous-verse', 'article-gallery--native', 'data-reader-enlarge', 'data-reader-list-flow']:
            self.assertNotIn(marker, result)
