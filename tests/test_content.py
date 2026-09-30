import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.content import ContentError, FragmentText, excerpt, load_content, load_language_registry, ordered_issues
from scripts.export_sources import ExportError, export_sources

A = '00000000-0000-4000-8000-000000000001'
I = '00000000-0000-4000-8000-000000000002'
C = '00000000-0000-4000-8000-000000000003'
SHA = 'a' * 40


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


def inventory(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and p.name != 'manifest.json'}


def fixture(root, translated=False, selected_revision=SHA, notice=True, human=False):
    article = {'id': A, 'issue_id': I, 'sequence': 2, 'title': 'The source title', 'subtitle': None, 'section': '', 'byline': {'raw': 'Printed Name'}, 'source_pages': {'start': 3, 'end': 5}, 'categories': {'primary': C, 'additional': []}, 'topics': [], 'images': [], 'html': {'repository_path': f'content/articles/{A}.html'}, 'language': 'en'}
    html = f'<article data-article-id="{A}"><p>Exact words and <em>meaning</em>.</p></article>'
    if not translated:
        path = root / article['html']['repository_path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html)
        write_json(root / 'index.json', {'format_version': '2.0', 'articles': [article], 'export': {'source_revision': selected_revision}})
        write_json(root / 'catalogue.json', {'format_version': '2.0', 'issues': [{'id': I, 'slug': 'spring-2024', 'date': {'year': 2024, 'season': 'Spring', 'precision': 'season'}}], 'categories': [{'id': C, 'slug': 'faith', 'name': 'Faith'}], 'topics': [], 'series': []})
        manifest = {'format_version': '2.0', 'source_revision': selected_revision, 'base_path': '/', 'counts': {'articles': 1}}
    else:
        if notice:
            html += f'<aside data-translation-notice="ai"><p>AI notice. <a href="/en/articles/{A}/">English</a></p></aside>'
        path = root / f'content/afr/articles/{A}.html'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html)
        metadata = {'title': 'Die titel', 'subtitle': None, 'section': ''}
        write_json(path.with_suffix('.json'), metadata)
        item = dict(metadata, id=A, issue_id=I, language='afr', language_tag='af', direction='ltr', human_reviewed=human, ai_notice_required=not human, status='ready', source_revision='b' * 40, source_translation_key='opaque', html=path.relative_to(root).as_posix(), metadata=path.with_suffix('.json').relative_to(root).as_posix(), html_sha256=hashlib.sha256(html.encode()).hexdigest())
        write_json(root / 'index.json', {'format_version': '1.0', 'source_revision': selected_revision, 'translation_revision': 'c' * 40, 'articles': [item]})
        manifest = {'format_version': '1.0', 'source_revision': selected_revision, 'translation_revision': 'c' * 40, 'base_path': '/', 'article_count': 1, 'omitted': []}
    manifest['files'] = inventory(root)
    write_json(root / 'manifest.json', manifest)
    return article, html


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.en, self.tr = self.root / 'en', self.root / 'translations'
        fixture(self.en)

    def tearDown(self):
        self.temp.cleanup()

    def test_english_only_is_explicit_and_authoritative(self):
        model = load_content(self.en)
        self.assertEqual(model['translation_status'], 'unavailable')
        self.assertEqual(len(model['articles']['en']), 1)
        self.assertTrue(model['warnings'])
        self.assertEqual(model['articles']['en'][0]['text'], 'Exact words and meaning.')
        self.assertEqual(model['articles']['en'][0]['byline']['raw'], 'Printed Name')

    def test_current_scan_not_historical_whole_repository_sha(self):
        _, html = fixture(self.tr, translated=True)
        model = load_content(self.en, self.tr, strict_translations=True)
        article = model['articles']['af'][0]
        self.assertEqual(article['html'], html)
        self.assertEqual(article['title'], 'Die titel')
        self.assertEqual(article['byline']['raw'], 'Printed Name')
        self.assertNotIn('AI notice', article['text'])
        self.assertNotEqual(article['translation']['source_revision'], model['source_revision'])

    def test_stale_scan_never_carried_forward(self):
        fixture(self.tr, translated=True, selected_revision='d' * 40)
        model = load_content(self.en, self.tr)
        self.assertEqual(model['translation_status'], 'failed')
        self.assertEqual(set(model['articles']), {'en'})
        with self.assertRaises(ContentError):
            load_content(self.en, self.tr, strict_translations=True)

    def test_missing_notice_cannot_publish_unreviewed_translation(self):
        fixture(self.tr, translated=True, notice=False)
        self.assertEqual(set(load_content(self.en, self.tr)['articles']), {'en'})

    def test_human_review_not_required_but_removes_notice(self):
        fixture(self.tr, translated=True, notice=False, human=True)
        article = load_content(self.en, self.tr)['articles']['af'][0]
        self.assertTrue(article['human_reviewed'])
        self.assertFalse(article['ai_notice_required'])

    def test_english_integrity_failure_is_fatal(self):
        (self.en / f'content/articles/{A}.html').write_text('corruption')
        with self.assertRaisesRegex(ContentError, 'checksum mismatch'):
            load_content(self.en, self.tr)

    def test_translation_integrity_failure_is_explicit_degradation(self):
        fixture(self.tr, translated=True)
        (self.tr / f'content/afr/articles/{A}.html').write_text('corruption')
        model = load_content(self.en, self.tr)
        self.assertEqual(model['translation_status'], 'failed')
        self.assertNotIn('af', model['articles'])

    def test_safe_path_and_symlinks(self):
        manifest = json.loads((self.en / 'manifest.json').read_text())
        manifest['files']['../outside'] = 'x'
        write_json(self.en / 'manifest.json', manifest)
        with self.assertRaisesRegex(ContentError, 'Unsafe exported path'):
            load_content(self.en)

    def test_excerpt_is_source_prefix_including_cjk(self):
        self.assertEqual(excerpt('An exact phrase repeated here', 16), 'An exact phrase…')
        self.assertEqual(excerpt('这是一个没有空格的段落', 5), '这是一个没…')

    def test_issue_chronology_does_not_invent_dates(self):
        model = {'issues': [{'id': 'summer', 'date': {'year': 2024, 'season': 'Summer', 'precision': 'season'}}, {'id': 'old', 'date': {'year': 2018}}, {'id': 'autumn', 'date': {'year': 2024, 'season': 'Autumn', 'precision': 'season'}}, {'id': 'tie', 'date': {'year': 2024, 'season': 'Autumn', 'precision': 'season'}}]}
        original = copy.deepcopy(model)
        self.assertEqual([i['id'] for i in ordered_issues(model)], ['autumn', 'tie', 'summer', 'old'])
        self.assertEqual(model, original)

    def test_exporter_fails_english_but_degrades_missing_translations(self):
        en_out, tr_out = self.root / 'out-en', self.root / 'out-tr'
        def fake_run(command, cwd):
            if 'tools/archive.py' in command:
                write_json(en_out / 'manifest.json', {'source_revision': SHA, 'counts': {'articles': 1}})
                return {}
            raise FileNotFoundError('translation checkout missing')
        with patch('scripts.export_sources._run', side_effect=fake_run):
            report = export_sources(self.en, self.root / 'missing', en_out, tr_out)
        self.assertEqual(report['english_status'], 'ready')
        self.assertEqual(report['translation_status'], 'failed')
        self.assertFalse(tr_out.exists())
        with self.assertRaisesRegex(ExportError, 'stale output'):
            export_sources(self.en, None, en_out, tr_out)
        with patch('scripts.export_sources._run', side_effect=ExportError('bad English')):
            with self.assertRaises(ExportError):
                export_sources(self.en, None, self.root / 'fresh', tr_out)


    def test_partial_translation_output_is_quarantined(self):
        en_out, tr_out = self.root / 'partial-en', self.root / 'partial-tr'
        def fake_run(command, cwd):
            if 'tools/archive.py' in command:
                write_json(en_out / 'manifest.json', {'source_revision': SHA, 'counts': {'articles': 1}})
                return {}
            write_json(tr_out / 'index.json', {'untrusted_partial': True})
            raise ExportError('interrupted foreign exporter')
        with patch('scripts.export_sources._run', side_effect=fake_run):
            report = export_sources(self.en, self.tr, en_out, tr_out)
        self.assertEqual(report['translation_status'], 'failed')
        self.assertFalse(tr_out.exists())
        self.assertTrue(Path(report['translation_quarantine']).is_dir())

    def test_full_language_registry_exposes_empty_languages_without_guidance(self):
        registry = {
            'afr': {'name': 'Afrikaans', 'native_name': 'Afrikaans', 'tag': 'af', 'dir': 'ltr', 'aliases': [], 'guidance': 'Translation-only guidance'},
            'jpn': {'name': 'Japanese', 'native_name': '日本語', 'tag': 'ja', 'dir': 'ltr', 'aliases': []},
        }
        path = self.root / 'languages.json'
        write_json(path, registry)
        fixture(self.tr, translated=True)
        model = load_content(self.en, self.tr, language_registry=path)
        self.assertEqual({language['tag'] for language in model['languages'].values()}, {'af', 'ja'})
        self.assertNotIn('ja', model['articles'])
        self.assertNotIn('guidance', model['languages']['afr'])
        self.assertEqual(model['translation_status'], 'ready')

    def test_missing_language_registry_is_explicit_not_an_assumed_fixed_inventory(self):
        model = load_content(self.en)
        self.assertIsNone(model['languages'])
        self.assertTrue(any('language additions cannot be checked' in warning for warning in model['warnings']))
        with self.assertRaises(ContentError):
            load_content(self.en, language_registry=self.root / 'missing-registry.json')

    def test_invalid_and_duplicate_language_registry_is_rejected(self):
        entry = {'name': 'Afrikaans', 'native_name': 'Afrikaans', 'tag': 'af', 'dir': 'ltr'}
        with self.assertRaisesRegex(ContentError, 'Duplicate configured language tag'):
            load_language_registry({'afr': entry, 'zzz': entry})
        entry['dir'] = 'invalid'
        with self.assertRaisesRegex(ContentError, 'direction'):
            load_language_registry({'afr': entry})

    def test_translation_language_must_match_selected_registry(self):
        fixture(self.tr, translated=True)
        registry = {'afr': {'name': 'Afrikaans', 'native_name': 'Afrikaans', 'tag': 'af', 'dir': 'rtl'}}
        model = load_content(self.en, self.tr, language_registry=registry)
        self.assertEqual(model['translation_status'], 'failed')
        self.assertNotIn('af', model['articles'])

    def test_newly_configured_empty_language_reaches_locale_validation(self):
        from scripts.i18n import load_locales, validate_locales
        locales = load_locales(Path(__file__).resolve().parents[1] / 'locales')
        registry = {data['meta']['code']: {'name': data['meta']['native_name'], 'native_name': data['meta']['native_name'], 'tag': tag, 'dir': data['meta']['dir']} for tag, data in locales.items() if tag != 'en'}
        registry['jpn'] = {'name': 'Japanese', 'native_name': '日本語', 'tag': 'ja', 'dir': 'ltr'}
        model = load_content(self.en, language_registry=registry)
        self.assertNotIn('ja', model['articles'])
        with self.assertRaisesRegex(ValueError, 'Upstream language inventory changed'):
            validate_locales(locales, registry=model['languages'])

    def test_exported_html_line_endings_are_not_reserialized(self):
        path = self.en / f'content/articles/{A}.html'
        original = path.read_bytes().replace(b'<p>', b'\r\n<p>').replace(b'</article>', b'\r\n</article>')
        path.write_bytes(original)
        manifest = json.loads((self.en / 'manifest.json').read_text())
        manifest['files'] = inventory(self.en)
        write_json(self.en / 'manifest.json', manifest)
        self.assertEqual(load_content(self.en)['articles']['en'][0]['html'].encode(), original)

    def test_fragment_rejects_document_elements_and_active_urls(self):
        for tag in ['base', 'meta', 'link', 'html', 'head', 'body', 'script', 'iframe']:
            with self.subTest(tag=tag), self.assertRaises(ContentError):
                FragmentText(f'<article data-article-id="{A}"><{tag}></{tag}></article>')
        for url in ['javascript:alert(1)', 'vbscript:msgbox(1)', 'data:text/html,active', 'jav&#x61;script:alert(1)', 'java&#x0a;script:alert(1)', 'file:///private', '//external.test/script']:
            for attribute, tag in [('href', 'a'), ('src', 'img'), ('xlink:href', 'a')]:
                with self.subTest(url=url, attribute=attribute), self.assertRaises(ContentError):
                    FragmentText(f'<article data-article-id="{A}"><{tag} {attribute}="{url}"></{tag}></article>')
        for attribute in ['style="color:red"', 'srcdoc="active"', 'srcset="/external.png 2x"', 'onclick="active()"']:
            with self.subTest(attribute=attribute), self.assertRaises(ContentError):
                FragmentText(f'<article data-article-id="{A}"><p {attribute}>Text</p></article>')

    def test_fragment_allows_passive_links_and_shared_images(self):
        for url in ['https://example.test/', 'http://example.test/', 'mailto:author@example.test', 'tel:+123456', '#source-note', f'/en/articles/{A}/']:
            parsed = FragmentText(f'<article data-article-id="{A}"><a href="{url}">Printed link</a></article>')
            self.assertEqual(parsed.text, 'Printed link')
        image = FragmentText(f'<article data-article-id="{A}"><img src="/images/articles/{A}-1.jpg" alt="Source image"></article>')
        self.assertEqual(image.images[0]['alt'], 'Source image')

    def test_output_symlink_is_rejected(self):
        real = self.root / 'real-output'
        real.mkdir()
        link = self.root / 'linked-output'
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(ExportError, 'absent or empty'):
            export_sources(self.en, None, link, self.root / 'new-output')


if __name__ == '__main__':
    unittest.main()
