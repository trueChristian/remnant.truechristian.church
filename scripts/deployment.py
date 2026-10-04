#!/usr/bin/env python3
"""Website-owned deployment metadata and last-successful-publication comparison.

The candidate deployment.json is packaged with the site, never saved as a cache
or source marker. Only a successful Pages deployment makes it live and eligible
as the baseline for the next poll. Failed builds/deployments cannot advance it.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
import uuid

from validate_event import FINGERPRINT, SHA
from publication_inventory import candidate_inventory, baseline_inventory, assert_retains

PRODUCTION_MANIFEST = 'https://remnant.truechristian.church/deployment.json'
DEPLOYMENT_REPORTS = {'deployment.json', 'build-report.json'}
MAX_DEPLOYMENT_BYTES = 32 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirects are not permitted for deployment metadata')


def request_bytes(request: urllib.request.Request, *, limit: int = MAX_DEPLOYMENT_BYTES) -> tuple[int, bytes]:
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        content = response.read(limit + 1)
        if len(content) > limit:
            raise ValueError('Response exceeds bounded metadata size')
        return response.status, content


def display_fingerprint(directory: Path) -> str:
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError('Display output must be an existing directory')
    digest = hashlib.sha256()
    included = 0
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('Display output must not contain symlinks')
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        if relative in DEPLOYMENT_REPORTS:
            continue
        raw = path.read_bytes()
        name = relative.encode('utf-8')
        # Length-prefixing prevents filename/content boundary ambiguities.
        digest.update(len(name).to_bytes(8, 'big'))
        digest.update(name)
        digest.update(len(raw).to_bytes(8, 'big'))
        digest.update(raw)
        included += 1
    if not included:
        raise ValueError('Refusing to fingerprint an empty display tree')
    return digest.hexdigest()


def live_deployment(request=request_bytes, *, fresh: bool = False) -> dict | None:
    try:
        url = PRODUCTION_MANIFEST + ('?publication-check=' + uuid.uuid4().hex if fresh else '')
        status, raw = request(urllib.request.Request(url, headers={
            'User-Agent': 'remnant-build/1', 'Cache-Control': 'no-cache, no-store, max-age=0', 'Accept': 'application/json'}))
        data = json.loads(raw)
        value = data.get('display_fingerprint') if isinstance(data, dict) else None
        if status == 200 and isinstance(data, dict) and data.get('schema') == 1 and isinstance(value, str) and FINGERPRINT.fullmatch(value):
            return data
    except (OSError, ValueError, urllib.error.URLError, TimeoutError, http.client.HTTPException):
        pass
    # Missing metadata, CDN uncertainty, or first deploy must never suppress work.
    return None


def validated_source_revisions(source_report: dict) -> dict:
    revisions = {'site': source_report['site_revision']}
    revisions.update({key: value['revision'] for key, value in source_report['sources'].items()})
    if set(revisions) != {'site', 'english', 'translations', 'theme'} or any(
            not isinstance(value, str) or not SHA.fullmatch(value)
            for value in revisions.values()):
        raise ValueError('A complete fixed-revision report is required')
    exported = source_report.get('export')
    english_status = exported.get('english_status') if isinstance(exported, dict) else None
    if english_status != 'ready':
        raise ValueError(f'Refusing publication: English export is {english_status or "unknown"}; '
                         'retain the last successful site until English validates')
    status = exported.get('translation_status') if isinstance(exported, dict) else None
    if status != 'ready':
        raise ValueError(f'Refusing publication: translation export is {status or "unknown"}; '
                         'retain the last successful site until translations validate')
    return revisions


def validated_revisions(source_report: dict, build_report: dict) -> dict:
    revisions = validated_source_revisions(source_report)
    built = build_report.get('source') if isinstance(build_report, dict) else None
    status = built.get('translation_status') if isinstance(built, dict) else None
    if status != 'ready':
        raise ValueError(f'Refusing publication: translation built content is {status or "unknown"}; '
                         'retain the last successful site until translations validate')
    built_revisions = {'site': build_report.get('site_revision'),
                       'english': built.get('source_revision'),
                       'translations': built.get('translation_revision'),
                       'theme': build_report.get('theme_revision')}
    if built_revisions != revisions:
        raise ValueError('Refusing publication: build report revisions do not match the selected sources')
    return revisions


def deployment_plan(output: Path, source_report: dict, build_report: dict, *, previous: dict | None = None,
                    migration_snapshot: dict | None = None, force: bool = False) -> dict:
    revisions = validated_revisions(source_report, build_report)
    inventory = candidate_inventory(output, build_report.get('article_counts'))
    published = baseline_inventory(previous, migration_snapshot)
    assert_retains(published, inventory)
    retained = None
    if 'retention' in previous or 'retention' in build_report:
        from retention import validate_ledger, validate_published_assets
        if 'retention' in previous:
            validate_ledger(previous['retention'], published)
        if 'retention' not in build_report:
            raise ValueError('Refusing publication: published retention provenance is missing from the candidate')
        retained = validate_ledger(build_report['retention'], inventory)
        validate_published_assets(output, retained)
    # Check health before fingerprinting or emitting a candidate/changed output.
    # Manual --force bypasses deduplication only, never failed validation.
    fingerprint = display_fingerprint(output)
    translation_status = 'ready'
    manifest = {'schema': 1, 'display_fingerprint': fingerprint, 'revisions': revisions,
                'translation_status': translation_status, 'article_inventory': inventory}
    if retained is not None:
        manifest['retention'] = retained
    encoded = json.dumps(manifest, ensure_ascii=False, separators=(',', ':')) + '\n'
    if len(encoded.encode('utf-8')) > MAX_DEPLOYMENT_BYTES:
        raise ValueError('Refusing publication: deployment metadata exceeds its readable size limit')
    (output / 'deployment.json').write_text(encoded, encoding='utf-8')
    unchanged = (isinstance(previous, dict) and previous.get('schema') == 1
                 and previous.get('display_fingerprint') == fingerprint
                 and previous.get('revisions') == revisions
                 and previous.get('retention') == retained
                 and previous.get('translation_status') == translation_status)
    return {'changed': force or not unchanged,
            'previous_fingerprint': previous.get('display_fingerprint') if previous else None,
            'reason': 'manual-recovery' if force else ('unchanged-display' if unchanged else 'display-changed'),
            **manifest}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-output', type=Path, default=Path('dist'))
    parser.add_argument('--source-report', type=Path, default=Path('.build/source-report.json'))
    parser.add_argument('--build-report', type=Path, default=Path('.build/site-build-report.json'))
    parser.add_argument('--migration-baseline', type=Path, default=Path(__file__).resolve().parents[1] / 'data/publication-baseline.json')
    parser.add_argument('--report', type=Path, default=Path('.build/deployment-plan.json'))
    parser.add_argument('--compare-live', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    sources = json.loads(args.source_report.read_text())
    built = json.loads(args.build_report.read_text())
    validated_revisions(sources, built)
    # A verified live inventory is mandatory, including review and manual runs.
    # --compare-live remains a compatibility option; it never disables retention.
    previous = live_deployment(fresh=True)
    migration = None
    if isinstance(previous, dict) and 'article_inventory' not in previous:
        migration = json.loads(args.migration_baseline.read_text())
    result = deployment_plan(args.site_output, sources, built,
                             previous=previous, migration_snapshot=migration,
                             force=args.force)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({**{key: value for key, value in result.items() if key not in {'article_inventory', 'retention'}},
                      'article_counts': {tag: len(ids) for tag, ids in result['article_inventory'].items()}}, indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('changed=' + str(result['changed']).lower() + '\n')


if __name__ == '__main__':
    main()
