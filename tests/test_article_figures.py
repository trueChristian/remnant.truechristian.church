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


def image(name, extra=''):
    return f'<img src="/images/articles/{name}.jpg" alt="Original &amp; caption"{extra}>'


def figure(name, caption='', extra=''):
    return f'<figure{extra}>{image(name)}{caption}</figure>'


def article(content, extra=''):
    return f'<article data-article-id="{A}"{extra}>{content}</article>'


def galleries(html):
    return [node for node in FigureElements(html).elements if node.tag == 'div' and 'article-gallery' in node.attrs.get('class', '').split()]


class ArticleFigureTests(unittest.TestCase):
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

    def test_standalone_sheets_and_repeated_decorations_are_not_gallery_items(self):
        rules = {A: {'standalone': ['sheet.jpg', 'divider.jpg']}}
        source = article(figure('one') + figure('sheet') + figure('two') + figure('divider') + figure('three'))
        output = arrange_article_figures(source, rules)
        self.assertEqual(galleries(output), [])
        self.assertEqual(output.count('article-figure--standalone'), 2)
        repeated = arrange_article_figures(article(figure('break') + figure('break') + figure('other')))
        self.assertEqual(galleries(repeated), [])
        self.assertEqual(repeated.count('article-figure--standalone'), 2)

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
