"""Fail-closed article retention checks for complete static publications.

Inventories identify published articles by locale and permanent UUID, independent
of titles, routes, source counts, or deployment deduplication. This module never
fetches a baseline or grants permission to remove a published article.
"""
from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
import uuid

from validate_event import FINGERPRINT, SHA

LOCALE = re.compile(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,4}\Z')
REVISION_NAMES = {'site', 'english', 'translations', 'theme'}
DEPLOYMENT_FIELDS = ('schema', 'display_fingerprint', 'revisions', 'translation_status')


def _reject(message: str) -> None:
    raise ValueError('Refusing publication: ' + message)


def _locale(value: object) -> None:
    if not isinstance(value, str) or not LOCALE.fullmatch(value):
        _reject('article inventory contains an invalid locale tag')


def _identity(value: object, locale: str) -> None:
    try:
        valid = isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        _reject(f'{locale}: article inventory contains an invalid UUID')


def validate_inventory(obj: object) -> dict[str, list[str]]:
    """Validate and copy an inventory into deterministic locale/UUID order."""
    if not isinstance(obj, dict):
        _reject('article inventory must be a locale-to-UUID-list object')
    result = {}
    for locale, identities in obj.items():
        _locale(locale)
        if not isinstance(identities, list):
            _reject(f'{locale}: article inventory must be a UUID list')
        seen = set()
        for identity in identities:
            _identity(identity, locale)
            if identity in seen:
                _reject(f'{locale}: duplicate article UUID {identity}')
            seen.add(identity)
        result[locale] = sorted(seen)
    if not result.get('en'):
        _reject('article inventory requires a nonempty English (en) publication')
    return dict(sorted(result.items()))


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _reject('search index contains a duplicate JSON key')
        result[key] = value
    return result


class _ReaderInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.identities = []

    def handle_starttag(self, tag, attrs):
        # Count attributes directly, so duplicate attributes do not get hidden
        # by conversion to a dict. HTML comments and script strings do not count.
        self.identities.extend(value for name, value in attrs if name == 'data-article-id')


def _real_file(output: Path, relative: Path, description: str) -> Path:
    path = output
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            _reject(description + ' must not use symlinks')
    if not path.is_file():
        _reject(description + ' is missing its local file')
    return path


def _check_reader(output: Path, locale: str, record: dict) -> None:
    description = f'{locale}: indexed article {record["id"]}'
    url = record.get('url')
    if not isinstance(url, str) or not url.startswith('/') or url.startswith('//'):
        _reject(description + ' must have a local reader URL')
    try:
        parsed = urlsplit(url)
        decoded = unquote(parsed.path, errors='strict')
    except ValueError:
        _reject(description + ' has an invalid reader URL')
    parts = decoded.strip('/').split('/')
    if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
            or not decoded.startswith(f'/{locale}/') or '\\' in decoded
            or any(part in {'', '.', '..'} for part in parts)
            or any(ord(character) < 32 or ord(character) == 127 for character in url + decoded)):
        _reject(description + ' has an unsafe or wrong-locale reader URL')
    relative = Path(*parts)
    if decoded.endswith('/'):
        relative /= 'index.html'
    if relative.suffix != '.html':
        _reject(description + ' must point to a local HTML reader')
    reader = _real_file(output, relative, description)
    try:
        parser = _ReaderInventory()
        parser.feed(reader.read_text(encoding='utf-8'))
        parser.close()
    except (OSError, ValueError) as error:
        _reject(description + f' could not be read ({type(error).__name__})')
    if parser.identities != [record['id']]:
        _reject(description + ' reader data-article-id does not match exactly')


