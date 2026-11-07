#!/usr/bin/env python3
"""Retrieve and preserve metadata belonging to the actual GitHub Pages deployment.

The public website is not a build API. GitHub's active deployment identifies the
publication; a separate Git branch preserves its exact metadata beyond artifact
expiry. A stale record can only recover from that same deployment's artifacts.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = 'trueChristian/remnant.truechristian.church'
REPOSITORY_ID = 1379934560
WORKFLOW_ID = 371482966
WORKFLOW_PATH = '.github/workflows/pages.yml'
STATE_BRANCH = 'publication-state'
FILES = ('deployment.json', 'routes.json', 'scripture/manifest.json')
RECEIPT = 'receipt.json'
API_ROOT = 'https://api.github.com/repos/' + REPOSITORY
SITE = 'https://remnant.truechristian.church/'
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_API_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_TAR_BYTES = 4 * 1024 * 1024 * 1024
SHA = re.compile(r'[0-9a-f]{40}\Z')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
AUTHORITY_KEYS = ('repository', 'repository_id', 'workflow_id', 'workflow_path',
                  'branch', 'deployment_id', 'deployment_status_id', 'run_id',
                  'run_attempt', 'deploy_job_id', 'event_sha', 'deployed_at')


class PublicationStateError(ValueError):
    """The actual published baseline could not be established safely."""


class GitHubError(PublicationStateError):
    def __init__(self, status, path):
        self.status = status
        super().__init__(f'GitHub request failed: HTTP {status} for {path.split("?")[0]}')


def require(condition, message):
    if not condition:
        raise PublicationStateError(message)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON object key in publication metadata')
        result[key] = value
    return result


def _json(raw):
    def invalid_constant(value):
        raise PublicationStateError('Non-finite JSON number in publication metadata')
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=invalid_constant)


def _encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def _positive(value):
    return type(value) is int and value > 0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class GitHub:
    """Fixed-repository requests; credentials never accompany artifact redirects."""
    def __init__(self, token=None, *, opener=None, sleep=time.sleep):
        self.token = token or os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        require(bool(self.token), 'GH_TOKEN or GITHUB_TOKEN is required for publication metadata')
        self.opener = opener or urllib.request.build_opener(_NoRedirect)
        self.sleep = sleep

    def _request(self, path, *, method='GET', data=None, redirect=False):
        require(path.startswith('/') and not path.startswith('//') and
                '..' not in path.split('/') and not urllib.parse.urlsplit(path).netloc,
                'GitHub request must remain in the fixed repository')
        headers = {'Authorization': 'Bearer ' + self.token,
                   'Accept': 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'remnant-publication/1'}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(API_ROOT + path, method=method, headers=headers,
                                         data=_encoded(data) if data is not None else None)
        for attempt in range(3):
            try:
                return self.opener.open(request, timeout=30)
            except urllib.error.HTTPError as error:
                if redirect and error.code == 302:
                    return error
                retry = error.code in (429, 500, 502, 503, 504) or (
                    error.code == 403 and (error.headers.get('Retry-After') or
                                          error.headers.get('X-RateLimit-Remaining') == '0'))
                error.close()
                if not retry or attempt == 2:
                    raise GitHubError(error.code, path) from None
            except (OSError, http.client.HTTPException) as error:
                if attempt == 2:
                    raise PublicationStateError('GitHub publication request failed after retries') from error
            self.sleep(2 ** attempt)

    def api(self, path, *, method='GET', data=None, missing=False):
        for attempt in range(3):
            try:
                with self._request(path, method=method, data=data) as response:
                    raw = response.read(MAX_API_BYTES + 1)
                break
            except GitHubError as error:
                if missing and error.status == 404:
                    return None
                raise
            except (OSError, http.client.HTTPException) as error:
                if attempt == 2:
                    raise PublicationStateError('GitHub metadata response failed after retries') from error
                self.sleep(2 ** attempt)
        require(len(raw) <= MAX_API_BYTES, 'GitHub metadata response exceeds its size limit')
        return _json(raw)

    def _download_archive(self, artifact, destination):
        with self._request(f'/actions/artifacts/{artifact["id"]}/zip', redirect=True) as response:
            require(response.code == 302, 'Artifact download did not provide its expected redirect')
            url = response.headers.get('Location', '')
        for _ in range(4):
            parsed = urllib.parse.urlsplit(url)
            host = parsed.hostname or ''
            require(parsed.scheme == 'https' and not parsed.username and not parsed.password
                    and parsed.port in (None, 443) and
                    any(host.endswith(suffix) for suffix in ('.blob.core.windows.net',
                                                              '.githubusercontent.com')),
                    'Artifact redirect is outside GitHub artifact storage')
            # Deliberately construct a fresh request with no API Authorization header.
            request = urllib.request.Request(url, headers={'User-Agent': 'remnant-publication/1'})
            try:
                response = self.opener.open(request, timeout=30)
            except urllib.error.HTTPError as error:
                if error.code in (301, 302, 303, 307, 308):
                    url = urllib.parse.urljoin(url, error.headers.get('Location', ''))
                    error.close()
                    continue
                error.close()
                raise GitHubError(error.code, '/actions/artifacts/download') from None
            with response, destination.open('wb') as output:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    require(total <= MAX_ARCHIVE_BYTES, 'Artifact exceeds its download size limit')
                    output.write(chunk)
            require(total == artifact['size_in_bytes'], 'Artifact download size does not match GitHub metadata')
            return
        raise PublicationStateError('Artifact download exceeded its redirect limit')

    @contextmanager
    def download(self, artifact):
        require(_positive(artifact.get('id')) and
                _positive(artifact.get('size_in_bytes')) and artifact['size_in_bytes'] <= MAX_ARCHIVE_BYTES
                and isinstance(artifact.get('digest'), str) and DIGEST.fullmatch(artifact['digest']),
                'Artifact must have a bounded size and a GitHub SHA-256 digest')
        with tempfile.TemporaryDirectory(prefix='remnant-artifact-') as temporary:
            path = Path(temporary) / 'artifact.zip'
            for attempt in range(3):
                try:
                    self._download_archive(artifact, path)
                    break
                except (OSError, http.client.HTTPException):
                    if attempt == 2:
                        raise PublicationStateError('Artifact download failed after retries') from None
                    self.sleep(2 ** attempt)
                except GitHubError as error:
                    if error.status not in (403, 429, 500, 502, 503, 504) or attempt == 2:
                        raise
                    self.sleep(2 ** attempt)
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            require('sha256:' + digest == artifact['digest'], 'Artifact SHA-256 digest mismatch')
            yield path


def current_deployment(client, deployment_id=None):
    """Bind the active Pages deployment to its trusted workflow and deploy job."""
    for page in range(1, 11):
        deployments = client.api(f'/deployments?environment=github-pages&per_page=100&page={page}')
        require(isinstance(deployments, list), 'Invalid GitHub deployment listing')
        for deployment in sorted(deployments, key=lambda item: item.get('id', 0), reverse=True):
            if deployment.get('environment') != 'github-pages':
                continue
            identity = deployment.get('id')
            require(_positive(identity), 'Invalid GitHub deployment identity')
            statuses = client.api(f'/deployments/{identity}/statuses?per_page=100')
            require(isinstance(statuses, list), 'Invalid GitHub deployment status listing')
            if not statuses:
                continue
            status = max(statuses, key=lambda item: (item.get('created_at', ''), item.get('id', 0)))
            if status.get('state') != 'success':
                continue
            require(deployment_id is None or identity == deployment_id,
                    'The active publication changed after preflight; rerun with its new baseline')
            require(deployment.get('ref') == 'main' and deployment.get('task') == 'deploy'
                    and status.get('environment') == 'github-pages' and status.get('environment_url') == SITE,
                    'Active Pages deployment does not identify trusted main and the expected site')
            match = re.fullmatch(r'https://github\.com/' + re.escape(REPOSITORY) +
                                 r'/actions/runs/([1-9][0-9]*)/job/([1-9][0-9]*)', status.get('log_url', ''))
            require(match is not None, 'Active deployment does not identify its exact workflow job')
            run_id, job_id = map(int, match.groups())
            run = client.api(f'/actions/runs/{run_id}')
            job = client.api(f'/actions/jobs/{job_id}')
            require(all(run.get(key, {}).get('id') == REPOSITORY_ID and
                        run.get(key, {}).get('full_name') == REPOSITORY
                        for key in ('repository', 'head_repository')) and run.get('id') == run_id
                    and run.get('workflow_id') == WORKFLOW_ID and run.get('path') == WORKFLOW_PATH
                    and run.get('head_branch') == 'main'
                    and run.get('event') in ('push', 'schedule', 'workflow_dispatch'),
                    'Deployment workflow repository, main branch, or workflow identity is untrusted')
            event_sha = run.get('head_sha')
            require(isinstance(event_sha, str) and SHA.fullmatch(event_sha)
                    and deployment.get('sha') == event_sha and job.get('head_sha') == event_sha,
                    'Deployment and workflow event revisions do not agree')
            require(job.get('id') == job_id and job.get('run_id') == run_id and job.get('name') == 'deploy'
                    and job.get('conclusion') == 'success' and _positive(job.get('run_attempt'))
                    and any(step.get('name') == 'Deploy the validated artifact'
                            and step.get('conclusion') == 'success' for step in job.get('steps', [])),
                    'Pages publication does not have a successful trusted deployment job')
            require(_positive(status.get('id')) and isinstance(status.get('created_at'), str),
                    'Invalid successful deployment status identity')
            return dict(zip(AUTHORITY_KEYS, (REPOSITORY, REPOSITORY_ID, WORKFLOW_ID, WORKFLOW_PATH,
                        'main', identity, status['id'], run_id, job['run_attempt'], job_id,
                        event_sha, status['created_at'])))
        if len(deployments) < 100:
            break
    raise PublicationStateError('No active successful GitHub Pages publication could be verified')


def validate_metadata(files):
    """Reuse existing fail-closed inventory, route, retention and ledger validators."""
    from publication_inventory import baseline_inventory
    from retention import validate_ledger
    from route_registry import decode_registry
    from scripture import load_manifest
    require(set(files) == set(FILES) and all(isinstance(raw, bytes) and 0 < len(raw) <= MAX_FILE_BYTES
                                          for raw in files.values()),
            'Publication metadata must contain the three complete bounded JSON files')
    deployment = _json(files['deployment.json'])
    inventory = baseline_inventory(deployment)
    if 'retention' in deployment:
        validate_ledger(deployment['retention'], inventory)
    decode_registry(files['routes.json'])
    _json(files['scripture/manifest.json'])  # Reject duplicate keys before the existing validator.
    with tempfile.TemporaryDirectory(prefix='remnant-ledger-') as directory:
        path = Path(directory) / 'manifest.json'
        path.write_bytes(files['scripture/manifest.json'])
        load_manifest(path)
    return deployment


def make_receipt(files, authority, artifact):
    deployment = validate_metadata(files)
    require(set(authority) == set(AUTHORITY_KEYS), 'Incomplete publication authority')
    name = f'remnant-publication-metadata-{authority["run_id"]}-{authority["run_attempt"]}'
    require(_positive(artifact.get('id')) and artifact.get('name') in (name, 'github-pages')
            and isinstance(artifact.get('digest'), str) and DIGEST.fullmatch(artifact['digest']),
            'Receipt must identify the verified publication artifact')
    return {'schema': 1, **authority,
            'artifact': {key: artifact[key] for key in ('id', 'name', 'digest')},
            'files': {name: hashlib.sha256(files[name]).hexdigest() for name in FILES},
            'source_revisions': deployment['revisions'],
            'display_fingerprint': deployment['display_fingerprint']}


def validate_snapshot(files, receipt, authority):
    require(isinstance(receipt, dict) and type(receipt.get('schema')) is int and receipt['schema'] == 1,
            'Invalid publication receipt schema')
    require(all(receipt.get(key) == authority[key] for key in AUTHORITY_KEYS),
            'Publication receipt does not match the active successful deployment')
    require(receipt == make_receipt(files, authority, receipt.get('artifact', {})),
            'Publication receipt hashes or source metadata do not match its exact files')


def extract_archive(path, *, pages=False):
    """Read only expected regular files; never extract an archive into the checkout."""
    files = {}
    def collect(name, size, regular, stream):
        require(name not in files and regular and 0 < size <= MAX_FILE_BYTES,
                'Duplicate, nonregular, or oversized publication artifact member')
        raw = stream.read(MAX_FILE_BYTES + 1)
        require(len(raw) == size, 'Publication artifact member size mismatch')
        files[name] = raw
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if pages:
            require(len(members) == 1 and members[0].filename == 'artifact.tar'
                    and 0 < members[0].file_size <= MAX_TAR_BYTES,
                    'Pages artifact must contain one bounded artifact.tar')
            with archive.open(members[0]) as stream, tarfile.open(fileobj=stream, mode='r|') as tar:
                for member in tar:
                    name = posixpath.normpath(member.name)
                    if name in FILES:
                        require(member.name in (name, './' + name) and member.isfile(),
                                'Publication metadata tar member must use its exact regular-file path')
                        with tar.extractfile(member) as source:
                            collect(name, member.size, True, source)
        else:
            require(len(members) == len(FILES), 'Publication metadata artifact contains unexpected members')
            for member in members:
                require(member.filename in FILES, 'Publication metadata artifact contains an unexpected path')
                mode = member.external_attr >> 16
                with archive.open(member) as source:
                    collect(member.filename, member.file_size,
                            not member.is_dir() and (not stat.S_IFMT(mode) or stat.S_ISREG(mode)), source)
    require(set(files) == set(FILES), 'Publication artifact is missing required metadata')
    validate_metadata(files)
    return files


def _blob(client, identity, limit=MAX_FILE_BYTES):
    require(isinstance(identity, str) and SHA.fullmatch(identity), 'Invalid publication Git blob identity')
    blob = client.api('/git/blobs/' + identity)
    require(blob.get('encoding') == 'base64' and type(blob.get('size')) is int
            and 0 < blob['size'] <= limit and isinstance(blob.get('content'), str),
            'Publication Git blob is not a bounded base64 object')
    raw = base64.b64decode(blob['content'].replace('\n', '').replace('\r', ''), validate=True)
    digest = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    require(len(raw) == blob['size'] and digest == identity and blob.get('sha') == identity,
            'Publication Git blob bytes do not match their immutable identity')
    return raw


def _stored_snapshot(client, authority):
    ref = client.api('/git/ref/heads/' + STATE_BRANCH, missing=True)
    if ref is None:
        return None, None, None
    head = ref.get('object', {}).get('sha')
    require(isinstance(head, str) and SHA.fullmatch(head), 'Invalid publication-state commit identity')
    tree = client.api(f'/git/trees/{head}?recursive=1')
    require(tree.get('truncated') is False and isinstance(tree.get('tree'), list),
            'Publication-state tree is incomplete')
    entries = {entry['path']: entry for entry in tree['tree'] if entry.get('type') != 'tree'}
    require(set(entries) == {*FILES, RECEIPT} and all(entry.get('mode') == '100644'
            and entry.get('type') == 'blob' for entry in entries.values()),
            'Publication-state branch must contain only the four expected regular files')
    receipt = _json(_blob(client, entries[RECEIPT]['sha'], 64 * 1024))
    require(isinstance(receipt, dict) and receipt.get('schema') == 1
            and receipt.get('repository') == REPOSITORY, 'Invalid publication-state receipt')
    if any(receipt.get(key) != authority[key] for key in AUTHORITY_KEYS):
        return head, None, None
    files = {name: _blob(client, entries[name]['sha']) for name in FILES}
    validate_snapshot(files, receipt, authority)
    return head, files, receipt


def _artifact_snapshot(client, authority):
    run_id = authority['run_id']
    listing = client.api(f'/actions/runs/{run_id}/artifacts?per_page=100')
    artifacts = listing.get('artifacts', [])
    require(type(listing.get('total_count')) is int and listing['total_count'] == len(artifacts),
            'Publication artifact listing is incomplete')
    preferred = f'remnant-publication-metadata-{run_id}-{authority["run_attempt"]}'
    candidates = [item for item in artifacts if item.get('name') == preferred]
    if not candidates:
        candidates = [item for item in artifacts if item.get('name') == 'github-pages']
    require(len(candidates) == 1, 'No unique artifact remains for the active publication; refusing an older baseline')
    artifact = candidates[0]
    origin = artifact.get('workflow_run', {})
    require(artifact.get('expired') is False and origin.get('id') == run_id
            and origin.get('repository_id') == REPOSITORY_ID and origin.get('head_repository_id') == REPOSITORY_ID
            and origin.get('head_branch') == 'main' and origin.get('head_sha') == authority['event_sha']
            and isinstance(artifact.get('created_at'), str) and artifact['created_at'] <= authority['deployed_at'],
            'Publication artifact is expired or does not belong to the successful deployment')
    with client.download(artifact) as path:
        files = extract_archive(path, pages=artifact['name'] == 'github-pages')
    return files, make_receipt(files, authority, artifact)


def fetch_publication(client, output, deployment_id=None):
    authority = current_deployment(client, deployment_id)
    _, files, receipt = _stored_snapshot(client, authority)
    if files is None:
        files, receipt = _artifact_snapshot(client, authority)
    output = Path(output)
    for name, raw in {**files, RECEIPT: _encoded(receipt)}.items():
        target = output / name
        require(not any(path.is_symlink() for path in (target, *target.parents)),
                'Publication output cannot traverse symlinks')
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
            temporary.write(raw)
            staged = Path(temporary.name)
        try:
            staged.replace(target)
        finally:
            staged.unlink(missing_ok=True)
    return receipt


def record_publication(client, run_id):
    require(_positive(run_id), 'Recording requires a positive trusted workflow run ID')
    for attempt in range(6):
        try:
            authority = current_deployment(client)
        except PublicationStateError as error:
            if isinstance(error, GitHubError) or attempt == 5:
                raise
            client.sleep(2)
            continue
        if authority['run_id'] == run_id:
            break
        if attempt == 5:
            raise PublicationStateError('The requested workflow has not become the active Pages publication')
        client.sleep(2)
    _, existing, receipt = _stored_snapshot(client, authority)
    if existing is not None:
        return receipt
    files, receipt = _artifact_snapshot(client, authority)
    entries = []
    for name, raw in {**files, RECEIPT: _encoded(receipt)}.items():
        blob = client.api('/git/blobs', method='POST', data={
            'encoding': 'base64', 'content': base64.b64encode(raw).decode('ascii')})
        expected = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        require(blob.get('sha') == expected, 'GitHub stored a different publication metadata blob')
        entries.append({'path': name, 'mode': '100644', 'type': 'blob', 'sha': expected})
    tree = client.api('/git/trees', method='POST', data={'tree': entries})
    require(isinstance(tree.get('sha'), str) and SHA.fullmatch(tree['sha']), 'Invalid stored publication tree')
    for attempt in range(3):
        require(current_deployment(client)['deployment_id'] == authority['deployment_id'],
                'Active publication changed before its state could be recorded')
        head, existing, previous = _stored_snapshot(client, authority)
        if existing is not None:
            require(previous == receipt, 'Another writer recorded different metadata for this deployment')
            return previous
        commit = client.api('/git/commits', method='POST', data={
            'message': f'Record successful Pages deployment {authority["deployment_id"]}',
            'tree': tree['sha'], 'parents': [head] if head else []})
        require(isinstance(commit.get('sha'), str) and SHA.fullmatch(commit['sha']), 'Invalid publication commit')
        try:
            if head:
                client.api('/git/refs/heads/' + STATE_BRANCH, method='PATCH',
                           data={'sha': commit['sha'], 'force': False})
            else:
                client.api('/git/refs', method='POST',
                           data={'ref': 'refs/heads/' + STATE_BRANCH, 'sha': commit['sha']})
            return receipt
        except GitHubError as error:
            if error.status not in (409, 422) or attempt == 2:
                raise
            client.sleep(2 ** attempt)
    raise PublicationStateError('Publication-state branch changed repeatedly during recording')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    fetch = commands.add_parser('fetch', help='Read the verified currently deployed publication')
    fetch.add_argument('--output', type=Path, default=Path('.build/published'))
    fetch.add_argument('--deployment-id', type=int, help='Require the same deployment selected by preflight')
    record = commands.add_parser('record', help='Preserve metadata after a successful Pages deployment')
    record.add_argument('--run-id', type=int, required=True)
    args = parser.parse_args()
    client = GitHub()
    receipt = (fetch_publication(client, args.output, args.deployment_id) if args.command == 'fetch'
               else record_publication(client, args.run_id))
    if args.command == 'fetch' and os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            stream.write(f'deployment_id={receipt["deployment_id"]}\n')
    print(json.dumps({key: receipt[key] for key in ('deployment_id', 'run_id', 'run_attempt',
                                                   'display_fingerprint')}, indent=2))


if __name__ == '__main__':
    main()
