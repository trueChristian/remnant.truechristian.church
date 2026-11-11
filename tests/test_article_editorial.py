"""Reviewed compositions preserve source nodes and decline ambiguous edits."""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from article_figures import arrange_article_figures, FigureElements, load_figure_rules
from article_editorial import arrange_editorial, validate_editorial_rules

ID = '00000000-0000-4000-9000-000000000001'
def image(name, caption=''):
    return f'<figure><img src="/images/articles/{name}.png" alt="Original &amp; artwork">{caption}</figure>'
def article(content):
    return f'<article data-article-id="{ID}">{content}</article>'
def rule(kind, names, **extra):
    return {ID: {'editorial': {'kind': kind, 'images': [f'{name}.png' for name in names], **extra}}}

QUOTE = '<blockquote><p><em>Original first line<br>Original second line<br>Original third line.</em></p></blockquote>'
POEM = '<div class="poem"><p>First stanza<br>Second line.</p><p>Second stanza<br>Last line.</p></div>'
PROSE = '<p>Original first main paragraph, with <strong>emphasis</strong>.</p>'

class EditorialLayoutTests(unittest.TestCase):
    def check_retained(self, source, rules, marker):
        output = arrange_article_figures(source, rules)
        self.assertIn(marker, output)
        for pattern in (r'<p\b[^>]*>.*?</p>', r'<figcaption\b[^>]*>.*?</figcaption>'):
            self.assertEqual(re.findall(pattern, source, re.S), re.findall(pattern, output, re.S))
        self.assertEqual(sorted(re.findall(r'<img\b[^>]*>', source)), sorted(re.findall(r'<img\b[^>]*>', output)))
        self.assertEqual(source.count('<br>'), output.count('<br>'))
        self.assertEqual(arrange_article_figures(output, rules), output)
        return output

    def test_source_note_keeps_credits_before_native_figure_and_prose(self):
        notes = '<p><em>From the book</em><br>Original title</p><p><em>Publisher<br>Original address</em></p>'
        output = self.check_retained(article(image('one')+notes+PROSE), rule('source-note',['one']), 'article-source-note')
        self.assertIn(f'<aside class="article-source-note">{notes}</aside>', output)
        self.assertLess(output.index('</aside>'), output.index('<figure'))
        self.assertLess(output.index('</figure>'), output.index(PROSE))

    def test_unreviewed_prose_cannot_become_a_source_note(self):
        source = article(image('one')+PROSE+PROSE+PROSE)
        self.assertEqual(arrange_editorial(source, rule('source-note',['one']), FigureElements), source)

    def test_poem_artwork_keeps_the_complete_poem_as_one_column(self):
        output = self.check_retained(article(image('one')+image('two')+POEM), rule('verse-pictures',['one','two']), 'article-editorial-verse')
        self.assertIn(POEM, output)
        self.assertIn(f'<div class="article-editorial-art">{image("one")}{image("two")}</div>', output)

    def test_portrait_keeps_intro_full_width_and_caption_with_image(self):
        picture = image('one','<figcaption>Exact <strong>caption</strong></figcaption>')
        output = self.check_retained(article(picture+PROSE+QUOTE+PROSE), rule('quote-portrait',['one']), 'article-editorial-verse--native')
        self.assertLess(output.index(PROSE), output.index('article-editorial-verse'))
        self.assertIn(QUOTE, output)
        self.assertIn(picture, output)

    def test_frame_keeps_quote_between_complete_corner_images(self):
        output = self.check_retained(article(image('one')+image('two')+QUOTE+PROSE), rule('quote-frame',['one','two']), 'article-quote-frame')
        self.assertLess(output.index('one.png'), output.index(QUOTE))
        self.assertLess(output.index(QUOTE), output.index('two.png'))
        self.assertIn('aria-hidden="true"', output)

    def test_frame_declines_captions_that_would_change_corner_geometry(self):
        source = article(image('one','<figcaption>New caption</figcaption>')+image('two')+QUOTE)
        self.assertEqual(arrange_editorial(source, rule('quote-frame',['one','two']), FigureElements), source)

    def test_pair_stays_together_beside_one_paragraph_after_the_logo(self):
        source = article(image('logo')+image('one')+image('two')+PROSE+PROSE)
        rules = rule('prose-pair',['one','two']); rules[ID]['standalone']=['logo.png']
        output = self.check_retained(source, rules, 'article-editorial-art--pair')
        self.assertLess(output.index('logo.png'), output.index('article-editorial-prose'))
        row = next(n for n in FigureElements(output).elements if 'article-editorial-prose' in n.attrs.get('class','').split())
        self.assertEqual([n.tag for n in row.children], ['div','p'])

    def test_only_explicit_reduction_gets_a_display_width(self):
        rules = rule('reduced-prose',['one'],width=400,source_size=[1276,1059])
        output = self.check_retained(article(QUOTE+image('one')+PROSE),rules,'data-display-width="400"')
        self.assertIn('data-source-width="1276" data-source-height="1059"',output)
        self.assertIn('<img src="/images/articles/one.png" alt="Original &amp; artwork">',output)

    def test_poem_heading_is_separate_and_leaves_poem_bytes_unchanged(self):
        output = self.check_retained(article(image('one')+POEM),rule('poem-heading',['one']),'article-poem-heading')
        self.assertIn(POEM,output)
        self.assertNotIn('article-verse-row',output)

    def test_changed_missing_repeated_nested_and_hidden_content_declines(self):
        rules = rule('quote-portrait',['one'])
        sources = [article(PROSE+QUOTE), article(image('one')+PROSE+QUOTE+image('one')),
                   article('<section>'+image('one')+'</section>'+PROSE+QUOTE),
                   article(image('one')+'Loose new text'+PROSE+QUOTE),
                   article(image('one')+PROSE+'<h2>New section</h2>'+QUOTE),
                   article(image('one')+PROSE+QUOTE.replace('<em>','<em hidden>'))]
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(arrange_editorial(source,rules,FigureElements),source)

    def test_list_opt_in_preserves_bullets_and_items(self):
        listing='<ul><li>First <em>item</em></li><li>Second item</li></ul>'
        source=article(image('one')+PROSE+listing)
        output=self.check_retained(source,{ID:{'list_flow':['one.png']}},'data-reader-list-flow')
        self.assertEqual(re.findall(r'<li>.*?</li>',output),re.findall(r'<li>.*?</li>',source))
        self.assertNotIn('data-reader-list-flow',arrange_article_figures(source))

    def test_registry_rejects_invalid_and_conflicting_compositions(self):
        invalid=[{'editorial':{}},{'editorial':{'kind':'unknown','images':['one.png']}},
                 {'editorial':{'kind':'quote-frame','images':['one.png','one.png']}},
                 {'editorial':{'kind':'poem-heading','images':[{}]}},
                 {'editorial':{'kind':'poem-heading','images':['../one.png']}},
                 {'editorial':{'kind':'poem-heading','images':['one.png'],'unexpected':1}},
                 {'editorial':{'kind':'poem-heading','images':['one.png']},'standalone':['one.png']},
                 {'editorial':{'kind':'reduced-prose','images':['one.png'],'width':1200,'source_size':[100,100]}},
                 {'editorial':{'kind':'reduced-prose','images':['one.png'],'width':True,'source_size':[1000,1000]}},
                 {'list_flow':'one.png'}]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):validate_editorial_rules(ID,value)

    def test_committed_registry_loads_without_relaxing_existing_validation(self):
        self.assertIn('editorial',load_figure_rules(ROOT/'data/article-image-layouts.json')['bbeefd6c-2894-4a32-88a8-1d6e889e3159'])

if __name__=='__main__':unittest.main()
