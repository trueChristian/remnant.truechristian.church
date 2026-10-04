"""Preserve source image bytes without changing article prose or attribution."""
from __future__ import annotations

import copy
import hashlib
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

if __package__:
    from .historical_source import HistoricalFileMissing
else:
    from historical_source import HistoricalFileMissing

SHA = re.compile(r'[a-f0-9]{40}\Z')
DIGEST = re.compile(r'[a-f0-9]{64}\Z')
PREFIX = '/images/articles/'


def _no_symlinks(path: Path):
    absolute = path.absolute()
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise ValueError('Retained asset paths cannot traverse a symlink')


def image_path(value: object) -> str:
    if not isinstance(value, str) or not value.startswith(PREFIX):
        raise ValueError('Retained image must use the shared article image path')
    parsed = urlsplit(value)
    decoded = unquote(parsed.path, errors='strict')
    if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or '\\' in decoded
            or any(part in {'', '.', '..'} for part in decoded[1:].split('/'))
            or any(ord(char) < 32 or ord(char) == 127 for char in value + decoded)):
        raise ValueError('Unsafe retained image path')
    return value


def validate_origin(original: str, origin: object) -> dict:
    image_path(original)
    if not isinstance(origin, dict) or set(origin) != {'revision', 'repository_path', 'sha256', 'public_path'}:
        raise ValueError('Incomplete retained image origin')
    if not isinstance(origin['revision'], str) or not SHA.fullmatch(origin['revision']):
        raise ValueError('Retained image origin requires an immutable English revision')
    if origin['repository_path'] != 'public' + unquote(original, errors='strict'):
        raise ValueError('Retained image origin does not identify the original shared path')
    if not isinstance(origin['sha256'], str) or not DIGEST.fullmatch(origin['sha256']):
        raise ValueError('Invalid retained image digest')
    image_path(origin['public_path'])
    return copy.deepcopy(origin)


def current_asset(root: Path, public_path: str) -> Path | None:
    image_path(public_path)
    _no_symlinks(root)
    relative = Path(unquote(public_path, errors='strict').lstrip('/'))
    if not (root / 'images').is_dir():
        relative = Path('public') / relative
    path = root
    if path.is_symlink():
        raise ValueError('Image export cannot be a symlink')
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise ValueError('Image files cannot use symlinks')
    return path if path.is_file() else None


class _ImageRewriter(HTMLParser):
    def __init__(self, source: str, replacements: dict[str, str]):
        super().__init__(convert_charrefs=False)
        self.source, self.replacements, self.edits = source, replacements, []
        self.offsets = [0]
        # HTMLParser counts only LF as a new line; Unicode paragraph separators
        # and lone CR are ordinary characters in its source positions.
        for match in re.finditer('\n', source):
            self.offsets.append(match.end())
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag != 'img':
            return
        values = [value for key, value in attrs if key == 'src']
        if len(values) != 1:
            raise ValueError('Image markup must have exactly one source attribute')
        if values[0] not in self.replacements:
            return
        raw = self.get_starttag_text()
        # Tokenize whole attributes, so a literal "src=" inside alt text is not
        # mistaken for another attribute. Keep every byte outside src intact.
        start = re.match(r'<\s*[^\s/>]+', raw).end()
        token = re.compile(r'''\s+([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?''')
        matches = [match for match in token.finditer(raw, start) if match.group(1).lower() == 'src']
        if len(matches) != 1:
            raise ValueError('Ambiguous image source markup')
        match = matches[0]
        if unescape(next(value for value in match.groups()[1:] if value is not None)) != values[0]:
            raise ValueError('Image source parsing mismatch')
        line, column = self.getpos()
        start = self.offsets[line - 1] + column
        replacement = 'src="' + escape(self.replacements[values[0]], quote=True) + '"'
        self.edits.append((start + match.start(1), start + match.end(), replacement))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def result(self) -> str:
        result = self.source
        for start, end, replacement in reversed(self.edits):
            result = result[:start] + replacement + result[end:]
        return result


