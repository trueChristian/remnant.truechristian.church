"""Recover publication metadata only from the actual successful Pages deployment."""
import base64
import copy
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import warnings
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publication_state as state
from retention import ledger_digest


ARTICLE = '00000000-0000-4000-8000-000000000001'
CATEGORY = '00000000-0000-4000-8000-000000000002'
SITE_SHA, EVENT_SHA = 'a' * 40, 'e' * 40
DEPLOYMENT_ID, STATUS_ID, RUN_ID, JOB_ID, ARTIFACT_ID = 302, 402, 202, 102, 502
OLD_DEPLOYMENT_ID, OLD_RUN_ID, OLD_JOB_ID = 301, 201, 101
NEW_RUN_ID = 203
STATE_COMMIT = 'f' * 40
DEPLOYED_AT = '2026-11-07T08:00:00Z'


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def metadata():
    revisions = {'site': SITE_SHA, 'english': 'b' * 40,
                 'translations': 'c' * 40, 'theme': 'd' * 40}
    ledger = {'schema': 1, 'english_sources': {ARTICLE: revisions['english']},
              'images': {tag: {ARTICLE: {}} for tag in ('en', 'af')}, 'aliases': {}}
    ledger['sha256'] = ledger_digest(ledger)
    deployment = {'schema': 1, 'display_fingerprint': '1' * 64,
                  'revisions': revisions, 'translation_status': 'ready',
                  'article_inventory': {tag: [ARTICLE] for tag in ('en', 'af')},
                  'retention': ledger}
    routes = {'version': 1, 'categories': {}, 'issues': {}, 'articles': {}}
    for tag, category, alias in (('en', 'faith', 'faithful-life'), ('af', 'geloof', 'getroue-lewe')):
        routes['categories'][tag] = {CATEGORY: {'slug': category, 'history': []}}
        routes['articles'][tag] = {ARTICLE: {
            'category_id': CATEGORY, 'category_slug': category,
            'alias': alias, 'history': [f'/{tag}/{category}/previous-title/'], 'fallback': False}}
    records = {}
    for tag in ('en', 'af'):
        record = {'article_id': ARTICLE, 'locale': tag, 'content_hash': digest(tag.encode()),
                  'detector': 'reviewed-fixture/v1', 'markers': []}
        record['record_hash'] = digest(canonical(record))
        key = ':'.join(record[field] for field in ('article_id', 'locale', 'content_hash', 'detector'))
        records[key] = record
    scripture = {'schema_version': 1, 'integrity': digest(canonical(records)), 'records': records}
    return {'deployment.json': encoded(deployment), 'routes.json': encoded(routes),
            'scripture/manifest.json': encoded(scripture)}


def deployment_record(identity, event_sha=EVENT_SHA):
    return {'id': identity, 'ref': 'main', 'sha': event_sha,
            'task': 'deploy', 'environment': 'github-pages', 'production_environment': False}


def status_record(identity, run_id, job_id, status='success'):
    return {'id': identity, 'state': status, 'environment': 'github-pages',
            'environment_url': 'https://remnant.truechristian.church/',
            'log_url': f'https://github.com/{state.REPOSITORY}/actions/runs/{run_id}/job/{job_id}',
            'created_at': DEPLOYED_AT}


def run_record(identity):
    repository = {'id': state.REPOSITORY_ID, 'full_name': state.REPOSITORY}
    return {'id': identity, 'repository': repository, 'head_repository': dict(repository),
            'workflow_id': state.WORKFLOW_ID, 'path': state.WORKFLOW_PATH,
            'head_branch': 'main', 'head_sha': EVENT_SHA, 'event': 'schedule',
            'run_attempt': 1, 'status': 'in_progress', 'conclusion': None}


def job_record(identity, run_id):
    return {'id': identity, 'run_id': run_id, 'run_attempt': 1, 'name': 'deploy',
            'status': 'completed', 'conclusion': 'success', 'head_sha': EVENT_SHA,
            'steps': [{'name': 'Deploy the validated artifact', 'number': 2,
                       'status': 'completed', 'conclusion': 'success'}]}


