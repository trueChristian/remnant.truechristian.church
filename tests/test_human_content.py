"""Human repository edits control presentation without bypassing export safety."""
import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from scripts.content import ContentError, load_content
from tests.test_content import A, fixture as export_fixture, inventory, write_json
from tests.test_site import fixture as site_fixture
from build import Site
from check_site import PageParser, SiteChecker


HUMAN_EDIT = {
    'commit': 'd' * 40,
    'author': 'Repository Editor',
    'email': 'editor@example.test',
    'time': '2026-10-04T12:34:56+00:00',
}
BODY = f'<article data-article-id="{A}"><p>Hersiene woorde.</p></article>'
NOTICE = '<aside data-translation-notice="ai"><p>Retained editorial wording.</p></aside>'
IMAGE_PATH = '/images/articles/original.jpg'


class HumanContentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.en, self.tr = self.root / 'en', self.root / 'translations'
        export_fixture(self.en)
        export_fixture(self.tr, translated=True, human=True, notice=False)
        self.base_item = json.loads((self.tr / 'index.json').read_text())['articles'][0]
        self.base_item.update(human_edit=copy.deepcopy(HUMAN_EDIT),
                              notice_present=False, images=[])
        self.translation(BODY)

    def refresh(self, root):
        manifest = json.loads((root / 'manifest.json').read_text())
        manifest['files'] = inventory(root)
        write_json(root / 'manifest.json', manifest)

    def translation(self, html, *, remove=(), **changes):
        item = copy.deepcopy(self.base_item)
        item.update(changes)
        for key in remove:
            item.pop(key, None)
        (self.tr / item['html']).write_text(html, encoding='utf-8')
        item['html_sha256'] = hashlib.sha256(html.encode()).hexdigest()
        write_json(self.tr / item['metadata'],
                   {key: item[key] for key in ('title', 'subtitle', 'section')})
        index = json.loads((self.tr / 'index.json').read_text())
        index['articles'] = [item]
        write_json(self.tr / 'index.json', index)
        self.refresh(self.tr)

    def article(self):
        model = load_content(self.en, self.tr, strict_translations=True)
        self.assertEqual(model['translation_status'], 'ready')
        return model['articles']['af'][0]

    def asset(self, public_path, *, public_directory=False):
        path = self.en / ('public' if public_directory else '') / public_path.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'shared fixture image')
        self.refresh(self.en)

    def source_image(self):
        self.asset(IMAGE_PATH)
        index = json.loads((self.en / 'index.json').read_text())
        image = {'public_path': IMAGE_PATH, 'alt': 'Original description',
                 'caption': 'Original caption', 'credit': 'Original Photographer',
                 'source_url': 'https://example.test/original-photo'}
        source = index['articles'][0]
        source['images'] = [image]
        path = self.en / source['html']['repository_path']
        path.write_text(
            f'<article data-article-id="{A}"><p>Exact source words.</p>'
            f'<figure><img src="{IMAGE_PATH}" alt="Original description">'
            '<figcaption>Original caption</figcaption></figure></article>',
            encoding='utf-8')
        write_json(self.en / 'index.json', index)
        self.refresh(self.en)
        return image

    def test_human_footer_wording_presence_and_marker_count_are_editorial(self):
        variants = [
            ('removed', '', 0),
            ('retained', NOTICE, 1),
            ('changed', '<footer data-translation-notice="ai"><p>Editor revised this freely.</p></footer>', 1),
            ('human', '<aside data-translation-notice="human"><p>Reviewed by a human.</p></aside>', 1),
            ('arbitrary', '<footer><p>Prepared for this edition by the editor.</p></footer>', 0),
            ('multiple', NOTICE + NOTICE.replace('Retained', 'Additional'), 2),
        ]
        for name, footer, notice_count in variants:
            with self.subTest(footer=name):
                html = BODY + footer
                self.translation(html, notice_present=bool(notice_count))
                article = self.article()
                self.assertEqual(article['html'], html)
                self.assertTrue(article['human_reviewed'])
                self.assertFalse(article['ai_notice_required'])
                self.assertEqual(article['notice_count'], notice_count)
                self.assertEqual(article['notice_present'], bool(notice_count))
                self.assertEqual(article['human_edit'], HUMAN_EDIT)

    def test_human_notice_is_excluded_from_search_and_preserved_in_markdown(self):
        from scripts.markdown import html_to_markdown
        footer = f'<aside data-translation-notice="human"><p>Reviewed by a human. <a href="/en/articles/{A}/">English original</a>.</p></aside>'
        self.translation(BODY + footer, notice_present=True)
        article = self.article()
        self.assertEqual(article['text'], 'Hersiene woorde.')
        self.assertNotIn('Reviewed by a human', article['excerpt'])
        self.assertIn(footer, html_to_markdown(article['html']))

    def test_human_prose_numbers_references_and_metadata_need_no_source_parity(self):
        text = 'Heeltemal nuwe woorde: 2026, 73 en Johannes 9:4–7.'
        html = (f'<article data-article-id="{A}"><p>{text}</p>'
                '<p><a href="https://example.test/new-reference">Nuwe verwysing</a></p></article>')
        self.translation(html, title='A freely revised title', subtitle='New subtitle',
                         section='New section')
        article = self.article()
        self.assertEqual(article['html'], html)
        self.assertIn(text, article['text'])
        self.assertIn('Nuwe verwysing', article['text'])
        self.assertNotIn('Exact words', article['text'])
        self.assertEqual(article['title'], 'A freely revised title')
        self.assertEqual(article['subtitle'], 'New subtitle')
        self.assertEqual(article['section'], 'New section')

    def test_human_can_remove_source_image(self):
        self.source_image()
        self.translation(BODY, images=[])
        article = self.article()
        self.assertEqual(article['images'], [])
        self.assertIsNone(article['image'])

    def test_human_can_replace_source_image_with_existing_shared_asset(self):
        self.source_image()
        replacement = '/images/articles/another-article.jpg'
        self.asset(replacement)
        html = BODY.replace('</article>', f'<img src="{replacement}" alt="New choice"></article>')
        self.translation(html, images=[{'public_path': replacement, 'alt': 'New choice'}])
        article = self.article()
        self.assertEqual(article['images'], [{'public_path': replacement, 'alt': 'New choice'}])
        self.assertEqual(article['image']['public_path'], replacement)
        self.assertNotIn(IMAGE_PATH, article['html'])

    def test_human_asset_can_use_supported_public_export_layout(self):
        self.asset(IMAGE_PATH, public_directory=True)
        html = BODY.replace('</article>', f'<img src="{IMAGE_PATH}" alt="Added image"></article>')
        self.translation(html, images=[{'public_path': IMAGE_PATH, 'alt': 'Added image'}])
        self.assertEqual(self.article()['images'][0]['public_path'], IMAGE_PATH)

    def test_matching_source_image_retains_attribution_with_edited_alt_and_caption(self):
        original = self.source_image()
        html = BODY.replace('</article>',
                            f'<figure><img src="{IMAGE_PATH}" alt="Hersiene beskrywing">'
                            '<figcaption>Nuwe onderskrif</figcaption></figure></article>')
        self.translation(html, images=[{'public_path': IMAGE_PATH, 'alt': 'Hersiene beskrywing',
                                        'credit': None, 'source_url': None}])
        image = self.article()['images'][0]
        self.assertEqual(image['alt'], 'Hersiene beskrywing')
        self.assertEqual(image['caption'], 'Nuwe onderskrif')
        self.assertEqual(image['credit'], original['credit'])
        self.assertEqual(image['source_url'], original['source_url'])

    def test_human_images_still_require_safe_existing_assets(self):
        for path in ('/images/articles/missing.jpg', '/images/articles/../outside.jpg',
                     '/images/articles//empty.jpg', 'https://example.test/image.jpg',
                     '/assets/elsewhere.jpg'):
            with self.subTest(path=path):
                html = BODY.replace('</article>', f'<img src="{path}" alt="Image"></article>')
                self.translation(html, images=[{'public_path': path, 'alt': 'Image'}])
                with self.assertRaises(ContentError):
                    self.article()

    def test_human_asset_symlink_cannot_escape_export(self):
        target = self.root / 'outside.jpg'
        target.write_bytes(b'outside export')
        link = self.en / IMAGE_PATH.lstrip('/')
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        html = BODY.replace('</article>', f'<img src="{IMAGE_PATH}" alt="Image"></article>')
        self.translation(html, images=[{'public_path': IMAGE_PATH, 'alt': 'Image'}])
        with self.assertRaisesRegex(ContentError, 'symlinks are forbidden'):
            self.article()

    def test_human_export_still_requires_actual_image_inventory(self):
        self.asset(IMAGE_PATH)
        image = {'public_path': IMAGE_PATH, 'alt': 'Image'}
        html = BODY.replace('</article>', f'<img src="{IMAGE_PATH}" alt="Image"></article>')
        for images in ([], [image, image], [{'public_path': IMAGE_PATH}], None):
            with self.subTest(images=images):
                self.translation(html, images=images)
                with self.assertRaises(ContentError):
                    self.article()
        self.translation(BODY, images=[image])
        with self.assertRaisesRegex(ContentError, 'image inventory mismatch'):
            self.article()

    def test_human_footer_and_body_still_reject_active_html(self):
        unsafe = ('<script>alert(1)</script>', '<p onclick="alert(1)">Text</p>',
                  '<a href="javascript:alert(1)">Link</a>', '<iframe></iframe>')
        for fragment in unsafe:
            for location in ('body', 'footer'):
                with self.subTest(fragment=fragment, location=location):
                    html = (BODY.replace('</article>', fragment + '</article>') if location == 'body'
                            else BODY + f'<aside data-translation-notice="ai">{fragment}</aside>')
                    self.translation(html, notice_present=location == 'footer')
                    with self.assertRaises(ContentError):
                        self.article()

    def test_human_edit_still_requires_article_identity_and_well_formed_html(self):
        for html in (BODY.replace(A, '00000000-0000-4000-8000-000000000099'),
                     BODY.replace('</article>', ''), BODY.replace('</p>', '</div>')):
            with self.subTest(html=html):
                self.translation(html)
                with self.assertRaises(ContentError):
                    self.article()

    def test_malformed_human_edit_provenance_is_rejected(self):
        invalid = [None, [], {}, dict(HUMAN_EDIT, commit='not-a-commit'),
                   dict(HUMAN_EDIT, commit='d' * 39), dict(HUMAN_EDIT, author=None),
                   dict(HUMAN_EDIT, email=[]), dict(HUMAN_EDIT, time=123)]
        invalid.extend({key: value for key, value in HUMAN_EDIT.items() if key != missing}
                       for missing in HUMAN_EDIT)
        for provenance in invalid:
            with self.subTest(provenance=provenance):
                self.translation(BODY, human_edit=provenance)
                with self.assertRaisesRegex(ContentError, 'human edit'):
                    self.article()

    def test_human_provenance_requires_explicit_export_control_and_presentation_fields(self):
        for changes in ({'human_reviewed': False}, {'human_reviewed': 1},
                        {'ai_notice_required': True}, {'ai_notice_required': 0},
                        {'notice_present': 'false'}, {'notice_present': None}):
            with self.subTest(changes=changes):
                self.translation(BODY, **changes)
                with self.assertRaises(ContentError):
                    self.article()
        for missing in ('human_reviewed', 'ai_notice_required', 'notice_present', 'images'):
            with self.subTest(missing=missing):
                self.translation(BODY, remove=(missing,))
                with self.assertRaises(ContentError):
                    self.article()

    def test_ai_only_translation_still_requires_exactly_one_notice(self):
        for count in (0, 1, 2):
            with self.subTest(notice_count=count):
                self.translation(BODY + NOTICE * count,
                                 remove=('human_edit', 'notice_present', 'images'),
                                 human_reviewed=False, ai_notice_required=True)
                if count == 1:
                    self.assertEqual(self.article()['notice_count'], 1)
                else:
                    with self.assertRaisesRegex(ContentError, 'Translation AI notice'):
                        self.article()

    def test_ai_only_translation_cannot_drop_source_image(self):
        self.source_image()
        self.translation(BODY + NOTICE, remove=('human_edit', 'notice_present', 'images'),
                         human_reviewed=False, ai_notice_required=True)
        with self.assertRaisesRegex(ContentError, 'image inventory mismatch'):
            self.article()


