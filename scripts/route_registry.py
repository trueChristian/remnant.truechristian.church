#!/usr/bin/env python3
"""Reuse aliases from the last successful publication before generating routes.

The checked-in registry owns editorial changes. The live registry additionally
owns aliases assigned to newly published articles, categories, and issues. It is
published with the site, so a failed candidate cannot become the next baseline.
Network failures must stop preparation rather than accidentally regenerate URLs.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import unicodedata
import urllib.error
import urllib.request
from urllib.parse import unquote
import uuid

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_REGISTRY = 'https://remnant.truechristian.church/routes.json'
MAX_REGISTRY = 32 * 1024 * 1024
KINDS = ('categories', 'issues', 'articles')
LOCALE = re.compile(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\Z')
UUID_IN_SLUG = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)


class RegistryError(ValueError):
    """Unsafe or unavailable durable routing state."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RegistryError('Redirects are not permitted for route registry metadata')


def request_bytes(request: urllib.request.Request) -> tuple[int, bytes]:
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        content = response.read(MAX_REGISTRY + 1)
        if len(content) > MAX_REGISTRY:
            raise RegistryError('Route registry exceeds the bounded response size')
        return response.status, content


def _identity(value: str) -> None:
    try:
        if isinstance(value, str) and str(uuid.UUID(value)) == value:
            return
    except ValueError:
        pass
    raise RegistryError(f'Invalid route identity: {value!r}')


