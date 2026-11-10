"""Reader-only galleries retain source images, captions and article semantics."""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from article_figures import arrange_article_figures, FigureElements, load_figure_rules

A = '00000000-0000-4000-9000-000000000001'
CONTOUR = {'image': 'arch.jpg', 'width': 100, 'height': 40, 'text_start': 18,
           'edges': [[0, 50, 50], [10, 50, 50], [20, 20, 80], [40, 0, 100]]}
PARAGRAPH_PAIR = [{'image': 'family.jpg', 'side': 'end'}, {'image': 'boy.jpg', 'side': 'start'}]


def image(name, extra=''):
    return f'<img src="/images/articles/{name}.jpg" alt="Original &amp; caption"{extra}>'


def figure(name, caption='', extra=''):
    return f'<figure{extra}>{image(name)}{caption}</figure>'


def article(content, extra=''):
    return f'<article data-article-id="{A}"{extra}>{content}</article>'


def galleries(html):
    return [node for node in FigureElements(html).elements if node.tag == 'div' and 'article-gallery' in node.attrs.get('class', '').split()]


class ArticleFigureTests(unittest.TestCase):
    def test_reviewed_paragraph_positions_preserve_complete_figures_and_source_text(self):
        quote = '<blockquote><p>First line<br>Second line<br>Reference</p></blockquote>'
        paragraphs = ['<p>First ordinary paragraph.</p>', '<p>Second ordinary paragraph.</p>',
                      '<p><strong>Original announcement<br>Original date</strong></p>']
        picture = figure('picture', '<figcaption>Original <em>caption</em>.</figcaption>')
        for content, position in [(picture + '\n' + quote + ''.join(paragraphs), 1),
                                  (''.join(paragraphs[:2]) + picture + '\n' + paragraphs[2], 1),
                                  (picture + '\n' + ''.join(paragraphs), 3)]:
            source = article(content)
            rules = {A: {'paragraph_positions': {'picture.jpg': position}}}
            output = arrange_article_figures(source, rules)
            root = next(node for node in FigureElements(output).elements if node.tag == 'article')
            target = [node for node in root.children if node.tag == 'p'][position - 1]
            moved = root.children[root.children.index(target) - 1]
            self.assertEqual(moved.tag, 'figure')
            self.assertEqual(output[moved.opening_end:moved.closing_start],
                             picture[picture.index('>') + 1:picture.rindex('</figure>')])
            self.assertEqual(re.findall(r'<p\b[^>]*>.*?</p>', output),
                             re.findall(r'<p\b[^>]*>.*?</p>', source))
            self.assertEqual(re.findall(r'<img\b[^>]*>', output), re.findall(r'<img\b[^>]*>', source))
            self.assertEqual(arrange_article_figures(output, rules), output)

    def test_paragraph_positions_decline_missing_repeated_or_nested_figures(self):
        rules = {A: {'paragraph_positions': {'picture.jpg': 2}}}
        prose = '<p>First paragraph.</p><p>Second paragraph.</p>'
        for content in [figure('picture') + '<p>Only one paragraph.</p>',
                        figure('picture') + prose + figure('picture'),
                        '<section>' + figure('picture') + '</section>' + prose,
                        '<figure>' + image('picture') + '<aside>Other content.</aside></figure>' + prose,
                        figure('picture') + 'Loose visible words.' + prose]:
            source = article(content)
            self.assertEqual(arrange_article_figures(source, rules), arrange_article_figures(source))

    def test_reviewed_opening_verse_quote_keeps_lineation_and_order(self):
        quote = '<blockquote><p><em>First line<br>Second line<br>Reference</em></p></blockquote>'
        picture = figure('picture')
        prose = '<p>Subsequent ordinary prose remains outside the row.</p>'
        source = article(quote + '\n' + picture + '\n' + prose)
        rules = {A: {'verse_quote': ['picture.jpg']}}
        output = arrange_article_figures(source, rules)
        self.assertIn('article-figure--native-verse', output)
        self.assertIn(quote, output)
        self.assertIn(prose, output)
        root = next(node for node in FigureElements(output).elements if node.tag == 'article')
        self.assertEqual([node.tag for node in root.children], ['div', 'p'])
        self.assertEqual([node.tag for node in root.children[0].children], ['div', 'figure'])
        self.assertEqual(re.findall(r'<img\b[^>]*>', output), re.findall(r'<img\b[^>]*>', source))
        self.assertEqual(arrange_article_figures(output, rules), output)
        for content in [quote + '<h2>A boundary</h2>' + picture + prose,
                        '<p>An introduction</p>' + quote + picture + prose,
                        quote + picture + picture + prose,
                        quote.replace('<blockquote>', '<blockquote hidden>') + picture + prose,
                        quote.replace('<br>Second line', '') + picture + prose,
                        quote.replace('</p>', '</p><p>Another paragraph</p>') + picture + prose]:
            self.assertNotIn('article-verse-row', arrange_article_figures(article(content), rules))

    def test_reviewed_verse_and_position_rules_reject_conflicts_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layouts.json'
            valid = {'paragraph_positions': {'picture.jpg': 2}, 'standalone': ['picture.jpg'],
                     'verse_quote': ['another.jpg']}
            path.write_text(json.dumps({'version': 1, 'articles': {A: valid}}))
            self.assertEqual(load_figure_rules(path), {A: valid})
            invalid = [{'paragraph_positions': value} for value in
                       [[], None, {'picture.jpg': 0}, {'picture.jpg': True}, {'picture.jpg': 1.5},
                        {'../picture.jpg': 1}, {'one.jpg': 1, 'two.jpg': 1}]]
            invalid += [{'verse_quote': value} for value in ['picture.jpg', None, ['../picture.jpg']]]
            invalid += [{'verse_quote': ['picture.jpg'], 'standalone': ['picture.jpg']},
                        {'paragraph_positions': {'family.jpg': 1}, 'paragraph_pair': PARAGRAPH_PAIR}]
            for rule in invalid:
                path.write_text(json.dumps({'version': 1, 'articles': {A: rule}}))
                with self.subTest(rule=rule), self.assertRaises(ValueError):
                    load_figure_rules(path)

    def test_illustrated_poem_keeps_stanzas_images_and_captions_in_source_order(self):
        stanza = '<p>First &amp; faithful line.<br>Second line.<br>Third line.</p>'
        closing = '<p>Closing <em>words</em>.<br>Remain exact.<br>Always.</p>'
        caption = '<figcaption>Original credit.</figcaption>'
        source = article('<div class="poem">' + figure('one', caption) + stanza * 2 +
                         figure('two') + stanza + closing + figure('last') + '</div>')
        output = arrange_article_figures(source)
        self.assertEqual(output.count('class="article-verse-row"'), 3)
        self.assertEqual(output.count(stanza), 3)
        self.assertIn(closing, output)
        self.assertEqual(re.findall(r'<img\b[^>]*>|<figcaption>.*?</figcaption>', output),
                         re.findall(r'<img\b[^>]*>|<figcaption>.*?</figcaption>', source))
        self.assertLess(output.index(closing), output.index('last.jpg'))
        self.assertEqual(arrange_article_figures(output), output)

    def test_verse_shapes_and_closing_illustrations_share_the_reader_layout(self):
        for verse in ['<p class="poem">First<br>Second</p>',
                      '<div class="lyrics"><p>First<br>Second</p></div>',
                      '<blockquote class="poem"><p>First<br>Second</p></blockquote>',
                      '<section class="poem"><p>First<br>Second</p></section>',
                      '<p>First<br>Second<br>Third</p>']:
            for content in [figure('one') + verse, verse + figure('one')]:
                output = arrange_article_figures(article(content))
                self.assertEqual(output.count('class="article-verse-row"'), 1)
                self.assertIn(verse, output)
                self.assertEqual(arrange_article_figures(output), output)

    def test_verse_groups_respect_prose_barriers_protected_images_and_galleries(self):
        verse = '<p class="poem">First<br>Second</p>'
        for content in [figure('one') + '<h2>New section</h2>' + verse,
                        figure('one') + '<p>Ordinary prose.</p>' + verse,
                        figure('one') + figure('two') + verse,
                        '<aside class="poem">' + figure('one') + verse + '</aside>',
                        '<blockquote>' + figure('one') + verse + '</blockquote>']:
            self.assertNotIn('article-verse-row', arrange_article_figures(article(content)))
        self.assertNotIn('article-verse-row', arrange_article_figures(article(figure('one') + verse),
                         {A: {'standalone': ['one.jpg']}}))

    def test_reviewed_transparent_padding_preserves_source_and_is_idempotent(self):
        bounds = dict(width=460, height=901, top=384, right=0, bottom=0, left=0)
        rules = {A: {'transparent_padding': {'orchid.jpg': bounds}}}
        caption = '<figcaption>Original caption &amp; credit.</figcaption>'
        source = article(figure('orchid', caption) + '<blockquote>Original quotation.</blockquote>')
        output = arrange_article_figures(source, rules)
        self.assertIn('--article-image-width:460px;--article-image-ratio:460/517', output)
        self.assertIn('--article-image-top:-74.27466151%', output)
        self.assertIn(image('orchid') + '</span>' + caption, output)
        self.assertIn('<blockquote>Original quotation.</blockquote>', output)
        self.assertIn('article-figure--standalone', output)
        self.assertEqual(arrange_article_figures(output, rules), output)
        self.assertNotIn('article-image-window', arrange_article_figures(source, {}))
        for content in [figure('other'), '<figure>' + image('orchid') + image('other') + '</figure>',
                        '<blockquote>' + figure('orchid') + '</blockquote>']:
            self.assertNotIn('article-image-window', arrange_article_figures(article(content), rules))

    def test_transparent_padding_rules_reject_invalid_dimensions_and_conflicts(self):
        bounds = dict(width=460, height=901, top=384, right=0, bottom=0, left=0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layouts.json'
            for changes in [{'top': -1}, {'top': 901}, {'width': 0}, {'left': 460},
                            {'right': 460}, {'bottom': 517}, {'width': True},
                            {'top': 1.5}, {'height': '901'}, {'extra': 1}]:
                rule = {'transparent_padding': {'orchid.png': bounds | changes}}
                path.write_text(json.dumps({'version': 1, 'articles': {A: rule}}))
                with self.assertRaises(ValueError):
                    load_figure_rules(path)
            for padding in [[], {'../orchid.png': bounds}, {'orchid.png': {}}, {'orchid.png': None}]:
                path.write_text(json.dumps({'version': 1, 'articles': {A: {'transparent_padding': padding}}}))
                with self.assertRaises(ValueError):
                    load_figure_rules(path)
            rule = {'transparent_padding': {'orchid.png': bounds}}
            path.write_text(json.dumps({'version': 1, 'articles': {A: rule}}))
            self.assertEqual(load_figure_rules(path), {A: rule})
            rule['paired'] = [['orchid.png', 'other.png']]
            path.write_text(json.dumps({'version': 1, 'articles': {A: rule}}))
            with self.assertRaises(ValueError):
                load_figure_rules(path)

    def test_adjacent_figures_keep_exact_images_captions_comments_and_source_order(self):
        caption = '<figcaption>A <em>faithful</em> caption &amp; credit.</figcaption>'
        source = article('<p>Opening &mdash; words.</p>' + figure('one', caption, ' class="original"') +
                         '\n<!-- between source images -->\n' + figure('two') + '<p>Closing words.</p>')
        output = arrange_article_figures(source)
        self.assertEqual(len(galleries(output)), 1)
        self.assertEqual(re.findall(r'<img\b[^>]*>', output), re.findall(r'<img\b[^>]*>', source))
        self.assertIn(caption, output)
        self.assertIn('<!-- between source images -->', output)
        self.assertLess(output.index('one.jpg'), output.index('two.jpg'))
        self.assertIn('class="article-figure original"', output)
        self.assertIn('</figure></div><p>Closing words.</p>', output)
        self.assertEqual(arrange_article_figures(output), output)

    def test_shared_caption_is_outside_the_image_row_and_original_image_tags_are_intact(self):
        images = image('one', ' width="800" height="400" loading="lazy"') + '\n' + image('two')
        caption = '<figcaption>One shared <strong>caption</strong>.</figcaption>'
        output = arrange_article_figures(article('<figure>' + images + caption + '</figure>'))
        self.assertIn('<div class="article-gallery__images">' + images + '</div>' + caption, output)
        self.assertEqual(arrange_article_figures(output), output)

    def test_reviewed_panels_remain_a_distinct_group_with_physical_source_order(self):
        rules = {A: {'paired': [['left.jpg', 'right.jpg']]}}
        for content in [figure('left') + figure('right'), '<figure>' + image('left') + image('right') + '</figure>']:
            output = arrange_article_figures(article(content, ' dir="rtl"'), rules)
            self.assertIn('article-gallery--paired', output)
            self.assertLess(output.index('left.jpg'), output.index('right.jpg'))
            self.assertIn('dir="rtl"', output)
        # A following ordinary photograph must not join the reviewed composition.
        output = arrange_article_figures(article(figure('left') + figure('right') + figure('other')), rules)
        self.assertEqual([len(group.children) for group in galleries(output)], [2])
        # If a panel disappears in a future source revision, it is not paired
        # with an unrelated neighbour, even in another language.
        output = arrange_article_figures(article(figure('left') + figure('other')), rules)
        self.assertEqual(galleries(output), [])
        self.assertIn('article-figure--standalone', output)

    def test_prose_headings_and_semantic_containers_are_hard_boundaries(self):
        for boundary in ['<p>Text between images.</p>', '<h2>A new section</h2>', 'Actual loose text', '<hr>']:
            self.assertEqual(galleries(arrange_article_figures(article(figure('one') + boundary + figure('two')))), [])
        for container in ['aside', 'blockquote', 'li', 'table', 'div']:
            source = article(f'<{container}>' + figure('one') + figure('two') + f'</{container}>')
            self.assertEqual(arrange_article_figures(source), source)
        source = article('<section>' + figure('one') + figure('two') + '</section>' + figure('three'))
        output = arrange_article_figures(source)
        self.assertEqual(len(galleries(output)), 1)
        self.assertIn('<section class="article-figure-section">', output)
        self.assertIn('</div></section><figure', output)

    def test_paired_dimensions_keep_unequal_panels_at_a_common_scale_without_upscaling(self):
        rules = {A: {'paired': [['left.jpg', 'right.jpg']],
                     'dimensions': {'left.jpg': [1959, 2534], 'right.jpg': [668, 2534]}}}
        source = article('<figure>' + image('left') + image('right') + '</figure>')
        output = arrange_article_figures(source, rules)
        wrapper = next(node for node in FigureElements(output).elements if node.tag == 'div')
        columns = re.search(r'--article-pair-columns:([\d.]+)fr ([\d.]+)fr', wrapper.attrs['style'])
        self.assertAlmostEqual(float(columns[1]) / float(columns[2]), 1959 / 668, places=4)
        width = float(re.search(r'--article-pair-width:([\d.]+)px', wrapper.attrs['style'])[1])
        self.assertAlmostEqual(width, (1959 + 668) * 384 / 2534, places=5)
        rules[A]['dimensions'] = {'left.jpg': [135, 80], 'right.jpg': [123, 77]}
        output = arrange_article_figures(article(figure('left') + figure('right')), rules)
        width = float(re.search(r'--article-pair-width:([\d.]+)px', output)[1])
        self.assertAlmostEqual(width, 135 * 77 / 80 + 123)
        self.assertEqual(re.findall(r'<img\b[^>]*>', source), re.findall(r'<img\b[^>]*>', output))

    def test_only_reviewed_unambiguous_caption_free_split_artwork_can_move(self):
        rules = {A: {'paired': [['left.jpg', 'right.jpg']]}}
        paragraphs = '<p>First paragraph &amp; meaning.</p><p>Second <em>paragraph</em>.</p>'
        source = article(figure('left') + paragraphs + figure('right') + '<p>Last paragraph.</p>')
        output = arrange_article_figures(source, rules)
        self.assertIn('article-gallery--paired', output)
        self.assertLess(output.index('right.jpg'), output.index(paragraphs))
        self.assertEqual(re.findall(r'<p>.*?</p>', source), re.findall(r'<p>.*?</p>', output))
        self.assertEqual(re.findall(r'<img\b[^>]*>', source), re.findall(r'<img\b[^>]*>', output))
        self.assertEqual(arrange_article_figures(output, rules), output)
        for unsafe in [figure('left') + paragraphs + figure('right', '<figcaption>Its own context.</figcaption>'),
                       figure('left') + paragraphs + figure('right') + figure('right'),
                       figure('right') + paragraphs + figure('left'),
                       figure('left') + figure('other') + paragraphs + figure('right'),
                       figure('left') + paragraphs + '<section>' + figure('right') + '</section>',
                       figure('left') + paragraphs + '<figure>' + image('right') + '<p>Image explanation.</p></figure>']:
            result = arrange_article_figures(article(unsafe), rules)
            self.assertNotIn('article-gallery--paired', result)
            self.assertEqual(re.findall(r'<img\b[^>]*>', unsafe), re.findall(r'<img\b[^>]*>', result))

    def test_paragraph_pair_moves_complete_captioned_figures_without_changing_prose(self):
        rules = {A: {'paragraph_pair': PARAGRAPH_PAIR}}
        before = '<p id="before">Earlier &amp; unchanged <em>paragraph</em>.</p>'
        after = '<p id="after">The following paragraph stays second.</p>'
        boy = figure('boy', '<figcaption><strong>Original portrait caption.</strong></figcaption>', ' id="boy" class="source"')
        family = figure('family', '<figcaption><strong>Family &amp; children<br>Original second line.</strong></figcaption>', ' id="family" class="source"')
        gaps = ['\n<!-- first gap -->\n', '\n<!-- second gap -->\n', '\n<!-- third gap -->\n']
        for figures, direction in [([boy, family], 'ltr'), ([family, boy], 'rtl')]:
            source = article(before + gaps[0] + figures[0] + gaps[1] + figures[1] + gaps[2] + after,
                             f' dir="{direction}"')
            output = arrange_article_figures(source, rules)
            root = next(node for node in FigureElements(output).elements if node.tag == 'article')
            self.assertEqual([node.tag for node in root.children], ['figure', 'p', 'figure', 'p'])
            self.assertEqual([node.attrs['id'] for node in root.children], ['family', 'before', 'boy', 'after'])
            for node, original, side in [(root.children[0], family, 'end'), (root.children[2], boy, 'start')]:
                figure_node = FigureElements(original).elements[0]
                self.assertEqual(output[node.opening_end:node.closing_start],
                                 original[figure_node.opening_end:figure_node.closing_start])
                self.assertIn('source', node.attrs['class'].split())
                self.assertIn(f'article-figure--reviewed-{side}', node.attrs['class'].split())
            self.assertEqual(re.findall(r'<p\b[^>]*>.*?</p>', output), [before, after])
            self.assertEqual(re.findall(r'<img\b[^>]*>', output), [image('family'), image('boy')])
            self.assertTrue(all(gap in output for gap in gaps))
            self.assertEqual(arrange_article_figures(output, rules), output)

    def test_paragraph_pair_declines_ambiguous_or_changed_boundaries(self):
        rules = {A: {'paragraph_pair': PARAGRAPH_PAIR}}
        paragraph = '<p>Unchanged ordinary prose.</p>'
        pair = figure('boy') + figure('family')
        cases = {
            'missing image': paragraph + figure('boy') + paragraph,
            'duplicate elsewhere': paragraph + pair + paragraph + figure('boy'),
            'extra leading figure': paragraph + figure('other') + pair + paragraph,
            'extra trailing figure': paragraph + pair + figure('other') + paragraph,
            'earlier figure would become adjacent': figure('other') + paragraph + pair + paragraph,
            'separated figures': paragraph + figure('boy') + paragraph + figure('family') + paragraph,
            'preceding heading': '<h2>Heading</h2>' + pair + paragraph,
            'following heading': paragraph + pair + '<h2>Heading</h2>',
            'nested section': '<section>' + paragraph + pair + paragraph + '</section>',
            'loose boundary text': paragraph + 'Original words.' + pair + paragraph,
            'loose text between figures': paragraph + figure('boy') + 'Original words.' + figure('family') + paragraph,
            'hidden paragraph': paragraph + pair + '<p hidden>Hidden prose.</p>',
            'hidden image': paragraph + '<figure>' + image('boy', ' hidden') + '</figure>' + figure('family') + paragraph,
            'hidden figure': paragraph + figure('boy', extra=' hidden') + figure('family') + paragraph,
            'verse paragraph': '<p class="poem">Verse.</p>' + pair + paragraph,
            'line breaks': paragraph + pair + '<p>First line.<br>Second line.</p>',
            'empty paragraph': '<p><em>&nbsp;</em></p>' + pair + paragraph,
            'paragraph media': paragraph + pair + '<p>Words <video></video></p>',
            'figure media': paragraph + figure('boy', '<figcaption><video></video></figcaption>') + figure('family') + paragraph,
            'loose figure text': paragraph + figure('boy', 'Original explanation.') + figure('family') + paragraph,
            'multiple figure images': paragraph + '<figure>' + image('boy') + image('other') + '</figure>' + figure('family') + paragraph,
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                source = article(content)
                self.assertEqual(arrange_article_figures(source, rules), arrange_article_figures(source))
        source = article(paragraph + pair + paragraph, ' class="lyrics"')
        self.assertEqual(arrange_article_figures(source, rules), arrange_article_figures(source))

    def test_paragraph_pair_and_verse_quote_rules_reject_invalid_entries_and_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layouts.json'
            valid = {'paragraph_pair': PARAGRAPH_PAIR, 'verse_quote': ['lion.jpg']}
            path.write_text(json.dumps({'version': 1, 'articles': {A: valid}}))
            self.assertEqual(load_figure_rules(path), {A: valid})
            invalid_pairs = [None, {}, [], PARAGRAPH_PAIR[:1], PARAGRAPH_PAIR * 2,
                             ['family.jpg', 'boy.jpg'], [PARAGRAPH_PAIR[0], PARAGRAPH_PAIR[0]],
                             [{'image': 'family.jpg'}, PARAGRAPH_PAIR[1]],
                             [PARAGRAPH_PAIR[0] | {'extra': True}, PARAGRAPH_PAIR[1]],
                             [PARAGRAPH_PAIR[0] | {'side': 'right'}, PARAGRAPH_PAIR[1]]]
            invalid_pairs.extend([PARAGRAPH_PAIR[0] | {'image': name}, PARAGRAPH_PAIR[1]]
                                 for name in ['', '.', '..', '../family.jpg', 'folder\\family.jpg', 42])
            invalid = [{'paragraph_pair': pair} for pair in invalid_pairs]
            invalid.extend({'verse_quote': value} for value in
                           ['lion.jpg', None, {}, ['../lion.jpg'], ['folder\\lion.jpg'], [''], [42], ['lion.jpg', 'lion.jpg']])
            bounds = dict(width=100, height=100, top=0, right=0, bottom=0, left=0)
            for field, value, name in [('paragraph_pair', PARAGRAPH_PAIR, 'family.jpg'),
                                       ('verse_quote', ['lion.jpg'], 'lion.jpg')]:
                invalid.extend({field: value, **conflict} for conflict in [
                    {'standalone': [name]}, {'wrap': [name]},
                    {'paired': [[name, 'other.jpg']]}, {'transparent_padding': {name: bounds}},
                    {'opening_contour': CONTOUR | {'image': name}},
                ])
            invalid.extend([{'paragraph_pair': PARAGRAPH_PAIR, 'verse_quote': ['family.jpg']},
                            {'paragraph_pair': PARAGRAPH_PAIR, 'opening_order': ['family.jpg', 'boy.jpg']}])
            for rule in invalid:
                path.write_text(json.dumps({'version': 1, 'articles': {A: rule}}))
                with self.subTest(rule=rule), self.assertRaises(ValueError):
                    load_figure_rules(path)

    def test_reviewed_opening_pair_precedes_cover_and_preserves_source_content(self):
        rules = {A: {'opening_order': ['left.jpg', 'right.jpg', 'cover.jpg'],
                     'paired': [['left.jpg', 'right.jpg']]}}
        cover = '<figure id="cover">' + image('cover', ' width="96" height="151" loading="lazy"') + '</figure>'
        paragraphs = '<p>First &amp; faithful <em>paragraph</em>.</p><p>Second paragraph.</p>'
        gap = '\n<!-- original image separator -->\n'
        source = article('\n  ' + cover + gap + figure('left') + '\n\n' + figure('right') + '\n  ' + paragraphs)
        output = arrange_article_figures(source, rules)
        nodes = FigureElements(output).elements
        root = next(node for node in nodes if node.tag == 'article')
        self.assertEqual([node.tag for node in root.children], ['div', 'figure', 'p', 'p'])
        pair = root.children[0]
        self.assertIn('article-gallery--paired', pair.attrs['class'].split())
        self.assertEqual([node.tag for node in pair.children], ['figure', 'figure'])
        self.assertEqual(root.children[1].attrs['id'], 'cover')
        self.assertEqual(re.findall(r'<img\b[^>]*>', output),
                         [image('left'), image('right'), image('cover', ' width="96" height="151" loading="lazy"')])
        self.assertIn(paragraphs, output)
        self.assertIn(gap, output)
        self.assertEqual(arrange_article_figures(output, rules), output)
        self.assertEqual(re.findall(r'<img\b[^>]*>', arrange_article_figures(source)),
                         re.findall(r'<img\b[^>]*>', source))

    def test_opening_order_leaves_changed_or_ambiguous_groups_in_source_order(self):
        rules = {A: {'opening_order': ['left.jpg', 'right.jpg', 'cover.jpg'],
                     'paired': [['left.jpg', 'right.jpg']]}}
        opening = figure('cover') + figure('left') + figure('right')
        paragraph = '<p>Unchanged opening paragraph.</p>'
        cases = {
            'missing image': figure('cover') + figure('left') + paragraph,
            'duplicate later in article': opening + paragraph + figure('cover'),
            'captioned cover': figure('cover', '<figcaption>Original caption.</figcaption>') + figure('left') + figure('right') + paragraph,
            'intervening paragraph': figure('cover') + paragraph + figure('left') + figure('right') + paragraph,
            'additional opening image': opening + figure('other') + paragraph,
            'changed image': figure('cover') + figure('left') + figure('other') + paragraph,
            'loose text between figures': figure('cover') + 'Original visible text.' + figure('left') + figure('right') + paragraph,
            'heading before figures': '<h2>Original heading</h2>' + opening + paragraph,
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                source = article(content)
                output = arrange_article_figures(source, rules)
                self.assertEqual(re.findall(r'<img\b[^>]*>', output), re.findall(r'<img\b[^>]*>', source))
                self.assertEqual(re.findall(r'<p>.*?</p>', output), re.findall(r'<p>.*?</p>', source))

    def test_opening_contour_preserves_source_and_contains_only_the_first_paragraph(self):
        rules = {A: {'opening_contour': CONTOUR}}
        image_tag = image('arch', ' width="100" height="40" loading="lazy"')
        paragraph = '<p class="lead">First &amp; faithful <em>words</em>, with <a href="#note">a reference</a>.</p>'
        later = '<p>Second paragraph remains outside the contour.</p>'
        gap = '\n<!-- original figure separator -->\n'
        for direction in ('ltr', 'rtl'):
            source = article('\n<!-- opening -->\n<figure class="original">' + image_tag +
                             '</figure>' + gap + paragraph + '\n' + later + figure('other'),
                             f' dir="{direction}"')
            output = arrange_article_figures(source, rules)
            nodes = FigureElements(output).elements
            root = next(node for node in nodes if node.tag == 'article')
            self.assertEqual([node.tag for node in root.children], ['div', 'p', 'figure'])
            wrapper = root.children[0]
            self.assertEqual(wrapper.attrs['class'], 'article-contour-opening')
            self.assertEqual([wrapper.attrs[f'data-contour-{key}'] for key in ('width', 'height', 'start')],
                             ['100', '40', '18'])
            self.assertIn('--article-contour-max-width:100px;', wrapper.attrs['style'])
            self.assertIn('40.00000000% 50.00000000%', wrapper.attrs['style'].split('--article-contour-right:')[0])
            self.assertIn('60.00000000% 50.00000000%', wrapper.attrs['style'].split('--article-contour-right:')[1])
            self.assertEqual([node.tag for node in wrapper.children], ['figure', 'span', 'span', 'p'])
            self.assertIn('original', wrapper.children[0].attrs['class'].split())
            self.assertIn('article-figure--standalone', wrapper.children[0].attrs['class'].split())
            for edge, side in zip(wrapper.children[1:3], ('left', 'right')):
                self.assertEqual(edge.attrs['class'], f'article-contour-edge article-contour-edge--{side}')
                self.assertEqual(edge.attrs['aria-hidden'], 'true')
                self.assertEqual(edge.opening_end, edge.closing_start)
            self.assertEqual(output[wrapper.children[-1].start:wrapper.children[-1].end], paragraph)
            self.assertEqual(output[root.children[1].start:root.children[1].end], later)
            self.assertEqual(re.findall(r'<img\b[^>]*>', output), re.findall(r'<img\b[^>]*>', source))
            self.assertIn(gap, output)
            self.assertEqual(arrange_article_figures(output, rules), output)
            self.assertNotIn('article-contour-opening', arrange_article_figures(source))

    def test_opening_contour_declines_changed_ambiguous_or_nonprose_content(self):
        rules = {A: {'opening_contour': CONTOUR}}
        opening, paragraph = figure('arch'), '<p>Opening &amp; prose.</p>'
        cases = {
            'different image': figure('other') + paragraph,
            'repeated image later': opening + paragraph + figure('arch'),
            'caption': figure('arch', '<figcaption>Original caption.</figcaption>') + paragraph,
            'loose figure text': figure('arch', 'Visible source explanation.') + paragraph,
            'two images in figure': '<figure>' + image('arch') + image('other') + '</figure>' + paragraph,
            'linked image': '<figure><a href="#image">' + image('arch') + '</a></figure>' + paragraph,
            'second leading figure': opening + figure('other') + paragraph,
            'preceding heading': '<h2>Source heading</h2>' + opening + paragraph,
            'intervening heading': opening + '<h2>Source heading</h2>' + paragraph,
            'preceding loose text': 'Source introduction.' + opening + paragraph,
            'intervening loose text': opening + 'Original visible text.' + paragraph,
            'nested figure': '<section>' + opening + paragraph + '</section>',
            'empty paragraph': opening + '<p><!-- source comment --><em>&nbsp;</em></p>',
            'poem': opening + '<p class="poem">Opening verse.</p>',
            'lyrics': opening + '<p class="lyrics">Opening lyrics.</p>',
            'nested line break': opening + '<p>Opening <em>line<br>second line.</em></p>',
            'inline image': opening + '<p>Opening ' + image('other') + ' prose.</p>',
            'hidden paragraph': opening + '<p hidden>Opening prose.</p>',
            'hidden figure': figure('arch', extra=' hidden') + paragraph,
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                source = article(content)
                output = arrange_article_figures(source, rules)
                self.assertNotIn('article-contour-opening', output)
                self.assertEqual(re.findall(r'<img\b[^>]*>', output), re.findall(r'<img\b[^>]*>', source))
                self.assertEqual(re.findall(r'<p\b[^>]*>.*?</p>', output, re.S),
                                 re.findall(r'<p\b[^>]*>.*?</p>', source, re.S))
        self.assertNotIn('article-contour-opening', arrange_article_figures(
            article(opening + paragraph, ' class="poem"'), rules))

    def test_opening_contour_rules_reject_invalid_geometry_paths_and_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layouts.json'
            valid = {'opening_contour': CONTOUR, 'standalone': ['other.jpg']}
            path.write_text(json.dumps({'version': 1, 'articles': {A: valid}}))
            self.assertEqual(load_figure_rules(path), {A: valid})
            invalid = [None, [], {}, CONTOUR | {'extra': 1}]
            invalid.extend(CONTOUR | {key: value} for key, values in {
                'image': ['', '.', '..', '../arch.jpg', 'folder\\arch.jpg', 42],
                'width': [0, -1, True, float('inf'), float('nan'), '100'],
                'height': [0, float('-inf')], 'text_start': [-1, 40, True, float('nan')],
                'edges': [None, {}, [], [[0, 50, 50]], [[0, 50], [40, 0, 100]],
                          [[0, 50, 50], [20, -1, 80], [40, 0, 100]],
                          [[0, 50, 50], [20, 51, 80], [40, 0, 100]],
                          [[0, 50, 50], [20, 20, 49], [40, 0, 100]],
                          [[0, 50, 50], [20, 20, 101], [40, 0, 100]],
                          [[0, 50, 50], [40, 0, 100], [20, 20, 80]],
                          [[0, 50, 50], [0, 20, 80], [40, 0, 100]],
                          [[1, 50, 50], [40, 0, 100]], [[0, 49, 50], [40, 0, 100]],
                          [[0, 50, 50], [40, 1, 100]], [[0, 50, 50], [41, 0, 100]],
                          [[0, 50, 50], [20, float('nan'), 80], [40, 0, 100]]],
            }.items() for value in values)
            rules = [{'opening_contour': contour} for contour in invalid]
            bounds = dict(width=100, height=40, top=0, right=0, bottom=0, left=0)
            rules.extend({'opening_contour': CONTOUR, **conflict} for conflict in [
                {'standalone': ['arch.jpg']}, {'wrap': ['arch.jpg']},
                {'paired': [['arch.jpg', 'other.jpg']]}, {'transparent_padding': {'arch.jpg': bounds}},
                {'opening_order': ['arch.jpg', 'other.jpg']},
            ])
            for rule in rules:
                path.write_text(json.dumps({'version': 1, 'articles': {A: rule}}))
                with self.subTest(rule=rule), self.assertRaises(ValueError):
                    load_figure_rules(path)

    def test_standalone_sheets_and_repeated_decorations_are_not_gallery_items(self):
        rules = {A: {'standalone': ['sheet.jpg', 'divider.jpg']}}
        source = article(figure('one') + figure('sheet') + figure('two') + figure('divider') + figure('three'))
        output = arrange_article_figures(source, rules)
        self.assertEqual(galleries(output), [])
        self.assertEqual(output.count('article-figure--standalone'), 2)
        repeated = arrange_article_figures(article(figure('break') + figure('break') + figure('other')))
        self.assertEqual(galleries(repeated), [])
        self.assertEqual(repeated.count('article-figure--standalone'), 2)

    def test_reviewed_wrap_marks_only_its_single_image_figure_without_changing_content(self):
        rules = {A: {'standalone': ['banner.jpg'], 'wrap': ['photo.jpg']}}
        caption = '<figcaption>Original credit &amp; source.</figcaption>'
        paragraph = '<p>Unchanged opening <em>paragraph</em>.</p>'
        source = article(figure('banner') + figure('photo', caption) + paragraph)
        output = arrange_article_figures(source, rules)
        root = next(node for node in FigureElements(output).elements if node.tag == 'article')
        self.assertEqual([node.tag for node in root.children], ['figure', 'figure', 'p'])
        self.assertNotIn('article-figure--reviewed-wrap', root.children[0].attrs['class'].split())
        self.assertIn('article-figure--standalone', root.children[0].attrs['class'].split())
        self.assertIn('article-figure--reviewed-wrap', root.children[1].attrs['class'].split())
        self.assertEqual(re.findall(r'<img\b[^>]*>', output), re.findall(r'<img\b[^>]*>', source))
        self.assertIn(caption, output)
        self.assertIn(paragraph, output)
        self.assertEqual(arrange_article_figures(output, rules), output)
        self.assertNotIn('article-figure--reviewed-wrap', arrange_article_figures(source))
        multiple = article('<figure>' + image('photo') + image('other') + '</figure>' + paragraph)
        self.assertNotIn('article-figure--reviewed-wrap', arrange_article_figures(multiple, rules))

    def test_reviewed_wrap_rules_reject_invalid_basenames_and_conflicting_layouts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layouts.json'
            rule = {'wrap': ['photo.jpg'], 'standalone': ['banner.jpg'],
                    'opening_order': ['banner.jpg', 'photo.jpg']}
            path.write_text(json.dumps({'version': 1, 'articles': {A: rule}}))
            self.assertEqual(load_figure_rules(path), {A: rule})
            invalid = [{'wrap': value} for value in ['photo.jpg', None, {}, ['../photo.jpg'],
                       ['folder\\photo.jpg'], [''], [42], ['photo.jpg', 'photo.jpg']]]
            bounds = dict(width=300, height=200, top=0, right=0, bottom=0, left=0)
            invalid.extend({'wrap': ['photo.jpg'], **conflict} for conflict in [
                {'standalone': ['photo.jpg']}, {'paired': [['photo.jpg', 'other.jpg']]},
                {'transparent_padding': {'photo.jpg': bounds}},
            ])
            for rule in invalid:
                path.write_text(json.dumps({'version': 1, 'articles': {A: rule}}))
                with self.subTest(rule=rule), self.assertRaises(ValueError):
                    load_figure_rules(path)

    def test_text_between_images_inside_a_figure_is_never_moved(self):
        source = article('<figure>' + image('one') + '<p>Intervening explanation.</p>' + image('two') + '</figure>')
        self.assertNotIn('article-gallery__images', arrange_article_figures(source))

    def test_existing_attributes_entities_and_unquoted_classes_remain_valid(self):
        for classes in ['class="existing"', "class='existing'", 'class=existing']:
            source = article(figure('one', extra=' ' + classes) + figure('two'), ' title="A class=word here" ' + classes)
            output = arrange_article_figures(source)
            nodes = FigureElements(output).elements
            for node in nodes:
                if node.tag in {'article', 'figure'} and 'existing' in node.attrs.get('class', ''):
                    self.assertIn('existing', node.attrs['class'].split())
            self.assertIn('title="A class=word here"', output)
            self.assertEqual(arrange_article_figures(output), output)

    def test_rule_loader_rejects_invalid_paths_and_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layouts.json'
            valid = {'version': 1, 'articles': {A: {'paired': [['left.jpg', 'right.jpg']], 'standalone': ['sheet.jpg']}}}
            path.write_text(json.dumps(valid))
            self.assertEqual(load_figure_rules(path), valid['articles'])
            valid['articles'][A]['opening_order'] = ['left.jpg', 'right.jpg', 'cover.jpg']
            path.write_text(json.dumps(valid))
            self.assertEqual(load_figure_rules(path), valid['articles'])
            for opening_order in ['left.jpg', None, {}, ['only.jpg'], ['left.jpg', 'left.jpg'],
                                  ['../left.jpg', 'right.jpg'], ['folder\\left.jpg', 'right.jpg'],
                                  ['', 'right.jpg'], [42, 'right.jpg']]:
                path.write_text(json.dumps({'version': 1, 'articles': {A: {'opening_order': opening_order}}}))
                with self.subTest(opening_order=opening_order), self.assertRaises(ValueError):
                    load_figure_rules(path)
            for invalid in [{}, {'version': 1, 'articles': {A: {'paired': [['only.jpg']]}}},
                            {'version': 1, 'articles': {A: {'paired': [['one.jpg', 'two.jpg', 'three.jpg']]}}},
                            {'version': 1, 'articles': {A: {'paired': [['one.jpg', 'two.jpg']], 'standalone': ['one.jpg']}}},
                            {'version': 1, 'articles': {A: {'paired': [['one.jpg', 'two.jpg']], 'dimensions': {'one.jpg': [10, 20]}}}},
                            {'version': 1, 'articles': {A: {'paired': [['one.jpg', 'two.jpg']], 'dimensions': {'one.jpg': [10, 0], 'two.jpg': [10, 20]}}}},
                            {'version': 1, 'articles': {A: {'standalone': ['../escape.jpg']}}}]:
                path.write_text(json.dumps(invalid))
                with self.assertRaises(ValueError):
                    load_figure_rules(path)

    def test_site_reader_changes_leave_model_and_markdown_source_unchanged(self):
        from build import Site
        from test_site import fixture
        with tempfile.TemporaryDirectory() as directory:
            model, locales, routes, theme, output = fixture(Path(directory), translated=False)
            item = model['articles']['en'][0]
            original = article(figure('one', '<figcaption>Exact caption.</figcaption>') + figure('two') + '<p>Unchanged prose.</p>')
            item['html'] = original
            site = Site(model, locales, routes, theme, output, {})
            site.article_page('en', item)
            reader = (output / item['url'].lstrip('/') / 'index.html').read_text()
            markdown = (output / item['markdown_url'].lstrip('/')).read_text()
            self.assertIn('article-gallery', reader)
            self.assertNotIn('article-gallery', markdown)
            self.assertIn(r'Exact caption\.', markdown)
            self.assertIn(r'Unchanged prose\.', markdown)
            self.assertEqual(item['html'], original)

    def test_source_backed_checker_accepts_layout_but_rejects_text_image_and_caption_mutations(self):
        from build import Site
        from check_site import SiteChecker
        from test_site import fixture
        with tempfile.TemporaryDirectory() as directory:
            model, locales, routes, theme, output = fixture(Path(directory), translated=False)
            item = model['articles']['en'][0]
            # Include both an ordinary captioned gallery and a reviewed split
            # composition whose second panel starts after the prose.
            item['html'] = article(figure('one', '<figcaption>Exact source caption.</figcaption>') +
                                   figure('two') + '<p>Original paragraph.</p>' +
                                   figure('left') + '<p>Prose between panels.</p>' + figure('right'))
            rules = {A: {'transparent_padding': {'one.jpg': dict(width=460, height=901, top=384, right=0, bottom=0, left=0)},
                         'paired': [['left.jpg', 'right.jpg']],
                         'dimensions': {'left.jpg': [300, 400], 'right.jpg': [200, 400]}}}
            site = Site(model, locales, routes, theme, output, {})
            site.figure_rules = rules
            site.article_page('en', item)
            image_directory = output / 'images/articles'
            image_directory.mkdir(parents=True)
            for name in ['one', 'two', 'left', 'right', 'changed']:
                (image_directory / f'{name}.jpg').write_bytes(b'fixture image')
            path = output / item['url'].lstrip('/') / 'index.html'
            reader = path.read_text()

            def errors():
                with patch('article_figures.load_figure_rules', return_value=rules):
                    checker = SiteChecker(output)
                    checker.run(model=model, locales=locales, routes=routes, theme=theme)
                    return checker.errors

            self.assertEqual(errors(), [])
            for before, after in [('Original paragraph.', 'Changed paragraph.'),
                                  ('/images/articles/one.jpg', '/images/articles/changed.jpg'),
                                  ('Exact source caption.', 'Changed source caption.')]:
                path.write_text(reader.replace(before, after, 1))
                self.assertTrue(any('original exported HTML/notice was changed' in error for error in errors()), (before, errors()))
            path.write_text(reader)


if __name__ == '__main__':
    unittest.main()