class HumanGeneratedSiteTests(unittest.TestCase):
    def test_all_twenty_translated_notices_link_the_matching_english_reader(self):
        from i18n import load_locales
        from routes import initialize_routes
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model, _, _, theme, output = site_fixture(root)
            locales = load_locales(Path(__file__).resolve().parents[1] / 'locales')
            template = copy.deepcopy(model['articles']['af'][0])
            for tag, locale in locales.items():
                if tag == 'en':
                    continue
                article = copy.deepcopy(template)
                article.update(locale=tag, language=tag, direction=locale['meta']['dir'],
                               human_reviewed=True, ai_notice_required=False, notice_count=1)
                article['html'] = re.sub(r'<aside.*?</aside>',
                    f'<aside data-translation-notice="human"><p>{locale["ui"]["english_authoritative"]} '
                    f'<a href="/en/articles/{article["id"]}/">{locale["ui"]["read_english"]}</a></p></aside>', article['html'])
                model['articles'][tag] = [article]
            routes = initialize_routes(model, locales, root / 'all-locale-routes.json', update=True)
            site = Site(model, locales, routes, theme, output, {})
            verified = 0
            for tag, articles in model['articles'].items():
                if tag == 'en':
                    continue
                article = articles[0]
                site.article_page(tag, article)
                expected = routes['articles']['en'][article['id']]
                for path in (output / article['url'].lstrip('/') / 'index.html',
                             output / article['markdown_url'].lstrip('/')):
                    notice = re.search(r'<aside data-translation-notice="human">.*?</aside>', path.read_text()).group()
                    self.assertIn(f'href="{expected}"', notice)
                    self.assertNotIn('href="/en/"', notice)
                    self.assertNotIn(f'/en/articles/{article["id"]}/', notice)
                verified += 1
            self.assertEqual(verified, 20)

    def test_reader_and_markdown_keep_human_footer_even_when_ai_notice_is_not_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, locales, routes, theme, output = site_fixture(Path(temporary))
            article = model['articles']['af'][0]
            article.update(human_reviewed=True, ai_notice_required=False,
                           human_edit=copy.deepcopy(HUMAN_EDIT), notice_present=True,
                           notice_count=1)
            article['html'] = article['html'].replace('KI-vertaling.', 'Human-edited footer retained verbatim.').replace('data-translation-notice="ai"', 'data-translation-notice="human"')
            Site(model, locales, routes, theme, output, {}).build()
            checker = SiteChecker(output)
            self.assertEqual(checker.run(model=model, locales=locales, routes=routes, theme=theme), [])
            reader = output / article['url'].lstrip('/') / 'index.html'
            markdown_path = output / article['markdown_url'].lstrip('/')
            for path in (reader, markdown_path):
                self.assertIn('Human-edited footer retained verbatim.', path.read_text())
            self.assertEqual(checker.pages[article['url']].notices, 1)
            markdown = markdown_path.read_text()
            self.assertEqual(PageParser(article['markdown_url'], markdown).page.notices, 1)

            # The checker still protects the editor's exported presentation.
            markdown_path.write_text(markdown.replace('data-translation-notice="human"', 'data-editor-note="removed"'))
            errors = SiteChecker(output).run(model=model, locales=locales, routes=routes, theme=theme)
            self.assertTrue(any('AI notice parity mismatch' in error for error in errors), errors)


if __name__ == '__main__':
    unittest.main()