def _slug(value: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 1024 or any(
            unicodedata.category(char)[0] not in 'LNM' and char != '-' for char in value):
        raise RegistryError(f'Unsafe route slug: {value!r}')


def _history(value: str, locale: str) -> None:
    if (not isinstance(value, str) or len(value) > 4096 or not value.startswith(f'/{locale}/')
            or not value.endswith('/') or re.search(r'%(?![0-9a-fA-F]{2})', value)):
        raise RegistryError(f'Unsafe route history: {value!r}')
    try:
        decoded = unquote(value, errors='strict')
    except UnicodeError as error:
        raise RegistryError(f'Unsafe route history: {value!r}') from error
    parts = decoded.strip('/').split('/')
    # History may be an earlier category, issue, article, or UUID compatibility
    # address, but never a foreign URL, encoded separator, or path traversal.
    if (decoded.count('/') != value.count('/') or len(parts) not in (2, 3)
            or parts[0] != locale or value.startswith('//') or any(
                char in decoded for char in '\\?#%') or any(
                    not part or part in ('.', '..') for part in parts)):
        raise RegistryError(f'Unsafe route history: {value!r}')
    for part in parts[1:]:
        _slug(part)


def route_path(kind: str, locale: str, entry: dict) -> str:
    if kind == 'articles':
        return f"/{locale}/{entry['category_slug']}/{entry['alias']}/"
    prefix = 'issues/' if kind == 'issues' else ''
    return f"/{locale}/{prefix}{entry['slug']}/"


def validate_registry(registry: dict) -> dict:
    """Validate the complete registry, including retired route reservations."""
    if (not isinstance(registry, dict) or type(registry.get('version')) is not int
            or registry['version'] != 1 or set(registry) != {'version', *KINDS}):
        raise RegistryError('Unsupported or incomplete route registry schema')
    occupied = {}
    for kind in KINDS:
        locales = registry[kind]
        if not isinstance(locales, dict):
            raise RegistryError(f'Route {kind} must be a locale map')
        for locale, records in locales.items():
            if not isinstance(locale, str) or not LOCALE.fullmatch(locale):
                raise RegistryError(f'Invalid route locale: {locale!r}')
            if not isinstance(records, dict):
                raise RegistryError(f'Route {kind}/{locale} must be an identity map')
            for identity, entry in records.items():
                _identity(identity)
                if not isinstance(entry, dict):
                    raise RegistryError('Route records must be objects')
                if kind == 'articles':
                    _identity(entry.get('category_id'))
                    _slug(entry.get('category_slug'))
                    _slug(entry.get('alias'))
                    for flag in ('fallback', 'placeholder'):
                        if flag in entry and type(entry[flag]) is not bool:
                            raise RegistryError(f'Article {flag} must be a boolean')
                else:
                    _slug(entry.get('slug'))
                history = entry.get('history', [])
                if not isinstance(history, list) or len(history) > 10000:
                    raise RegistryError('Route history must be a bounded list')
                for old in history:
                    _history(old, locale)
                owner = (kind, locale, identity)
                for path in [route_path(kind, locale, entry), *history]:
                    key = unicodedata.normalize('NFC', unquote(path)).casefold()
                    if key in occupied and occupied[key] != owner:
                        raise RegistryError(f'Route collision in durable registry: {path}')
                    occupied[key] = owner
    return registry


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RegistryError(f'Duplicate route registry key: {key!r}')
        result[key] = value
    return result


def decode_registry(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or len(raw) > MAX_REGISTRY:
        raise RegistryError('Route registry exceeds the bounded response size')
    try:
        value = json.loads(raw, object_pairs_hook=_no_duplicate_keys)
    except (ValueError, UnicodeError) as error:
        raise RegistryError('Invalid route registry JSON') from error
    return validate_registry(value)


def read_registry(path: Path) -> dict:
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_REGISTRY:
        raise RegistryError('Route registry must be a bounded regular file')
    return decode_registry(path.read_bytes())


def live_registry(request=request_bytes) -> dict | None:
    """Only a missing first publication permits a committed-only baseline."""
    try:
        status, raw = request(urllib.request.Request(PRODUCTION_REGISTRY, headers={
            'User-Agent': 'remnant-build/1', 'Cache-Control': 'no-cache',
            'Accept': 'application/json'}))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise RegistryError(f'Published route registry request failed: HTTP {error.code}') from error
    except OSError as error:
        raise RegistryError('Cannot retrieve the published route registry; existing aliases must be preserved') from error
    if status == 404:
        return None
    if status != 200:
        raise RegistryError(f'Published route registry request failed: HTTP {status}')
    return decode_registry(raw)


def _legacy_entry(kind: str, entry: dict) -> bool:
    fields = ('category_slug', 'alias') if kind == 'articles' else ('slug',)
    return bool(entry.get('fallback')) or any(UUID_IN_SLUG.search(entry[field]) for field in fields)


def merge_registries(committed: dict, published: dict | None) -> dict:
    """Freeze published additions, apply editorial changes, and retain history.

    Published migrations take precedence over stale committed UUID fallbacks or
    missing-translation placeholders. Otherwise the committed record owns
    editorial changes. Removed records remain reserved so a temporarily
    unpublished URL cannot be reassigned.
    """
    validate_registry(committed)
    if published is None:
        return copy.deepcopy(committed)
    validate_registry(published)
    merged = copy.deepcopy(published)
    for kind in KINDS:
        for locale, records in committed[kind].items():
            target = merged[kind].setdefault(locale, {})
            for identity, source in records.items():
                previous = target.get(identity)
                if previous is None:
                    target[identity] = copy.deepcopy(source)
                    continue
                keep_published = (_legacy_entry(kind, source) and not _legacy_entry(kind, previous)) or (
                    kind == 'articles' and source.get('placeholder') is True
                    and previous.get('placeholder') is not True)
                chosen = copy.deepcopy(previous if keep_published else source)
                current = route_path(kind, locale, chosen)
                histories = set(source.get('history', [])) | set(previous.get('history', []))
                histories.update((route_path(kind, locale, source), route_path(kind, locale, previous)))
                chosen['history'] = sorted(histories - {current})
                target[identity] = chosen
    return validate_registry(merged)


def prepare_registry(committed: Path, output: Path, *, published: dict | None) -> dict:
    merged = merge_registries(read_registry(committed), published)
    output = Path(output)
    if output.resolve() == Path(committed).resolve():
        raise RegistryError('Build preparation must not overwrite the committed route registry')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    temporary.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(output)
    return {'baseline': 'published' if published is not None else 'first-publication',
            'counts': {kind: sum(len(records) for records in merged[kind].values()) for kind in KINDS}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--committed', type=Path, default=ROOT / 'data/routes.json')
    parser.add_argument('--output', type=Path, default=ROOT / '.build/routes.json')
    parser.add_argument('--report', type=Path, default=ROOT / '.build/route-registry-report.json')
    parser.add_argument('--published', type=Path, help='Use a captured published registry for an offline review')
    args = parser.parse_args()
    published = read_registry(args.published) if args.published else live_registry()
    result = prepare_registry(args.committed, args.output, published=published)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