def authority():
    return {'repository': state.REPOSITORY, 'repository_id': state.REPOSITORY_ID,
            'workflow_id': state.WORKFLOW_ID, 'workflow_path': state.WORKFLOW_PATH,
            'branch': 'main', 'deployment_id': DEPLOYMENT_ID,
            'deployment_status_id': STATUS_ID, 'run_id': RUN_ID, 'run_attempt': 1,
            'deploy_job_id': JOB_ID, 'event_sha': EVENT_SHA, 'deployed_at': DEPLOYED_AT}


class FakeGitHub:
    """A fixed repository with a pending build, one active deployment, and older history."""

    def __init__(self):
        self.deployments = [deployment_record(303), deployment_record(DEPLOYMENT_ID),
                            deployment_record(OLD_DEPLOYMENT_ID)]
        self.statuses = {
            303: [status_record(403, NEW_RUN_ID, 103, 'in_progress')],
            DEPLOYMENT_ID: [status_record(STATUS_ID, RUN_ID, JOB_ID)],
            OLD_DEPLOYMENT_ID: [status_record(499, OLD_RUN_ID, OLD_JOB_ID, 'inactive'),
                                status_record(401, OLD_RUN_ID, OLD_JOB_ID)],
        }
        self.runs = {identity: run_record(identity) for identity in (OLD_RUN_ID, RUN_ID, NEW_RUN_ID)}
        self.jobs = {JOB_ID: job_record(JOB_ID, RUN_ID), OLD_JOB_ID: job_record(OLD_JOB_ID, OLD_RUN_ID)}
        self.artifacts, self.archives, self.download_errors = {}, {}, {}
        self.calls, self.downloads = [], []
        self.tree, self.blobs = None, {}

    def sleep(self, delay):
        pass

    def api(self, path, *, method='GET', data=None, missing=False):
        self.calls.append((method, path, copy.deepcopy(data)))
        if method != 'GET':
            raise AssertionError(f'Unexpected repository write: {method} {path}')
        parsed = urlsplit(path)
        route = parsed.path.removeprefix(f'/repos/{state.REPOSITORY}')
        query = parse_qs(parsed.query)
        if route == '/deployments':
            value = self.deployments if query.get('page', ['1']) == ['1'] else []
        elif match := re.fullmatch(r'/deployments/(\d+)/statuses', route):
            value = self.statuses[int(match[1])]
        elif match := re.fullmatch(r'/deployments/(\d+)', route):
            value = next(item for item in self.deployments if item['id'] == int(match[1]))
        elif match := re.fullmatch(r'/actions/runs/(\d+)/artifacts', route):
            artifacts = self.artifacts.get(int(match[1]), [])
            value = {'total_count': len(artifacts), 'artifacts': artifacts}
        elif match := re.fullmatch(r'/actions/runs/(\d+)', route):
            value = self.runs[int(match[1])]
        elif match := re.fullmatch(r'/actions/jobs/(\d+)', route):
            value = self.jobs[int(match[1])]
        elif route == '/git/ref/heads/publication-state':
            value = None if self.tree is None else {
                'ref': 'refs/heads/publication-state', 'object': {'type': 'commit', 'sha': STATE_COMMIT}}
        elif route == f'/git/trees/{STATE_COMMIT}':
            value = self.tree
        elif match := re.fullmatch(r'/git/blobs/([a-f0-9]{40})', route):
            value = self.blobs[match[1]]
        else:
            raise AssertionError(f'Unexpected API request: {path}')
        return copy.deepcopy(value)

    @contextmanager
    def download(self, artifact):
        self.downloads.append(artifact['id'])
        if artifact['id'] in self.download_errors:
            raise self.download_errors[artifact['id']]
        yield self.archives[artifact['id']]

    def install_snapshot(self, files, receipt):
        entries = []
        for name, raw in {**files, state.RECEIPT: encoded(receipt)}.items():
            sha = hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest()
            entries.append({'path': name, 'type': 'blob', 'mode': '100644', 'sha': sha, 'size': len(raw)})
            self.blobs[sha] = {'sha': sha, 'size': len(raw), 'encoding': 'base64',
                               'content': base64.b64encode(raw).decode()}
        self.tree = {'sha': STATE_COMMIT, 'truncated': False, 'tree': entries}


