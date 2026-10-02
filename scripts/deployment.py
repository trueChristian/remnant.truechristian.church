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

from validate_event import FINGERPRINT, SHA

PRODUCTION_MANIFEST = 'https://remnant.truechristian.church/deployment.json'
DEPLOYMENT_REPORTS = {'deployment.json', 'build-report.json'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirects are not permitted for deployment metadata')


def request_bytes(request: urllib.request.Request, *, limit: int = 65536) -> tuple[int, bytes]:
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


def live_deployment(request=request_bytes) -> dict | None:
    try:
        status, raw = request(urllib.request.Request(PRODUCTION_MANIFEST, headers={
            'User-Agent': 'remnant-build/1', 'Cache-Control': 'no-cache', 'Accept': 'application/json'}))
        data = json.loads(raw)
        value = data.get('display_fingerprint') if isinstance(data, dict) else None
        if status == 200 and isinstance(data, dict) and data.get('schema') == 1 and isinstance(value, str) and FINGERPRINT.fullmatch(value):
            return data
    except (OSError, ValueError, urllib.error.URLError, TimeoutError, http.client.HTTPException):
        pass
    # Missing metadata, CDN uncertainty, or first deploy must never suppress work.
    return None


def deployment_plan(output: Path, source_report: dict, *, previous: dict | None = None,
                    force: bool = False) -> dict:
    fingerprint = display_fingerprint(output)
    revisions = {'site': source_report['site_revision']}
    revisions.update({key: value['revision'] for key, value in source_report['sources'].items()})
    if set(revisions) != {'site', 'english', 'translations', 'theme'} or any(
            not isinstance(value, str) or not SHA.fullmatch(value)
            for key, value in revisions.items() if not (key == 'translations' and value is None
                and source_report['sources'][key].get('acquisition') == 'unavailable')):
        raise ValueError('A complete fixed-revision report is required')
    translation_status = source_report.get('export', {}).get('translation_status', 'unknown')
    manifest = {'schema': 1, 'display_fingerprint': fingerprint, 'revisions': revisions,
                'translation_status': translation_status}
    (output / 'deployment.json').write_text(json.dumps(manifest, indent=2) + '\n')
    unchanged = (isinstance(previous, dict) and previous.get('schema') == 1
                 and previous.get('display_fingerprint') == fingerprint
                 and previous.get('revisions') == revisions
                 and previous.get('translation_status') == translation_status)
    return {'changed': force or not unchanged,
            'previous_fingerprint': previous.get('display_fingerprint') if previous else None,
            'reason': 'manual-recovery' if force else ('unchanged-display' if unchanged else 'display-changed'),
            **manifest}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-output', type=Path, default=Path('dist'))
    parser.add_argument('--source-report', type=Path, default=Path('.build/source-report.json'))
    parser.add_argument('--report', type=Path, default=Path('.build/deployment-plan.json'))
    parser.add_argument('--compare-live', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    result = deployment_plan(args.site_output, json.loads(args.source_report.read_text()),
                             previous=live_deployment() if args.compare_live and not args.force else None,
                             force=args.force)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('changed=' + str(result['changed']).lower() + '\n')


if __name__ == '__main__':
    main()
