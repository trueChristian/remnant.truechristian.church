import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.content import ContentError, FragmentText, excerpt, load_content, ordered_issues
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


if __name__ == '__main__':
    unittest.main()
