"""Offline publication histories keep approved bodies, provenance, and image bytes.

The three source revisions intentionally disagree: the translation's original
English is older than the last published English, and the current archive has
changed or removed both.  Historical reads use the real source parser over
immutable in-memory files; no Git, network, or source-repository writes occur.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from content import ContentError, load_content
from historical_source import (ARTICLE_FIELDS, HistoricalError,
                               HistoricalFileMissing, HistoricalSources,
                               REPOSITORY)
from publication_inventory import assert_retains
from retention import PublicationRetention, ledger_digest


def identity(number):
    return f'00000000-0000-4000-8000-{number:012x}'


A, B, I, C, T, S, NEW_I, NEW_C, NEW_T, NEW_S = map(identity, range(1, 11))
ORIGINAL, DEPLOYED, CURRENT, NEXT, THIRD, TRANSLATIONS = (char * 40 for char in 'abcdef')
IMAGE = f'/images/articles/{A}-1.jpg'
HUMAN_IMAGE = '/images/articles/editor-approved.jpg'
ORIGINAL_IMAGE = b'original translation source image\x00'
DEPLOYED_IMAGE = b'last publicly deployed shared image\x01'
CURRENT_IMAGE = b'new English source image\x02'
HUMAN_BYTES = b'last publicly deployed human-selected image\x03'
REGISTRY = {'afr': {'name': 'Afrikaans', 'native_name': 'Afrikaans',
                    'tag': 'af', 'dir': 'ltr'}}
HUMAN_EDIT = {'commit': '1' * 40, 'author': 'Repository Editor',
              'email': 'editor@example.test', 'time': '2026-10-01T12:00:00+00:00'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8'))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


def files_at(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


def refresh_manifest(root):
    manifest = json.loads((root / 'manifest.json').read_bytes())
    manifest['files'] = {name: digest(raw) for name, raw in files_at(root).items()
                         if name != 'manifest.json'}
    write_json(root / 'manifest.json', manifest)


def catalogue(*, current=False):
    issue, category, topic, series = ((NEW_I, NEW_C, NEW_T, NEW_S) if current
                                     else (I, C, T, S))
    prefix = 'Current' if current else 'Original'
    return {'format_version': '2.0',
            'issues': [{'id': issue, 'slug': prefix.lower() + '-issue',
                        'publication': prefix + ' magazine', 'date': {'year': 2024 if current else 2020}}],
            'categories': [{'id': category, 'slug': prefix.lower() + '-category',
                            'name': prefix + ' category'}],
            'topics': [{'id': topic, 'name': prefix + ' topic'}],
            'series': [{'id': series, 'name': prefix + ' series'}]}


def source_article(*, current=False, added=False):
    article_id = B if added else A
    article = {'id': article_id, 'issue_id': NEW_I if current else I,
               'sequence': 2 if added else 1,
               'title': 'Unrelated new article' if added else ('Current title' if current else 'Original title'),
               'subtitle': None, 'section': '', 'byline': {'raw': 'Printed Name'},
               'categories': {'primary': NEW_C if current else C, 'additional': []},
               'topics': [NEW_T if current else T],
               'series': {'id': NEW_S if current else S, 'part': 1},
               'images': [] if added else [{'public_path': IMAGE, 'repository_path': 'public' + IMAGE,
                                             'alt': 'Printed illustration', 'credit': 'Original photographer'}],
               'rights': {'status': 'eligible', 'article_specific_permission_notice_detected': False},
               'source_pages': {'start': 3, 'end': 5},
               'html': {'repository_path': f'content/articles/{article_id}.html'}, 'language': 'en'}
    return article


def body(article_id, words, image=IMAGE):
    illustration = (f'\r\n<figure><img src="{image}" alt="Gedrukte beeld">'
                    '<figcaption>Oorspronklike byskrif.</figcaption></figure>') if image else ''
    return f'<article data-article-id="{article_id}">\r\n<p>{words}</p>{illustration}\r\n</article>\r\n'


def historical_files(article, html, image_bytes):
    raw_article = copy.deepcopy(article)
    raw_article.update(verification={'private': 'reviewer'}, source_labels={'private': 'labels'})
    raw_catalogue = catalogue()
    raw_catalogue.update(normalization=[{'private': 'normalization'}], review_candidates=['private review'])
    return {'index.json': encoded({'format_version': '2.0', 'articles': [raw_article], 'skipped': []}),
            'catalogue.json': encoded(raw_catalogue),
            article['html']['repository_path']: html.encode('utf-8'),
            'public' + IMAGE: image_bytes, 'public' + HUMAN_IMAGE: HUMAN_BYTES}


def retained_source(article, html):
    # This is the upstream six-field frozen snapshot, including exact CRLF HTML.
    fingerprints = {'html_sha256': digest(html.encode('utf-8')),
                    'metadata_sha256': canonical(article), 'text_sha256': '1' * 64,
                    'structure_sha256': '2' * 64, 'translation_metadata_sha256': '3' * 64}
    snapshot = {'repository': REPOSITORY, 'revision': ORIGINAL,
                'article': {key: copy.deepcopy(article.get(key)) for key in ARTICLE_FIELDS},
                'fingerprints': fingerprints,
                'translation_key': canonical({key: fingerprints[key] for key in (
                    'text_sha256', 'structure_sha256', 'translation_metadata_sha256')}), 'html': html}
    return {'repository': REPOSITORY, 'revision': ORIGINAL, 'article_id': A,
            'html_repository_path': f'content/articles/{A}.html',
            'index_repository_path': 'index.json', 'catalogue_repository_path': 'catalogue.json',
            'html_sha256': fingerprints['html_sha256'], 'metadata_sha256': fingerprints['metadata_sha256'],
            'translation_key': snapshot['translation_key'], 'fingerprints': fingerprints,
            'article': snapshot['article'], 'snapshot_sha256': canonical(snapshot)}


class OfflineHistory(HistoricalSources):
    def __init__(self, revisions):
        self.revisions = copy.deepcopy(revisions)
        self.requests = []

    def read(self, revision, path):
        self.requests.append((revision, path))
        if revision not in self.revisions:
            raise HistoricalError('Unknown immutable fixture revision')
        try:
            return self.revisions[revision][path]
        except KeyError as error:
            raise HistoricalFileMissing(f'{revision}:{path}') from error


def deployment(*, revision=DEPLOYED, inventory=None, ledger=None):
    result = {'schema': 1, 'display_fingerprint': '9' * 64,
              'revisions': {'site': '7' * 40, 'english': revision,
                            'translations': TRANSLATIONS, 'theme': '8' * 40},
              'translation_status': 'ready',
              'article_inventory': inventory or {'en': [A], 'af': [A]}}
    if ledger is not None:
        result['retention'] = copy.deepcopy(ledger)
    return result


def model_inventory(model):
    return {tag: sorted(article['id'] for article in articles)
            for tag, articles in model['articles'].items()}


class PublicationRetentionIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.en, self.tr = self.root / 'english', self.root / 'translations'
        self.original = source_article()
        self.original_html = body(A, 'Original English: café, 信仰.')
        self.published = source_article()
        self.published['title'] = 'Last published English title'
        self.published_html = body(A, 'Last published English, revised after translation.')
        self.history = OfflineHistory({
            ORIGINAL: historical_files(self.original, self.original_html, ORIGINAL_IMAGE),
            DEPLOYED: historical_files(self.published, self.published_html, DEPLOYED_IMAGE),
        })
        original_raw = json.loads(self.history.revisions[ORIGINAL]['index.json'])['articles'][0]
        self.spec = retained_source(original_raw, self.original_html)
        self.previous = deployment()
        self.current_html = body(A, 'Current English has unrelated new wording.')
        self.translation_html = body(A, 'Goedgekeurde ou woorde: café, 信仰.') + (
            f'<aside data-translation-notice="ai"><p>KI-vertaling. '
            f'<a href="/en/articles/{A}/">English</a></p></aside>\r\n')
        self.write_english()
        self.write_translation()

    def write_english(self, *, removed=False, revision=CURRENT):
        # Each publication has a fresh export directory, including a new article.
        self.en = self.root / ('english-' + revision[:1])
        if self.en.exists():
            shutil.rmtree(self.en)
        article = source_article(current=True)
        added = source_article(current=True, added=True)
        articles = [added] if removed else [article, added]
        write_json(self.en / 'index.json', {'format_version': '2.0', 'articles': articles,
                                          'export': {'source_revision': revision}})
        write_json(self.en / 'catalogue.json', catalogue(current=True))
        for item in articles:
            path = self.en / item['html']['repository_path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((body(B, 'New unrelated English stays published.', None)
                              if item['id'] == B else self.current_html).encode('utf-8'))
        if not removed:
            image = self.en / IMAGE.lstrip('/')
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(CURRENT_IMAGE)
        write_json(self.en / 'manifest.json', {'format_version': '2.0', 'base_path': '/',
                                               'source_revision': revision,
                                               'counts': {'articles': len(articles)}})
        refresh_manifest(self.en)
        # This revision genuinely lacks A after removal, including its old asset.
        historical = files_at(self.en)
        historical['index.json'] = encoded({'format_version': '2.0', 'articles': articles, 'skipped': []})
        if not removed:
            historical['public' + IMAGE] = CURRENT_IMAGE
        self.history.revisions[revision] = historical

    def write_translation(self, *, removed=False, revision=CURRENT, human=False,
                          translation_revision=TRANSLATIONS):
        html = body(A, 'Menslik hersiene woorde: café, 信仰.', HUMAN_IMAGE) if human else self.translation_html
        metadata = {'title': 'Goedgekeurde titel', 'subtitle': None, 'section': ''}
        item = dict(metadata, id=A, issue_id=I, language='afr', language_tag='af', direction='ltr',
                    human_reviewed=human, ai_notice_required=not human,
                    status='source_removed' if removed else 'stale', retained=True,
                    retention_reason='english_removed' if removed else 'english_changed',
                    current_source_translation_key=None if removed else '4' * 64,
                    source_revision=ORIGINAL, source_translation_key=self.spec['translation_key'],
                    retained_source=copy.deepcopy(self.spec), html=f'content/afr/articles/{A}.html',
                    metadata=f'content/afr/articles/{A}.json', html_sha256=digest(html.encode('utf-8')))
        if human:
            item.update(human_edit=copy.deepcopy(HUMAN_EDIT), notice_present=False,
                        images=[{'public_path': HUMAN_IMAGE, 'alt': 'Gedrukte beeld'}])
        html_path = self.tr / item['html']
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_bytes(html.encode('utf-8'))
        write_json(self.tr / item['metadata'], metadata)
        write_json(self.tr / 'index.json', {'format_version': '1.0', 'source_revision': revision,
                                          'translation_revision': translation_revision, 'articles': [item]})
        write_json(self.tr / 'manifest.json', {'format_version': '1.0', 'base_path': '/',
                                               'source_revision': revision, 'translation_revision': translation_revision,
                                               'article_count': 1, 'omitted': []})
        refresh_manifest(self.tr)
        return item, html

    def context(self, *, previous=None, revision=CURRENT, **kwargs):
        return PublicationRetention(previous or self.previous, None, current_root=self.en,
                                    current_revision=revision, cache_dir=self.root / 'cache',
                                    history=self.history, **kwargs)

    def load(self, *, previous=None, revision=CURRENT, **kwargs):
        return load_content(self.en, self.tr, strict_translations=True, language_registry=REGISTRY,
                            retention=self.context(previous=previous, revision=revision, **kwargs))

    def change_translation(self, change):
        index = json.loads((self.tr / 'index.json').read_bytes())
        change(index['articles'][0])
        write_json(self.tr / 'index.json', index)
        refresh_manifest(self.tr)

    @staticmethod
    def article(model, locale, article_id=A):
        return next(item for item in model['articles'][locale] if item['id'] == article_id)

    def assert_copy(self, model, path, expected):
        copies = {item['public_path']: item for item in model['retained_asset_copies']}
        self.assertIn(path, copies)
        self.assertEqual(Path(copies[path]['source']).read_bytes(), expected)
        self.assertEqual(copies[path]['sha256'], digest(expected))

    def test_changed_english_keeps_approved_ai_body_and_last_published_images(self):
        before = (files_at(self.en), files_at(self.tr), copy.deepcopy(self.history.revisions))
        model = self.load()
        english, translated = self.article(model, 'en'), self.article(model, 'af')
        pinned = f'/images/articles/retained/{digest(DEPLOYED_IMAGE)}/{A}-1.jpg'
        self.assertEqual(translated['html'].encode('utf-8'),
                         self.translation_html.replace(IMAGE, pinned).encode('utf-8'))
        self.assertEqual(translated['text'], 'Goedgekeurde ou woorde: café, 信仰.\nOorspronklike byskrif.')
        self.assertFalse(translated['human_reviewed'])
        self.assertTrue(translated['ai_notice_required'])
        self.assertEqual(translated['notice_count'], 1)
        self.assertEqual(translated['translation']['status'], 'stale')
        self.assertEqual(translated['translation']['retention_reason'], 'english_changed')
        self.assertEqual(translated['source_revision'], ORIGINAL)
        self.assertEqual(translated['issue_id'], I)
        self.assertEqual(translated['issue']['publication'], 'Original magazine')
        self.assertEqual(translated['images'][0]['credit'], 'Original photographer')
        self.assertEqual(english['html'], self.current_html)
        self.assertEqual(english['issue_id'], NEW_I)
        self.assertEqual(english['source_revision'], CURRENT)
        self.assertEqual(english['images'][0]['public_path'], IMAGE)
        self.assert_copy(model, pinned, DEPLOYED_IMAGE)
        self.assertNotIn(IMAGE, {item['public_path'] for item in model['retained_asset_copies']})
        self.assertEqual(model['retention']['aliases'][IMAGE]['sha256'], digest(CURRENT_IMAGE))
        self.assertEqual(model['retention']['images']['af'][A][IMAGE]['revision'], DEPLOYED)
        self.assertEqual(before, (files_at(self.en), files_at(self.tr), self.history.revisions))
        self.assertIsNone(assert_retains(self.previous['article_inventory'], model_inventory(model)))

    def test_human_reviewed_retained_body_and_custom_image_keep_editorial_provenance(self):
        _, html = self.write_translation(human=True)
        model = self.load()
        translated = self.article(model, 'af')
        pinned = '/images/articles/retained/' + digest(HUMAN_BYTES) + '/editor-approved.jpg'
        self.assertEqual(translated['html'], html.replace(HUMAN_IMAGE, pinned))
        self.assertTrue(translated['human_reviewed'])
        self.assertFalse(translated['ai_notice_required'])
        self.assertFalse(translated['notice_present'])
        self.assertEqual(translated['notice_count'], 0)
        self.assertEqual(translated['human_edit'], HUMAN_EDIT)
        self.assertEqual(translated['source_metadata']['title'], 'Original title')
        self.assertEqual(translated['translation']['retained_source'], self.spec)
        self.assert_copy(model, pinned, HUMAN_BYTES)
        self.assert_copy(model, HUMAN_IMAGE, HUMAN_BYTES)

    def test_new_approved_human_image_is_allowed_with_complete_prior_ledger(self):
        first = self.load()
        previous = deployment(revision=CURRENT, inventory=model_inventory(first), ledger=first['retention'])
        self.assertNotIn(HUMAN_IMAGE, previous['retention']['images']['af'][A])
        self.assertNotIn('public' + HUMAN_IMAGE, self.history.revisions[CURRENT])
        _, html = self.write_translation(human=True, translation_revision='6' * 40)
        model = self.load(previous=previous)
        translated = self.article(model, 'af')
        origin = model['retention']['images']['af'][A][HUMAN_IMAGE]
        self.assertEqual(translated['human_edit'], HUMAN_EDIT)
        self.assertEqual(translated['html'], html.replace(HUMAN_IMAGE, origin['public_path']))
        self.assertEqual(origin['revision'], ORIGINAL)
        self.assertEqual(model['translation_revision'], '6' * 40)
        self.assert_copy(model, origin['public_path'], HUMAN_BYTES)
        self.assert_copy(model, HUMAN_IMAGE, HUMAN_BYTES)
        self.assertEqual(model['retention']['images']['en'][A][IMAGE]['revision'], CURRENT)
        self.assertIsNone(assert_retains(previous['article_inventory'], model_inventory(model)))

    def test_removed_english_uses_last_publication_not_older_translation_source(self):
        self.write_english(removed=True)
        self.write_translation(removed=True)
        model = self.load()
        english, translated = self.article(model, 'en'), self.article(model, 'af')
        pinned = f'/images/articles/retained/{digest(DEPLOYED_IMAGE)}/{A}-1.jpg'
        self.assertEqual(english['title'], 'Last published English title')
        self.assertEqual(english['html'], self.published_html.replace(IMAGE, pinned))
        self.assertEqual(english['source_revision'], DEPLOYED)
        self.assertEqual(english['retention']['status'], 'source_removed')
        self.assertEqual(translated['source_revision'], ORIGINAL)
        self.assertEqual(translated['source_metadata']['title'], 'Original title')
        self.assertEqual(translated['translation']['status'], 'source_removed')
        self.assertIsNone(translated['translation']['current_source_translation_key'])
        self.assertEqual(translated['translation']['retention_reason'], 'english_removed')
        self.assertEqual(model['current_english_ids'], {B})
        self.assertEqual(model_inventory(model), {'en': [A, B], 'af': [A]})
        self.assertEqual(self.article(model, 'en', B)['title'], 'Unrelated new article')
        for group, old_id, new_id in [('issues', I, NEW_I), ('categories', C, NEW_C),
                                      ('topics', T, NEW_T), ('series', S, NEW_S)]:
            self.assertEqual({item['id'] for item in model[group]}, {old_id, new_id})
        self.assertNotIn('verification', english['source_metadata'])
        self.assertNotIn('source_labels', english['source_metadata'])
        self.assert_copy(model, pinned, DEPLOYED_IMAGE)
        self.assert_copy(model, IMAGE, DEPLOYED_IMAGE)
        self.assertEqual(model['retention']['english_sources'], {A: DEPLOYED, B: CURRENT})

    def test_second_and_third_publications_reuse_article_and_image_origins(self):
        previous = self.previous
        for revision in (CURRENT, NEXT, THIRD):
            with self.subTest(publication=revision[0]):
                self.write_english(removed=True, revision=revision)
                self.write_translation(removed=True, revision=revision)
                self.history.requests.clear()
                model = self.load(previous=previous, revision=revision)
                english, translated = self.article(model, 'en'), self.article(model, 'af')
                self.assertEqual(english['source_revision'], DEPLOYED)
                self.assertEqual(translated['source_revision'], ORIGINAL)
                self.assertEqual(model['retention']['english_sources'], {A: DEPLOYED, B: revision})
                for tag in ('en', 'af'):
                    origin = model['retention']['images'][tag][A][IMAGE]
                    self.assertEqual(origin['revision'], DEPLOYED)
                    self.assertEqual(origin['sha256'], digest(DEPLOYED_IMAGE))
                    self.assert_copy(model, origin['public_path'], DEPLOYED_IMAGE)
                self.assertEqual(model['retention']['aliases'][IMAGE]['revision'], DEPLOYED)
                self.assert_copy(model, IMAGE, DEPLOYED_IMAGE)
                self.assertTrue(all(pin in {ORIGINAL, DEPLOYED} for pin, _ in self.history.requests))
                self.assertIsNone(assert_retains(previous['article_inventory'], model_inventory(model)))
                previous = deployment(revision=revision, inventory=model_inventory(model), ledger=model['retention'])

    def test_later_removal_preserves_distinct_english_translation_and_alias_bytes(self):
        # A successful changed-source publication already froze the old translation
        # image, while English and the original URL still served the newer image.
        changed = self.load()
        previous = deployment(revision=CURRENT, inventory=model_inventory(changed), ledger=changed['retention'])
        for revision in (NEXT, THIRD):
            with self.subTest(publication=revision[0]):
                self.write_english(removed=True, revision=revision)
                self.write_translation(removed=True, revision=revision)
                model = self.load(previous=previous, revision=revision)
                english = self.article(model, 'en')
                translated = self.article(model, 'af')
                english_image = f'/images/articles/retained/{digest(CURRENT_IMAGE)}/{A}-1.jpg'
                translated_image = f'/images/articles/retained/{digest(DEPLOYED_IMAGE)}/{A}-1.jpg'
                self.assertEqual(english['html'], self.current_html.replace(IMAGE, english_image))
                self.assertEqual(english['source_revision'], CURRENT)
                self.assertEqual(english['issue_id'], NEW_I)
                self.assertEqual(translated['html'], self.translation_html.replace(IMAGE, translated_image))
                self.assertEqual(translated['issue_id'], I)
                self.assert_copy(model, english_image, CURRENT_IMAGE)
                self.assert_copy(model, translated_image, DEPLOYED_IMAGE)
                self.assert_copy(model, IMAGE, CURRENT_IMAGE)
                self.assertEqual(model['retention']['aliases'][IMAGE]['revision'], CURRENT)
                self.assertIsNone(assert_retains(previous['article_inventory'], model_inventory(model)))
                previous = deployment(revision=revision, inventory=model_inventory(model), ledger=model['retention'])

    def test_unknown_omitted_translation_still_blocks_publication_despite_english_growth(self):
        index = json.loads((self.tr / 'index.json').read_bytes())
        index['articles'] = []
        write_json(self.tr / 'index.json', index)
        manifest = json.loads((self.tr / 'manifest.json').read_bytes())
        manifest.update(article_count=0, omitted=[{'id': A, 'language': 'afr', 'reason': 'unknown'}])
        write_json(self.tr / 'manifest.json', manifest)
        refresh_manifest(self.tr)
        model = self.load()
        self.assertEqual(model['translation_status'], 'ready')
        self.assertEqual(len(model['articles']['en']), 2)
        with self.assertRaisesRegex(ValueError, 'af: locale disappeared'):
            assert_retains(self.previous['article_inventory'], model_inventory(model))

    def test_unrelated_ready_translation_cannot_hide_an_unknown_omitted_article(self):
        index = json.loads((self.tr / 'index.json').read_bytes())
        item = index['articles'][0]
        for field in ('retained', 'retention_reason', 'retained_source', 'current_source_translation_key'):
            item.pop(field)
        html = body(B, 'Nuwe goedgekeurde vertaling.', None) + (
            f'<aside data-translation-notice="ai"><p>KI-vertaling. '
            f'<a href="/en/articles/{B}/">English</a></p></aside>')
        item.update(id=B, issue_id=NEW_I, status='ready', source_revision=CURRENT,
                    source_translation_key='5' * 64, html=f'content/afr/articles/{B}.html',
                    metadata=f'content/afr/articles/{B}.json', html_sha256=digest(html.encode('utf-8')))
        (self.tr / item['html']).write_bytes(html.encode('utf-8'))
        write_json(self.tr / item['metadata'], {key: item[key] for key in ('title', 'subtitle', 'section')})
        write_json(self.tr / 'index.json', index)
        manifest = json.loads((self.tr / 'manifest.json').read_bytes())
        manifest['omitted'] = [{'id': A, 'language': 'afr', 'reason': 'unknown'}]
        write_json(self.tr / 'manifest.json', manifest)
        refresh_manifest(self.tr)
        model = self.load()
        self.assertEqual(model_inventory(model), {'en': [A, B], 'af': [B]})
        self.assertEqual(self.article(model, 'af', B)['html'], html)
        with self.assertRaisesRegex(ValueError, 'af: 1 published article UUID.*' + A):
            assert_retains(self.previous['article_inventory'], model_inventory(model))

    def test_retained_entry_requires_a_verified_publication_context(self):
        with self.assertRaisesRegex(ContentError, 'verified publication history'):
            load_content(self.en, self.tr, strict_translations=True, language_registry=REGISTRY)

    def test_current_and_removed_status_must_match_selected_english_archive(self):
        for removed in (False, True):
            with self.subTest(removed=removed):
                self.write_english(removed=removed)
                self.write_translation(removed=not removed)
                with self.assertRaisesRegex(ContentError, 'status disagrees'):
                    self.load()

    def test_retention_status_reason_and_current_fingerprint_are_explicit(self):
        variants = [({'retained': False}, 'compatibility state'),
                    ({'retention_reason': 'english_removed'}, 'reason disagrees'),
                    ({'current_source_translation_key': None}, 'distinct current fingerprint'),
                    ({'current_source_translation_key': self.spec['translation_key']}, 'distinct current fingerprint'),
                    ({'current_source_translation_key': 'not-a-digest'}, 'distinct current fingerprint'),
                    ({'status': 'ready'}, 'cannot claim retained')]
        for change, message in variants:
            with self.subTest(change=change):
                self.write_translation()
                self.change_translation(lambda item: item.update(change))
                with self.assertRaisesRegex(ContentError, message):
                    self.load()
        self.write_english(removed=True)
        self.write_translation(removed=True)
        self.change_translation(lambda item: item.update(current_source_translation_key='4' * 64))
        with self.assertRaisesRegex(ContentError, 'must not claim a current fingerprint'):
            self.load()

    def test_frozen_snapshot_and_original_issue_cannot_be_changed_by_current_metadata(self):
        variants = [({'snapshot_sha256': '0' * 64}, 'snapshot checksum'),
                    ({'translation_key': '0' * 64}, 'fingerprint differs'),
                    ({'revision': DEPLOYED}, 'identity or revision mismatch'),
                    ({'repository': 'someone/other-source'}, 'identity or revision mismatch'),
                    ({'article_id': B}, 'identity or revision mismatch'),
                    ({'html_repository_path': '../untrusted.html'}, 'paths mismatch')]
        for change, message in variants:
            with self.subTest(change=change):
                self.write_translation()
                self.change_translation(lambda item: item['retained_source'].update(change))
                with self.assertRaisesRegex(ContentError, message):
                    self.load()
        self.write_translation()
        self.change_translation(lambda item: item.update(issue_id=NEW_I))
        with self.assertRaisesRegex(ContentError, 'issue differs from its original source'):
            self.load()

    def test_current_export_and_translation_revision_pins_must_match_context(self):
        with self.assertRaisesRegex(ContentError, 'different current English revision'):
            self.load(revision=NEXT)
        pins = {'site': '7' * 40, 'english': CURRENT, 'translations': NEXT, 'theme': '8' * 40}
        with self.assertRaisesRegex(ContentError, 'different translation revision'):
            self.load(source_revisions=pins)

    def test_unavailable_original_snapshot_html_fails_closed_even_with_current_html(self):
        del self.history.revisions[ORIGINAL][f'content/articles/{A}.html']
        with self.assertRaises(ContentError):
            self.load()

    def test_corrupt_recorded_image_origin_does_not_fall_back_to_current_bytes(self):
        first = self.load()
        previous = deployment(revision=CURRENT, inventory=model_inventory(first), ledger=first['retention'])
        previous['retention']['images']['af'][A][IMAGE]['sha256'] = '0' * 64
        # A self-consistent ledger still cannot assert bytes absent from its
        # actual immutable historical origin.
        previous['retention']['sha256'] = ledger_digest(previous['retention'])
        with self.assertRaisesRegex(ContentError, 'no longer match their recorded origin'):
            self.load(previous=previous)

    def test_incomplete_prior_article_or_locale_ledger_fails_closed(self):
        first = self.load()
        baseline = deployment(revision=CURRENT, inventory=model_inventory(first), ledger=first['retention'])
        removals = [lambda ledger: ledger['english_sources'].pop(A),
                    lambda ledger: ledger['images'].pop('af'),
                    lambda ledger: ledger['images']['af'].pop(A),
                    lambda ledger: ledger['images']['en'].pop(B)]
        for remove in removals:
            with self.subTest(remove=remove):
                previous = copy.deepcopy(baseline)
                remove(previous['retention'])
                with self.assertRaises(ValueError):
                    self.load(previous=previous)

    def test_previously_recorded_image_origin_cannot_be_omitted(self):
        first = self.load()
        previous = deployment(revision=CURRENT, inventory=model_inventory(first), ledger=first['retention'])
        del previous['retention']['images']['af'][A][IMAGE]
        self.history.requests.clear()
        # Falling back to CURRENT here would silently replace the old approved
        # translation's image with different bytes, despite an existing ledger.
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.load(previous=previous)
        self.assertEqual(self.history.requests, [])


if __name__ == '__main__':
    unittest.main()
