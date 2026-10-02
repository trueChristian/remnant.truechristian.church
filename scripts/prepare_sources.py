#!/usr/bin/env python3
"""Prepare isolated, fixed-revision source checkouts and supported display exports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

REPOSITORIES = {
    'english': 'trueChristian/berean-voice',
    'translations': 'trueChristian/berean-translation',
    'theme': 'trueChristian/theme',
}
# Theme changes are reviewed in website PRs, never silently taken from a mutable ref.
THEME_REVISION = '3bd0c28956610506f83e3ecd3af6ea775ac7cb45'
SHA = re.compile(r'[0-9a-f]{40}\Z')


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(['git', *args], cwd=cwd, text=True, stderr=subprocess.PIPE).strip()


def resolve_main(repository: str) -> str:
    if repository not in REPOSITORIES.values():
        raise ValueError('Source repository is not allowlisted')
    result = git('ls-remote', '--exit-code', f'https://github.com/{repository}.git', 'refs/heads/main')
    rows = result.splitlines()
    if len(rows) != 1 or len(rows[0].split()) != 2:
        raise ValueError('Main did not resolve to exactly one revision')
    revision, ref = rows[0].split()
    if not SHA.fullmatch(revision) or ref != 'refs/heads/main':
        raise ValueError('Invalid trusted main resolution')
    return revision


def checkout_fixed(repository: str, revision: str, destination: Path, local: Path | None = None) -> None:
    if repository not in REPOSITORIES.values() or not SHA.fullmatch(revision):
        raise ValueError('Invalid immutable source selection')
    if destination.exists():
        raise ValueError(f'Checkout destination must not exist: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    git('init', '--quiet', str(destination))
    remote = str(local.resolve()) if local else f'https://github.com/{repository}.git'
    git('remote', 'add', 'origin', remote, cwd=destination)
    git('-c', 'protocol.file.allow=always', 'fetch', '--quiet', '--depth=1', 'origin', revision, cwd=destination)
    git('checkout', '--quiet', '--detach', revision, cwd=destination)
    if git('rev-parse', 'HEAD', cwd=destination) != revision or git('status', '--porcelain', cwd=destination):
        raise ValueError('Source checkout failed fixed-revision/cleanliness checks')


def snapshot_languages(checkout: Path, destination: Path) -> None:
    """Keep the selected private language registry even if article export fails."""
    source = checkout / 'config/languages.json'
    if destination.exists() or destination.is_symlink():
        raise ValueError('Language registry destination must not exist; stale input is never reused')
    if (source.is_symlink() or not source.is_file()
            or not source.resolve().is_relative_to(checkout.resolve())):
        raise ValueError('Selected translation checkout lacks a regular language registry')
    if source.stat().st_size > 1_000_000:
        raise ValueError('Language registry exceeds bounded input size')
    raw = source.read_bytes()
    if not isinstance(json.loads(raw), dict):
        raise ValueError('Language registry must be a JSON object')
    # Private build input only. The content adapter exposes an allowlisted view.
    destination.write_bytes(raw)


def prepare(root: Path, local_sources: dict[str, Path] | None = None,
            selection: dict | None = None) -> dict:
    from export_sources import export_sources

    local_sources = local_sources or {}
    site_revision = git('rev-parse', 'HEAD')
    if selection is not None:
        from poll_sources import validate_selection
        selection = validate_selection(selection, site_revision=site_revision)
        if local_sources:
            raise ValueError('Polled revisions cannot be combined with local source overrides')
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'languages.json').exists() or (root / 'languages.json').is_symlink():
        raise ValueError('Build root already contains a language registry; use a fresh build root')
    selected = {}
    for name, repository in REPOSITORIES.items():
        local = local_sources.get(name)
        try:
            revision = selection[name] if selection is not None else (
                THEME_REVISION if name == 'theme' else (
                    git('rev-parse', 'HEAD', cwd=local) if local else resolve_main(repository)))
            if not isinstance(revision, str) or not SHA.fullmatch(revision):
                raise ValueError('Invalid source revision')
            selected[name] = {'repository': repository, 'revision': revision, 'acquisition': 'selected'}
        except (OSError, ValueError, subprocess.SubprocessError):
            if name != 'translations':
                raise
            selected[name] = {'repository': repository, 'revision': None, 'acquisition': 'unavailable'}
    # All revisions are selected before any export; a preflight selection is never re-resolved.
    for name, source in selected.items():
        destination = root / ('theme' if name == 'theme' else f'checkouts/{name}')
        if source['revision'] is None:
            continue
        try:
            checkout_fixed(source['repository'], source['revision'], destination, local_sources.get(name))
            source['acquisition'] = 'ready'
        except (OSError, ValueError, subprocess.SubprocessError):
            if name != 'translations':
                raise
            source['acquisition'] = 'unavailable'
            # Leave the failed clone isolated. Never export partial checkout bytes.
            if destination.exists():
                destination.rename(destination.with_name('translations-incomplete'))
    report = {'schema': 1, 'sources': selected, 'site_revision': site_revision, 'export': None}
    report_path = root / 'source-report.json'
    report['language_registry'] = {'status': 'unavailable', 'revision': None}
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    if selected['translations']['acquisition'] == 'ready':
        snapshot_languages(root / 'checkouts/translations', root / 'languages.json')
        report['language_registry'] = {'status': 'ready', 'path': 'languages.json',
                                       'revision': selected['translations']['revision']}
        report_path.write_text(json.dumps(report, indent=2) + '\n')
    try:
        report['export'] = export_sources(root / 'checkouts/english', root / 'checkouts/translations',
                                           root / 'english', root / 'translations')
    except Exception:
        report['export'] = {'english_status': 'failed', 'translation_status': 'not_attempted'}
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        raise
    if report['export'].get('translation_status') != 'ready':
        failed_output = root / 'translations'
        if failed_output.exists() or failed_output.is_symlink():
            # Do not let the generator accidentally consume a failed/partial export.
            # Keep it outside the public input path as diagnostic evidence only.
            failed_output.rename(root / 'translations-unusable')
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path, default=Path('.build'))
    for name in REPOSITORIES:
        parser.add_argument(f'--{name}-checkout', type=Path)
    parser.add_argument('--selection', help='Validated JSON revision selection from the lightweight poll')
    args = parser.parse_args()
    sources = {name: getattr(args, f'{name}_checkout') for name in REPOSITORIES if getattr(args, f'{name}_checkout')}
    print(json.dumps(prepare(args.build_root, sources,
                             json.loads(args.selection) if args.selection else None), indent=2))


if __name__ == '__main__':
    main()
