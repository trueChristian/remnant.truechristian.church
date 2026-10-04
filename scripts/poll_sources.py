#!/usr/bin/env python3
"""Lightweight website-owned poll against the last successfully deployed pins."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from deployment import live_deployment
from prepare_sources import REPOSITORIES, SHA, THEME_REVISION, git, resolve_main

REVISION_KEYS = {'site', 'english', 'translations', 'theme'}


def validate_selection(selection: object, *, site_revision: str | None = None) -> dict:
    if not isinstance(selection, dict) or set(selection) != REVISION_KEYS:
        raise ValueError('A complete fixed-revision selection is required')
    for name, revision in selection.items():
        if name == 'translations' and revision is None:
            continue
        if not isinstance(revision, str) or not SHA.fullmatch(revision):
            raise ValueError('Each selected revision must be a lowercase full commit SHA')
    if selection['theme'] != THEME_REVISION:
        raise ValueError('Theme must remain pinned to the website-reviewed revision')
    if site_revision is not None and selection['site'] != site_revision:
        raise ValueError('Build checkout must match the polled website revision')
    return dict(selection)


def select_revisions() -> dict:
    # No source checkout, package install, build, token, or state mutation.
    selection = {'site': git('rev-parse', 'HEAD'), 'theme': THEME_REVISION}
    for name in ('english', 'translations'):
        try:
            selection[name] = resolve_main(REPOSITORIES[name])
        except (OSError, ValueError, subprocess.SubprocessError):
            if name != 'translations':
                raise
            # Missing translation acquisition must request a retry. Publication
            # remains blocked until its complete inventory can be validated.
            selection[name] = None
    return validate_selection(selection)


def poll_plan(selection: dict, previous: dict | None, *, force: bool = False,
              review: bool = False) -> dict:
    selection = validate_selection(selection)
    if review:
        reason = 'pull-request-validation'
    elif force:
        reason = 'manual-recovery'
    elif not isinstance(previous, dict) or previous.get('schema') != 1:
        reason = 'no-verified-live-deployment'
    elif previous.get('revisions') != selection:
        reason = 'revision-changed'
    elif selection['translations'] is None or previous.get('translation_status') != 'ready':
        reason = 'retry-translation-acquisition-or-export'
    else:
        reason = 'unchanged-deployed-revisions'
    return {'schema': 1, 'build': reason != 'unchanged-deployed-revisions',
            'reason': reason, 'selection': selection,
            'deployed_revisions': previous.get('revisions') if isinstance(previous, dict) else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=Path('.build/poll-report.json'))
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--review', action='store_true')
    args = parser.parse_args()
    selection = select_revisions()
    result = poll_plan(selection, None if args.review or args.force else live_deployment(),
                       force=args.force, review=args.review)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('build=' + str(result['build']).lower() + '\n')
            stream.write('site_revision=' + selection['site'] + '\n')
            stream.write('selection=' + json.dumps(selection, separators=(',', ':')) + '\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write('## Source revision check\n\n')
            stream.write(result['reason'] + '\n\n')
            stream.write('Build requested.\n' if result['build'] else
                         'No source or website revisions changed; build and deployment skipped.\n')
            stream.write('The baseline is the live deployment.json, never the last seen or attempted revision.\n')


if __name__ == '__main__':
    main()