def pin_article_assets(article: dict, *, current_root: Path, current_revision: str,
                       read_historical, cache_dir: Path, retained: bool,
                       prior_origins: dict | None = None, fallback_revisions=(),
                       prior_aliases: dict | None = None) -> dict:
    if not isinstance(current_revision, str) or not SHA.fullmatch(current_revision):
        raise ValueError('Image origin requires the selected English revision')
    result = copy.deepcopy(article)
    origins, copies, replacements, aliases = {}, {}, {}, {}
    prior_origins = prior_origins or {}
    prior_aliases = prior_aliases or {}
    for image in result.get('images', []):
        original = image_path(image['public_path'])
        if original in origins:
            image['public_path'] = origins[original]['public_path']
            continue
        current = current_asset(current_root, original)
        repository_path = 'public' + unquote(original, errors='strict')
        if not retained:
            if current is None:
                raise ValueError('Current publication image is absent from the English export')
            raw, revision = current.read_bytes(), current_revision
        elif original in prior_origins:
            prior = validate_origin(original, prior_origins[original])
            revision = prior['revision']
            raw = read_historical(revision, repository_path)
            if hashlib.sha256(raw).hexdigest() != prior['sha256']:
                raise ValueError('Previously published image bytes no longer match their recorded origin')
        else:
            raw = None
            candidates = list(dict.fromkeys(fallback_revisions))
            if not candidates:
                raise ValueError('Retained image needs a verified historical source before considering current bytes')
            for revision in candidates:
                if not isinstance(revision, str) or not SHA.fullmatch(revision):
                    raise ValueError('Invalid historical image revision')
                try:
                    raw = read_historical(revision, repository_path)
                    break
                except HistoricalFileMissing:
                    continue
            if raw is None:
                if current is None:
                    raise ValueError('No verified historical or current copy of the publication image is available')
                raw, revision = current.read_bytes(), current_revision
        digest = hashlib.sha256(raw).hexdigest()
        target = original
        if retained:
            target = PREFIX + 'retained/' + digest + '/' + original[len(PREFIX):]
            _no_symlinks(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached = cache_dir / digest
            if cached.is_symlink():
                raise ValueError('Retained asset cache file cannot be a symlink')
            if cached.exists() and cached.read_bytes() != raw:
                raise ValueError('Retained asset cache digest mismatch')
            if not cached.exists():
                cached.write_bytes(raw)
            copies[target] = {'source': str(cached.resolve()), 'public_path': target, 'sha256': digest}
            if current is None:
                alias_raw, alias_revision = raw, revision
                if original in prior_aliases:
                    alias = validate_origin(original, prior_aliases[original])
                    if alias['public_path'] != original:
                        raise ValueError('Original image alias must retain its original URL')
                    alias_revision = alias['revision']
                    alias_raw = read_historical(alias_revision, repository_path)
                    if hashlib.sha256(alias_raw).hexdigest() != alias['sha256']:
                        raise ValueError('Original published image alias digest mismatch')
                alias_digest = hashlib.sha256(alias_raw).hexdigest()
                alias_cache = cache_dir / alias_digest
                if alias_cache.is_symlink() or (alias_cache.exists() and alias_cache.read_bytes() != alias_raw):
                    raise ValueError('Original image alias cache mismatch')
                if not alias_cache.exists():
                    alias_cache.write_bytes(alias_raw)
                copies[original] = {'source': str(alias_cache.resolve()), 'public_path': original, 'sha256': alias_digest}
                aliases[original] = {'revision': alias_revision, 'repository_path': repository_path,
                                     'sha256': alias_digest, 'public_path': original}
            replacements[original] = target
        else:
            aliases[original] = {'revision': revision, 'repository_path': repository_path,
                                 'sha256': digest, 'public_path': original}
        origins[original] = {'revision': revision, 'repository_path': repository_path,
                             'sha256': digest, 'public_path': target}
        image['public_path'] = target
    if replacements:
        result['html'] = _ImageRewriter(result['html'], replacements).result()
    result['image'] = result['images'][0] if result.get('images') else None
    result['asset_origins'] = origins
    return {'article': result, 'origins': origins, 'copies': list(copies.values()), 'aliases': aliases}