def candidate_inventory(output: Path, article_counts: dict) -> dict[str, list[str]]:
    """Read complete generated indexes and verify their counted reader UUIDs.

    The full site checker remains responsible for article text, navigation, and
    source semantics. These complementary checks prevent stale search records
    or build counts alone from masquerading as retained reader pages.
    """
    output = Path(output)
    if output.is_symlink() or not output.is_dir():
        _reject('article inventory requires a real output directory')
    if not isinstance(article_counts, dict):
        _reject('article counts must cover every indexed locale')
    for locale, count in article_counts.items():
        _locale(locale)
        if type(count) is not int or count < 0:
            _reject(f'{locale}: article count must be a nonnegative integer')
    indexed_locales = {path.parent.name for path in output.glob('*/search-index.json')}
    for locale in indexed_locales:
        _locale(locale)
    if set(article_counts) != indexed_locales:
        _reject('article counts and search indexes have different locale sets')
    inventory = {}
    for locale in sorted(indexed_locales):
        index = _real_file(output, Path(locale) / 'search-index.json', f'{locale}: search index')
        try:
            records = json.loads(index.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
        except (OSError, ValueError) as error:
            _reject(f'{locale}: invalid or unreadable search index ({type(error).__name__})')
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            _reject(f'{locale}: search index must contain article objects')
        if len(records) != article_counts[locale]:
            _reject(f'{locale}: search inventory count {len(records)} differs from build count {article_counts[locale]}')
        identities = [record.get('id') for record in records]
        # Validate all identities before using any record in paths or messages.
        for identity in identities:
            _identity(identity, locale)
        if len(set(identities)) != len(identities):
            _reject(f'{locale}: duplicate article UUID in search index')
        for record in records:
            _check_reader(output, locale, record)
        inventory[locale] = identities
    return validate_inventory(inventory)


def assert_retains(previous: dict, candidate: dict) -> None:
    """Reject every missing prior locale or article; no count-based exception."""
    previous = validate_inventory(previous)
    candidate = validate_inventory(candidate)
    losses = []
    for locale, identities in previous.items():
        if locale not in candidate:
            losses.append(f'{locale}: locale disappeared ({len(identities)} published articles)')
            continue
        missing = sorted(set(identities) - set(candidate[locale]))
        if missing:
            sample = ', '.join(missing[:3])
            suffix = f', +{len(missing) - 3} more' if len(missing) > 3 else ''
            losses.append(f'{locale}: {len(missing)} published article UUID(s) disappeared ({sample}{suffix})')
    if losses:
        summary = '; '.join(losses[:5])
        if len(losses) > 5:
            summary += f'; +{len(losses) - 5} more affected locales'
        _reject(summary + '; retain the whole last successful publication')


def _deployment_identity(obj: object) -> dict:
    if not isinstance(obj, dict) or type(obj.get('schema')) is not int or obj['schema'] != 1:
        _reject('publication baseline has an invalid deployment schema')
    fingerprint = obj.get('display_fingerprint')
    if not isinstance(fingerprint, str) or not FINGERPRINT.fullmatch(fingerprint):
        _reject('publication baseline has an invalid display fingerprint')
    revisions = obj.get('revisions')
    if (not isinstance(revisions, dict) or set(revisions) != REVISION_NAMES
            or any(not isinstance(value, str) or not SHA.fullmatch(value) for value in revisions.values())):
        _reject('publication baseline requires complete fixed revisions')
    if obj.get('translation_status') != 'ready':
        _reject('publication baseline translation status must be ready')
    return {field: obj[field] for field in DEPLOYMENT_FIELDS}


def baseline_inventory(live_manifest: dict, migration_snapshot: dict | None = None) -> dict[str, list[str]]:
    """Trust a live inventory or an exactly pinned one-time migration snapshot.

    An invalid present inventory never falls back to migration data. A snapshot
    is eligible only while all four deployment identity fields still match.
    """
    live_identity = _deployment_identity(live_manifest)
    if 'article_inventory' in live_manifest:
        return validate_inventory(live_manifest['article_inventory'])
    if not isinstance(migration_snapshot, dict):
        _reject('live publication has no article inventory and no verified migration snapshot')
    migration_identity = _deployment_identity(migration_snapshot.get('deployment'))
    if migration_identity != live_identity:
        _reject('migration snapshot does not match the live publication identity')
    if 'article_inventory' not in migration_snapshot:
        _reject('migration snapshot has no article inventory')
    return validate_inventory(migration_snapshot['article_inventory'])
