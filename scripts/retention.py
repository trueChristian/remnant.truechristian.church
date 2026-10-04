"""Build-time, pinned provenance for publications retained across source changes."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import uuid
from urllib.parse import unquote

if __package__:
    from .historical_source import HistoricalSources, verify_retained_source
    from .publication_inventory import baseline_inventory
    from .retained_assets import pin_article_assets, validate_origin, image_path
else:
    from historical_source import HistoricalSources, verify_retained_source
    from publication_inventory import baseline_inventory
    from retained_assets import pin_article_assets, validate_origin, image_path

SHA = re.compile(r'[a-f0-9]{40}\Z')


def ledger_digest(value: dict) -> str:
    """Detect incomplete provenance before it can select replacement bytes."""
    payload = {key: item for key, item in value.items() if key != 'sha256'}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Invalid retained article UUID')


def validate_ledger(value: object, inventory: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {'schema', 'english_sources', 'images', 'aliases', 'sha256'} or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('Invalid publication retention ledger')
    if value['sha256'] != ledger_digest(value):
        raise ValueError('Publication retention ledger integrity check failed')
    sources = value['english_sources']
    if (not isinstance(sources, dict) or set(sources) != set(inventory['en'])
            or any(not isinstance(pin, str) or not SHA.fullmatch(pin) for pin in sources.values())):
        raise ValueError('Retention ledger must identify every published English source revision')
    if not isinstance(value['images'], dict) or not isinstance(value['aliases'], dict):
        raise ValueError('Invalid retained image ledger')
    for tag, identities in inventory.items():
        if set(value['images'].get(tag, {})) != set(identities):
            raise ValueError('Image ledger must cover every published article, including articles without images')
    for tag, articles in value['images'].items():
        if tag not in inventory or not isinstance(articles, dict):
            raise ValueError('Image ledger contains an unpublished language')
        for identity, origins in articles.items():
            _uuid(identity)
            if identity not in inventory[tag] or not isinstance(origins, dict):
                raise ValueError('Image ledger contains an unpublished article')
            for original, origin in origins.items():
                validate_origin(original, origin)
    for original, origin in value['aliases'].items():
        validate_origin(original, origin)
        if origin['public_path'] != original:
            raise ValueError('Original retained image alias changed its URL')
    return copy.deepcopy(value)


def validate_published_assets(output: Path, ledger: dict) -> None:
    """Bind public provenance to the actual packaged bytes, once per path."""
    checked = {}
    origins = list(ledger['aliases'].values())
    origins.extend(origin for articles in ledger['images'].values()
                   for images in articles.values() for origin in images.values())
    for origin in origins:
        public_path = origin['public_path']
        path = Path(output) / unquote(public_path, errors='strict').lstrip('/')
        if public_path not in checked:
            if any(part.is_symlink() for part in (path.absolute(), *path.absolute().parents)):
                raise ValueError('Published retention asset cannot traverse a symlink')
            if not path.is_file():
                raise ValueError('Published retention asset is missing: ' + public_path)
            checked[public_path] = hashlib.sha256(path.read_bytes()).hexdigest()
        if checked[public_path] != origin['sha256']:
            raise ValueError('Published retention asset differs from its recorded bytes: ' + public_path)


def copy_retained_assets(output: Path, copies: list) -> None:
    for asset in copies:
        target = Path(output) / unquote(image_path(asset['public_path']), errors='strict').lstrip('/')
        source = Path(asset['source'])
        if any(part.is_symlink() for path in (target, source) for part in (path.absolute(), *path.absolute().parents)):
            raise ValueError('Retained asset copying cannot traverse a symlink')
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != asset['sha256']:
            raise ValueError('Retained asset changed after source verification')
        if target.exists() and target.read_bytes() != raw:
            raise ValueError('Retained asset would replace different current source bytes')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


class PublicationRetention:
    def __init__(self, previous: dict, migration_snapshot: dict | None, *, current_root: Path,
                 current_revision: str, cache_dir: Path, history=None, source_revisions=None):
        self.previous = previous
        self.inventory = baseline_inventory(previous, migration_snapshot)
        self.current_root, self.current_revision = Path(current_root), current_revision
        self.source_revisions = source_revisions
        self.history = history or HistoricalSources(Path(cache_dir) / 'source-objects')
        self.asset_cache = Path(cache_dir) / 'images'
        if 'retention' in previous:
            self.prior = validate_ledger(previous['retention'], self.inventory)
        else:
            self.prior = {'schema': 1, 'english_sources': {
                identity: previous['revisions']['english'] for identity in self.inventory['en']},
                'images': {}, 'aliases': {}}
        self.ledger = {'schema': 1, 'english_sources': {}, 'images': {}, 'aliases': {}}
        self.copies = {}

    def missing_english(self, current_ids):
        for identity in sorted(set(self.inventory['en']) - set(current_ids)):
            yield self.history.article(self.prior['english_sources'][identity], identity)

    def translation_source(self, item):
        status = item.get('status')
        if status not in {'stale', 'source_removed'} or item.get('retained') is not True:
            raise ValueError('Retained translation must explicitly identify its compatibility state')
        expected_reason = 'english_changed' if status == 'stale' else 'english_removed'
        if item.get('retention_reason') != expected_reason:
            raise ValueError('Retained translation reason disagrees with its status')
        current_key = item.get('current_source_translation_key')
        if status == 'stale':
            if (not isinstance(current_key, str) or not re.fullmatch(r'[a-f0-9]{64}', current_key)
                    or current_key == item.get('source_translation_key')):
                raise ValueError('Changed English source must have a distinct current fingerprint')
        elif current_key is not None:
            raise ValueError('Removed English source must not claim a current fingerprint')
        spec = item.get('retained_source')
        if not isinstance(spec, dict) or spec.get('translation_key') != item.get('source_translation_key'):
            raise ValueError('Retained publication fingerprint differs from its original source snapshot')
        source = verify_retained_source(spec, item['id'], item['source_revision'], self.history.read)
        if source['article']['issue_id'] != item['issue_id']:
            raise ValueError('Retained translation issue differs from its original source')
        return source

    def assets(self, article, *, retained=False, fallback_revisions=()):
        tag, identity = article['locale'], article['id']
        if tag == 'en':
            self.ledger['english_sources'][identity] = article['source_revision']
        result = pin_article_assets(article, current_root=self.current_root,
            current_revision=self.current_revision, read_historical=self.history.read,
            cache_dir=self.asset_cache, retained=retained,
            prior_origins=self.prior['images'].get(tag, {}).get(identity),
            prior_aliases=self.prior['aliases'], fallback_revisions=fallback_revisions)
        self.ledger['images'].setdefault(tag, {})[identity] = result['origins']
        for path, origin in result['aliases'].items():
            if path in self.ledger['aliases'] and self.ledger['aliases'][path]['sha256'] != origin['sha256']:
                raise ValueError('Two retained copies disagree on the original published image URL')
            self.ledger['aliases'][path] = origin
        for item in result['copies']:
            old = self.copies.get(item['public_path'])
            if old and old['sha256'] != item['sha256']:
                raise ValueError('Retained image targets conflict')
            self.copies[item['public_path']] = item
        return result['article']

    def finish(self, model):
        inventory = {tag: [article['id'] for article in articles] for tag, articles in model['articles'].items()}
        self.ledger['sha256'] = ledger_digest(self.ledger)
        model['retention'] = validate_ledger(self.ledger, inventory)
        model['retained_asset_copies'] = list(self.copies.values())


def load_retention_context(english_root: Path, context_path: Path | None = None, *, site_revision=None):
    path = context_path or Path(english_root).parent / 'retention-context.json'
    if not path.exists():
        return None
    if any(part.is_symlink() for part in (path.absolute(), *path.absolute().parents)):
        raise ValueError('Retention context cannot be a symlink')
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or set(value) != {'schema', 'source_revisions', 'baseline', 'migration_snapshot'} or value['schema'] != 1:
        raise ValueError('Invalid retention context')
    revisions = value['source_revisions']
    if (not isinstance(revisions, dict) or set(revisions) != {'site', 'english', 'translations', 'theme'}
            or any(not isinstance(pin, str) or not SHA.fullmatch(pin) for pin in revisions.values())
            or (site_revision is not None and revisions['site'] != site_revision)):
        raise ValueError('Retention context does not match the selected immutable sources')
    return PublicationRetention(value['baseline'], value['migration_snapshot'], current_root=english_root,
        current_revision=revisions['english'], cache_dir=Path(english_root).parent / 'retention-cache',
        source_revisions=revisions)