class RecordingGitHub(FakeGitHub):
    """In-memory Git objects with non-fast-forward protection, never a remote write."""

    def __init__(self):
        super().__init__()
        self.head = None
        self.git_trees, self.git_commits = {}, {}
        self.conflict_once = False
        self.concurrent_head = None

    def install_snapshot(self, files, receipt):
        super().install_snapshot(files, receipt)
        tree_sha = hashlib.sha1(canonical(self.tree['tree'])).hexdigest()
        self.git_trees[tree_sha] = copy.deepcopy(self.tree)
        self.git_commits[STATE_COMMIT] = {'tree': tree_sha, 'parents': []}
        self.head = STATE_COMMIT

    def api(self, path, *, method='GET', data=None, missing=False):
        route = urlsplit(path).path
        if method == 'GET' and route == '/git/ref/heads/publication-state':
            self.calls.append((method, path, None))
            return None if self.head is None else {
                'ref': 'refs/heads/publication-state', 'object': {'type': 'commit', 'sha': self.head}}
        if method == 'GET' and (match := re.fullmatch(r'/git/trees/([a-f0-9]{40})', route)):
            self.calls.append((method, path, None))
            return copy.deepcopy(self.git_trees[self.git_commits[match[1]]['tree']])
        if method == 'GET':
            return super().api(path, method=method, data=data, missing=missing)
        self.calls.append((method, path, copy.deepcopy(data)))
        if (method, route) == ('POST', '/git/blobs'):
            assert data['encoding'] == 'base64'
            raw = base64.b64decode(data['content'], validate=True)
            sha = hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest()
            self.blobs[sha] = {'sha': sha, 'size': len(raw), **data}
            return {'sha': sha}
        if (method, route) == ('POST', '/git/trees'):
            sha = hashlib.sha1(canonical(data['tree'])).hexdigest()
            self.git_trees[sha] = {'sha': sha, 'truncated': False, 'tree': copy.deepcopy(data['tree'])}
            return {'sha': sha}
        if (method, route) == ('POST', '/git/commits'):
            sha = hashlib.sha1(canonical(data)).hexdigest()
            self.git_commits[sha] = copy.deepcopy(data)
            return {'sha': sha}
        if (method, route) == ('POST', '/git/refs'):
            assert self.head is None and data['ref'] == 'refs/heads/publication-state'
            self.head = data['sha']
            return {'object': {'sha': self.head}}
        if (method, route) == ('PATCH', '/git/refs/heads/publication-state'):
            assert data.get('force') is False, 'Publication history must never be force-pushed'
            if self.conflict_once:
                self.conflict_once = False
                self.concurrent_head = hashlib.sha1(b'concurrent state branch advance').hexdigest()
                self.git_commits[self.concurrent_head] = {
                    'tree': self.git_commits[self.head]['tree'], 'parents': [self.head]}
                self.head = self.concurrent_head
                raise state.GitHubError(422, path)
            if self.git_commits[data['sha']]['parents'] != [self.head]:
                raise state.GitHubError(422, path)
            self.head = data['sha']
            return {'object': {'sha': self.head}}
        raise AssertionError(f'Unexpected repository write: {method} {path}')


class PublicationStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.files = metadata()
        self.client = FakeGitHub()
        archive = self.archive('current.zip')
        self.artifact = self.add_artifact(ARTIFACT_ID, RUN_ID, archive)

    def archive(self, name, *, files=None, pages=False, duplicate=False):
        files = self.files if files is None else files
        path = self.root / name
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            if pages:
                buffer = io.BytesIO()
                with tarfile.open(fileobj=buffer, mode='w') as tar:
                    for member, raw in {**files, 'en/index.html': b'<h1>Published article</h1>'}.items():
                        info = tarfile.TarInfo('./' + member)
                        info.size = len(raw)
                        tar.addfile(info, io.BytesIO(raw))
                    if duplicate:
                        info = tarfile.TarInfo('./deployment.json')
                        info.size = len(files['deployment.json'])
                        tar.addfile(info, io.BytesIO(files['deployment.json']))
                archive.writestr('artifact.tar', buffer.getvalue())
            else:
                for member, raw in files.items():
                    archive.writestr(member, raw)
                if duplicate:
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', UserWarning)
                        archive.writestr('deployment.json', files['deployment.json'])
        return path

    def add_artifact(self, identity, run_id, archive, *, name=None):
        artifact = {'id': identity, 'name': name or f'remnant-publication-metadata-{run_id}-1',
                    'expired': False, 'size_in_bytes': archive.stat().st_size,
                    'created_at': '2026-11-07T07:59:00Z',
                    'digest': 'sha256:' + digest(archive.read_bytes()),
                    'archive_download_url': f'https://api.github.com/repos/{state.REPOSITORY}/actions/artifacts/{identity}/zip',
                    'workflow_run': {'id': run_id, 'repository_id': state.REPOSITORY_ID,
                                     'head_repository_id': state.REPOSITORY_ID,
                                     'head_branch': 'main', 'head_sha': EVENT_SHA}}
        self.client.artifacts.setdefault(run_id, []).append(artifact)
        self.client.archives[identity] = archive
        return artifact

    def test_only_current_successful_pages_deployment_authorizes_state(self):
        # A recording job may still be running, or may have failed after Pages succeeded.
        for status, conclusion in (('in_progress', None), ('completed', 'failure')):
            with self.subTest(status=status, conclusion=conclusion):
                self.client.runs[RUN_ID].update(status=status, conclusion=conclusion)
                self.assertEqual(state.current_deployment(self.client), authority())
        # An old success followed by an inactive status is no longer publication authority.
        with self.assertRaises(ValueError):
            state.current_deployment(self.client, deployment_id=OLD_DEPLOYMENT_ID)
        with self.assertRaises(ValueError):
            state.record_publication(self.client, NEW_RUN_ID)
        self.assertTrue(all(method == 'GET' for method, _, _ in self.client.calls))

    def test_untrusted_repository_branch_workflow_and_failed_deploy_are_rejected(self):
        cases = (
            ('repository', lambda c: c.runs[RUN_ID]['repository'].update(full_name='elsewhere/site')),
            ('head repository', lambda c: c.runs[RUN_ID]['head_repository'].update(id=state.REPOSITORY_ID + 1)),
            ('branch', lambda c: c.deployments[1].update(ref='feature')),
            ('workflow path', lambda c: c.runs[RUN_ID].update(path='.github/workflows/review.yml')),
            ('workflow ID', lambda c: c.runs[RUN_ID].update(workflow_id=state.WORKFLOW_ID + 1)),
            ('pull request', lambda c: c.runs[RUN_ID].update(event='pull_request')),
            ('failed deploy job', lambda c: c.jobs[JOB_ID].update(conclusion='failure')),
            ('failed deploy step', lambda c: c.jobs[JOB_ID]['steps'][0].update(conclusion='failure')),
            ('foreign status link', lambda c: c.statuses[DEPLOYMENT_ID][0].update(
                log_url=f'https://github.com/elsewhere/site/actions/runs/{RUN_ID}/job/{JOB_ID}')),
        )
        for label, alter in cases:
            client = copy.deepcopy(self.client)
            alter(client)
            with self.subTest(case=label), self.assertRaises(ValueError):
                state.current_deployment(client)

    def test_restores_exact_three_files_without_public_site_and_allows_selected_main_to_advance(self):
        output = self.root / 'restored'
        with patch('urllib.request.urlopen', side_effect=AssertionError('Public HTTP is unavailable')), \
             patch('urllib.request.build_opener', side_effect=AssertionError('Public HTTP is unavailable')):
            receipt = state.fetch_publication(self.client, output)
        self.assertEqual(set(state.FILES), set(self.files))
        for name, raw in self.files.items():
            self.assertEqual((output / name).read_bytes(), raw)
        self.assertEqual(receipt['deployment_id'], DEPLOYMENT_ID)
        self.assertEqual(receipt['run_id'], RUN_ID)
        self.assertEqual(receipt['source_revisions']['site'], SITE_SHA)
        self.assertEqual(receipt['event_sha'], EVENT_SHA)
        self.assertNotEqual(SITE_SHA, EVENT_SHA)
        self.assertEqual(self.client.downloads, [ARTIFACT_ID])
        self.assertEqual(state.validate_metadata(self.files)['article_inventory'], {'en': [ARTICLE], 'af': [ARTICLE]})

    def test_matching_pinned_branch_receipt_preserves_bytes_without_artifact_download(self):
        receipt = state.make_receipt(self.files, authority(), self.artifact)
        self.client.install_snapshot(self.files, receipt)
        output = self.root / 'from-branch'
        restored = state.fetch_publication(self.client, output)
        self.assertEqual(restored, receipt)
        self.assertEqual(self.client.downloads, [])
        self.assertTrue(any(f'/git/trees/{STATE_COMMIT}' in path for _, path, _ in self.client.calls))
        for name, raw in self.files.items():
            self.assertEqual((output / name).read_bytes(), raw)

    def test_recorded_publication_survives_artifact_expiry_and_repeated_recording_is_read_only(self):
        client = RecordingGitHub()
        client.artifacts = copy.deepcopy(self.client.artifacts)
        client.archives = dict(self.client.archives)
        receipt = state.record_publication(client, RUN_ID)
        self.assertEqual(receipt['deployment_id'], DEPLOYMENT_ID)
        self.assertEqual(client.git_commits[client.head]['parents'], [])
        tree = client.git_trees[client.git_commits[client.head]['tree']]
        self.assertEqual({entry['path'] for entry in tree['tree']}, {*state.FILES, state.RECEIPT})
        self.assertEqual(client.downloads, [ARTIFACT_ID])

        # GitHub artifact expiry must not erase the publication baseline.
        client.artifacts.clear()
        client.archives.clear()
        client.calls.clear()
        client.downloads.clear()
        self.assertEqual(state.record_publication(client, RUN_ID), receipt)
        output = self.root / 'durable'
        self.assertEqual(state.fetch_publication(client, output), receipt)
        self.assertTrue(all(method == 'GET' for method, _, _ in client.calls))
        self.assertEqual(client.downloads, [])
        for name, raw in self.files.items():
            self.assertEqual((output / name).read_bytes(), raw)

    def test_recording_rereads_a_conflicting_branch_and_preserves_its_new_parent(self):
        client = RecordingGitHub()
        client.artifacts = copy.deepcopy(self.client.artifacts)
        client.archives = dict(self.client.archives)
        previous = {**authority(), 'deployment_id': OLD_DEPLOYMENT_ID,
                    'run_id': OLD_RUN_ID, 'deploy_job_id': OLD_JOB_ID, 'deployment_status_id': 401}
        artifact = {**self.artifact, 'id': 501, 'name': f'remnant-publication-metadata-{OLD_RUN_ID}-1'}
        client.install_snapshot(self.files, state.make_receipt(self.files, previous, artifact))
        client.conflict_once = True
        receipt = state.record_publication(client, RUN_ID)
        self.assertEqual(receipt['deployment_id'], DEPLOYMENT_ID)
        self.assertIsNotNone(client.concurrent_head)
        self.assertEqual(client.git_commits[client.head]['parents'], [client.concurrent_head])
        updates = [data for method, path, data in client.calls
                   if method == 'PATCH' and path == '/git/refs/heads/publication-state']
        self.assertEqual(len(updates), 2)
        self.assertTrue(all(update['force'] is False for update in updates))

    def test_stale_receipt_recovers_current_artifact_but_current_corruption_fails_closed(self):
        previous = {**authority(), 'deployment_id': OLD_DEPLOYMENT_ID,
                    'run_id': OLD_RUN_ID, 'deploy_job_id': OLD_JOB_ID, 'deployment_status_id': 401}
        old_artifact = self.add_artifact(501, OLD_RUN_ID, self.archive('previous.zip'))
        stale = state.make_receipt(self.files, previous, old_artifact)
        self.client.install_snapshot(self.files, stale)
        result = state.fetch_publication(self.client, self.root / 'recovered')
        self.assertEqual(result['deployment_id'], DEPLOYMENT_ID)
        self.assertEqual(self.client.downloads, [ARTIFACT_ID])

        receipt = state.make_receipt(self.files, authority(), self.artifact)
        changed = {**self.files, 'routes.json': self.files['routes.json'] + b' '}
        self.client.install_snapshot(changed, receipt)
        self.client.downloads.clear()
        output = self.root / 'corrupt'
        with self.assertRaises(ValueError):
            state.fetch_publication(self.client, output)
        self.assertFalse(output.exists())
        self.assertEqual(self.client.downloads, [])

    def test_receipt_cannot_pair_another_publication_or_changed_file_with_current_authority(self):
        receipt = state.make_receipt(self.files, authority(), self.artifact)
        state.validate_snapshot(self.files, receipt, authority())
        for field, value in (('deployment_id', OLD_DEPLOYMENT_ID), ('run_id', OLD_RUN_ID),
                             ('repository', 'elsewhere/site'), ('event_sha', '9' * 40)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                state.validate_snapshot(self.files, {**receipt, field: value}, authority())
        with self.assertRaises(ValueError):
            state.validate_snapshot({**self.files, 'routes.json': self.files['routes.json'] + b' '},
                                    receipt, authority())

    def test_missing_or_corrupt_current_artifact_never_falls_back_to_older_publication(self):
        self.add_artifact(501, OLD_RUN_ID, self.archive('old.zip'))
        self.client.artifacts[RUN_ID] = []
        with self.assertRaises(ValueError):
            state.fetch_publication(self.client, self.root / 'missing')
        self.assertEqual(self.client.downloads, [])

        self.client.artifacts[RUN_ID] = [self.artifact]
        self.add_artifact(503, RUN_ID, self.archive('legacy.zip', pages=True), name='github-pages')
        self.client.download_errors[ARTIFACT_ID] = ValueError('Artifact digest mismatch')
        with self.assertRaisesRegex(ValueError, 'digest'):
            state.fetch_publication(self.client, self.root / 'bad-digest')
        self.assertEqual(self.client.downloads, [ARTIFACT_ID])

    def test_archive_digest_is_verified_before_contents_are_available(self):
        client = state.GitHub(token='fixture-token', sleep=lambda _: None)
        raw = self.client.archives[ARTIFACT_ID].read_bytes()

        def download(artifact, destination):
            Path(destination).write_bytes(raw)

        with patch.object(client, '_download_archive', side_effect=download):
            with client.download(self.artifact) as path:
                self.assertEqual(Path(path).read_bytes(), raw)
            with self.assertRaisesRegex(ValueError, 'digest'):
                with client.download({**self.artifact, 'digest': 'sha256:' + '0' * 64}):
                    self.fail('Corrupt archive was exposed to its consumer')

    def test_legacy_pages_archive_preserves_metadata_and_rejects_ambiguous_or_incomplete_bundles(self):
        pages = self.archive('pages.zip', pages=True)
        self.assertEqual(state.extract_archive(pages, pages=True), self.files)
        for pages in (False, True):
            path = self.archive(f'duplicate-{pages}.zip', pages=pages, duplicate=True)
            with self.subTest(archive='pages' if pages else 'metadata'), self.assertRaises(ValueError):
                state.extract_archive(path, pages=pages)
        incomplete = self.archive('incomplete.zip', files={k: v for k, v in self.files.items() if k != 'routes.json'})
        with self.assertRaises(ValueError):
            state.extract_archive(incomplete)
        unexpected = self.archive('unexpected.zip', files={**self.files, '../receipt.json': b'{}'})
        with self.assertRaises(ValueError):
            state.extract_archive(unexpected)

    def test_semantically_invalid_inventory_routes_or_scripture_ledger_cannot_be_restored(self):
        cases = []
        deployment = json.loads(self.files['deployment.json'])
        deployment['article_inventory']['en'] = []
        cases.append(('deployment.json', deployment))
        routes = json.loads(self.files['routes.json'])
        routes['articles']['en'][ARTICLE]['history'] = ['https://elsewhere.example/']
        cases.append(('routes.json', routes))
        scripture = json.loads(self.files['scripture/manifest.json'])
        scripture['integrity'] = '0' * 64
        cases.append(('scripture/manifest.json', scripture))
        for name, value in cases:
            with self.subTest(file=name), self.assertRaises(ValueError):
                state.validate_metadata({**self.files, name: encoded(value)})


if __name__ == '__main__':
    unittest.main()
