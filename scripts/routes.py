"""Stable localized routes with UUID identity kept inside the route registry.

Every published article has one readable canonical route per language. Frozen
aliases survive title/category edits; alternate language-prefix spellings and
legacy UUID routes are redirects to that canonical route. New aliases are
allocated from localized titles, with numeric suffixes for collisions.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import unquote
import uuid

if __package__:
    from .authors import build_author_index
else:
    from authors import build_author_index

RESERVED = {"articles", "issues", "categories", "authors", "topics", "series", "search", "assets", "images", "feeds", "rss", "feed", "sitemap", "404", "index", "api", "downloads", "routes"}
UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


class RouteError(ValueError):
    pass


def slugify(value: str | None, fallback: str = "article") -> str:
    """Unicode-safe slug; retain scripts rather than invented transliterations."""
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = "".join(char if unicodedata.category(char)[0] in "LNM" else "-" for char in value)
    return re.sub(r"-+", "-", value).strip("-")[:100].rstrip("-") or fallback


def _slug(value: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."} or any(char in value for char in "/\\?#%"):
        raise RouteError(f"Unsafe slug: {value!r}")
    if any(unicodedata.category(char)[0] not in "LNM" and char != "-" for char in value):
        raise RouteError(f"Invalid slug characters: {value!r}")
    return value


def _locale(value: str) -> str:
    if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value):
        raise RouteError(f"Invalid URL language tag: {value!r}")
    return value


def _uuid(value: str) -> str:
    try:
        if str(uuid.UUID(value)) == value:
            return value
    except (ValueError, AttributeError):
        pass
    raise RouteError(f"Invalid route UUID: {value!r}")


def _key(path: str) -> str:
    """Match browser-encoded paths, Unicode equivalents, and slug case."""
    return unicodedata.normalize("NFC", unquote(path)).casefold()


def _path(locale: str, record: dict) -> str:
    return f"/{_locale(locale)}/{_slug(record['category_slug'])}/{_slug(record['alias'])}/"


def _group_path(kind: str, locale: str, slug: str) -> str:
    return f"/{locale}/" + (kind + "/" if kind in {"issues", "authors"} else "") + _slug(slug) + "/"


def _author_name(value: str) -> str:
    """Keep exact source spelling while rejecting malformed registry identities."""
    if (not isinstance(value, str) or not value.strip() or len(value) > 1024
            or any(unicodedata.category(char)[0] == "C" for char in value)):
        raise RouteError(f"Invalid author name: {value!r}")
    return value


def _author_history(path: str, locale: str) -> str:
    _history(path, locale)
    try:
        decoded = unquote(path, errors="strict")
    except UnicodeError as error:
        raise RouteError(f"Unsafe author history: {path!r}") from error
    parts = decoded.strip("/").split("/")
    if (len(path) > 4096 or re.search(r"%(?![0-9a-fA-F]{2})", path)
            or decoded.count("/") != path.count("/") or len(parts) != 3
            or parts[:2] != [locale, "authors"] or parts[-1].casefold() == "page"):
        raise RouteError(f"Unsafe author history: {path!r}")
    _slug(parts[-1])
    return path


def _history(path: str, locale: str) -> str:
    if not isinstance(path, str):
        raise RouteError(f"Unsafe redirect history: {path!r}")
    decoded = unquote(path)
    parts = decoded.split("/")
    if (not decoded.startswith(f"/{locale}/") or not decoded.endswith("/")
            or any(char in decoded for char in "\\?#")
            or any(part in {".", "..", ""} for part in parts[1:-1])
            or any(unicodedata.category(char)[0] == "C" for char in decoded)):
        raise RouteError(f"Unsafe redirect history: {path!r}")
    return path


def _readable(value: str | None, fallback: str) -> str:
    """Never carry legacy UUID suffixes into a public canonical alias."""
    return slugify(UUID_PATTERN.sub("", value or ""), fallback)


def set_article_alias(registry: dict, locale: str, identity: str, alias: str, category_slug: str | None = None) -> None:
    """Explicit migration preserving all previous addresses as redirects.

    initialize_routes validates collisions before the candidate can be saved.
    UUIDs are accepted only as internal identities or legacy redirect sources.
    """
    _locale(locale)
    _uuid(identity)
    if UUID_PATTERN.search(alias) or (category_slug and UUID_PATTERN.search(category_slug)):
        raise RouteError("UUIDs are not permitted in canonical article URLs")
    entry = registry["articles"][locale][identity]
    previous = _path(locale, entry)
    history = set(entry.get("history", [])) | {previous}
    if entry.get("fallback"):
        for category in registry["categories"][locale].values():
            history.add(f"/{locale}/{category['slug']}/article-{identity}/")
    entry["alias"] = _slug(alias)
    if category_slug is not None:
        entry["category_slug"] = _slug(category_slug)
    entry["history"] = sorted(history - {_path(locale, entry)})
    entry["fallback"] = False
    entry.pop("placeholder", None)


def initialize_routes(model: dict, locales, registry_path: Path, update: bool = False) -> dict:
    """Resolve readable frozen routes and language-prefix redirects by UUID.

    Ordinary builds return a complete candidate registry without editing the
    checkout. update=True atomically saves that candidate after all validation.
    Missing translations get readable availability routes, marked placeholders;
    publishing the translation promotes its own localized title and retains the
    former availability address as a redirect.
    """
    config = locales if isinstance(locales, dict) else {tag: {} for tag in locales}
    if "en" not in config:
        raise RouteError("English locale is required")
    tags = ["en"] + [tag for tag in config if tag != "en"]
    for tag in tags:
        _locale(tag)
    unknown = set(model["articles"]) - set(tags)
    if unknown:
        raise RouteError(f"Exported languages are not configured: {sorted(unknown)}")
    registry_path = Path(registry_path)
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        if registry.get("version") != 1:
            raise RouteError("Unsupported route registry version")
    else:
        registry = {"version": 1, "categories": {}, "issues": {}, "articles": {}}
    registry = copy.deepcopy(registry)
    result = {"categories": {}, "issues": {}, "articles": {}, "authors": {}, "redirects": {}, "registry": registry, "pending": []}
    occupied: dict[str, tuple[str, str, str]] = {}
    aliases: dict[str, tuple[str, str]] = {}
    alias_spellings: dict[str, set[str]] = {}
    legacy_sources: dict[str, tuple[str, str, str]] = {}
    result["legacy_aliases"] = {}
    authors = {author["id"]: author for author in build_author_index(model)}
    for identity in authors:
        _author_name(identity)
    articles = {tag: {item["id"]: item for item in model["articles"].get(tag, [])} for tag in tags}
    for tag in tags:
        if len(articles[tag]) != len(model["articles"].get(tag, [])):
            raise RouteError(f"Duplicate article UUID in {tag}")
        for identity in articles[tag]:
            _uuid(identity)
        orphaned = set(articles[tag]) - set(articles["en"])
        if orphaned:
            raise RouteError(f"Translated articles have no English identity in {tag}: {sorted(orphaned)}")
        for kind in ("categories", "issues", "articles", "authors"):
            if not isinstance(registry.setdefault(kind, {}), dict):
                raise RouteError(f"Route {kind} must be a locale map")
            registry.setdefault(kind, {}).setdefault(tag, {})
            if not isinstance(registry[kind][tag], dict):
                raise RouteError(f"Route {kind}/{tag} must be an identity map")
            result[kind][tag] = {}

    def reserve(path, owner):
        key = _key(path)
        if key in occupied and occupied[key] != owner:
            raise RouteError(f"Route collision: {path} ({occupied[key]} and {owner})")
        occupied[key] = owner

    def remember(path, kind, identity):
        # The tail identifies the object independently of the source language.
        tail = "/" + path.split("/", 2)[2]
        key = _key(tail)
        owner = (kind, identity)
        if key in aliases and aliases[key] != owner:
            raise RouteError(f"Ambiguous language-prefix alias: {tail} ({aliases[key]} and {owner})")
        aliases[key] = owner
        alias_spellings.setdefault(key, set()).add(tail)
        if kind != "authors" and UUID_PATTERN.search(tail):
            # UUID paths remain migration inputs, never public canonical URLs.
            # Own-locale static redirects keep existing bookmarks working. A
            # compact exact lookup supports prefix changes on these old inputs
            # without multiplying every historical UUID route by every locale.
            tag = unquote(path).split("/", 2)[1]
            legacy_sources[path] = (kind, tag, identity)
            result["legacy_aliases"][tail] = {"kind": kind, "id": identity}

    def redirect(old, new, owner):
        if old == new:
            return
        reserve(old, owner)
        if old in result["redirects"] and result["redirects"][old] != new:
            raise RouteError(f"Ambiguous redirect: {old}")
        result["redirects"][old] = new

    def allocate(base, path_for, owner, *, reserved=False):
        alias, number = base, 2
        def unavailable(value):
            path = path_for(value)
            tail_key = _key("/" + path.split("/", 2)[2])
            return ((_key(path) in occupied and occupied[_key(path)] != owner)
                    or (tail_key in aliases and aliases[tail_key] != (owner[0], owner[2])))

        while (reserved and alias in RESERVED) or unavailable(alias):
            alias = f"{base}-{number}"
            number += 1
        reserve(path_for(alias), owner)
        return alias

    def mark_pending(kind, tag, identity):
        result["pending"].append({"kind": kind, "locale": tag, "id": identity})

    # Reserve retired records and history before assigning any new alias. Old
    # addresses can never be silently reassigned to another article/category.
    original_categories = copy.deepcopy(registry["categories"])
    for tag in tags:
        reserve(f"/{tag}/", ("reserved", tag, "home"))
        for reserved in RESERVED:
            reserve(f"/{tag}/{reserved}/", ("reserved", tag, reserved))
        reserve(f"/{tag}/authors/page/", ("reserved", tag, "authors-page"))
        for kind in ("categories", "issues", "articles", "authors"):
            for identity, entry in registry[kind][tag].items():
                if kind == "authors":
                    _author_name(identity)
                    if not isinstance(entry, dict) or set(entry) - {"slug", "history"}:
                        raise RouteError("Author route records must contain a slug and optional history")
                    _slug(entry.get("slug"))
                    if entry["slug"].casefold() == "page" or UUID_PATTERN.search(entry["slug"]):
                        raise RouteError(f"Invalid canonical author slug: {entry['slug']!r}")
                    if not isinstance(entry.get("history", []), list) or len(entry.get("history", [])) > 10000:
                        raise RouteError("Author route history must be a bounded list")
                else:
                    _uuid(identity)
                owner = (kind, tag, identity)
                path = _path(tag, entry) if kind == "articles" else _group_path(kind, tag, entry["slug"])
                reserve(path, owner)
                remember(path, kind, identity)
                for old in entry.get("history", []):
                    checked = _author_history(old, tag) if kind == "authors" else _history(old, tag)
                    reserve(checked, owner)
                    remember(checked, kind, identity)

    # Author names are exact source identities, shared by all language views.
    # Frozen aliases and histories reserve retired names before new allocation.
    for tag in tags:
        records = registry["authors"][tag]
        for identity in sorted(authors, key=lambda name: (name.casefold(), name)):
            entry = records.get(identity)
            owner = ("authors", tag, identity)
            if entry is None:
                english = registry["authors"]["en"].get(identity, {})
                base = english.get("slug") or _readable(identity, "author")
                if base == "page":
                    base = "author-page"
                slug = allocate(base, lambda value: _group_path("authors", tag, value), owner)
                records[identity] = entry = {"slug": slug, "history": []}
                mark_pending("authors", tag, identity)
            path = _group_path("authors", tag, entry["slug"])
            reserve(path, owner)
            result["authors"][tag][identity] = path
            remember(path, "authors", identity)

    for tag in tags:
        for kind in ("categories", "issues"):
            groups = {group["id"]: group for group in model[kind]}
            if len(groups) != len(model[kind]):
                raise RouteError(f"Duplicate {kind} UUID")
            records = registry[kind][tag]
            for identity in sorted(set(groups) | set(records)):
                _uuid(identity)
                group = groups.get(identity, {})
                entry = records.get(identity)
                owner = (kind, tag, identity)
                translated = config[tag].get("categories", {}).get(identity, {}) if isinstance(config[tag], dict) and kind == "categories" else {}
                if entry is None or UUID_PATTERN.search(entry["slug"]):
                    old = _group_path(kind, tag, entry["slug"]) if entry else None
                    name = translated.get("slug") or group.get("slug") or (entry or {}).get("slug")
                    base = _readable(name, "category" if kind == "categories" else "issue")
                    if kind == "categories" and base in RESERVED:
                        base = "category-" + base
                    slug = allocate(base, lambda value: _group_path(kind, tag, value), owner)
                    history = set((entry or {}).get("history", []))
                    if old:
                        history.add(old)
                    records[identity] = entry = {"slug": slug, "history": sorted(history - {_group_path(kind, tag, slug)})}
                    mark_pending(kind, tag, identity)
                if kind == "categories" and entry["slug"] in RESERVED:
                    raise RouteError(f"Category uses reserved namespace: {entry['slug']}")
                path = _group_path(kind, tag, entry["slug"])
                if identity in groups:
                    result[kind][tag][identity] = path
                remember(path, kind, identity)
                for old in entry.get("history", []):
                    remember(_history(old, tag), kind, identity)

    for tag in tags:
        records = registry["articles"][tag]
        for identity in sorted(set(articles["en"]) | set(records)):
            source = articles[tag].get(identity)
            english = articles["en"].get(identity)
            entry = records.get(identity)
            owner = ("articles", tag, identity)
            old = _path(tag, entry) if entry else None
            history = set((entry or {}).get("history", []))
            was_fallback = bool(entry and entry.get("fallback"))
            is_new = entry is None
            # Category addresses are frozen with an existing article. Migrating a
            # category's UUID suffix is the only automatic category-path change.
            category_id = (entry or {}).get("category_id")
            if category_id is None:
                category_id = (source or english)["categories"]["primary"]
            if category_id not in registry["categories"][tag]:
                raise RouteError(f"Unknown primary category {category_id} for article {identity} in {tag}")
            category_slug = (entry or {}).get("category_slug") or registry["categories"][tag][category_id]["slug"]
            previous_category = original_categories.get(tag, {}).get(category_id, {}).get("slug")
            if category_slug == previous_category or UUID_PATTERN.search(category_slug):
                category_slug = registry["categories"][tag][category_id]["slug"]
            promote = bool(entry and entry.get("placeholder") and source is not None)
            missing_placeholder = source is None and english is not None and (entry is None or entry.get("placeholder"))
            if missing_placeholder:
                # Availability pages are noindex and are not category content.
                # Sharing their English tail avoids one localized-category
                # redirect permutation for every still-missing translation.
                category_slug = "articles"
            elif promote:
                category_slug = registry["categories"][tag][category_id]["slug"]
            migrate = bool(entry and (was_fallback or UUID_PATTERN.search(entry["alias"]) or UUID_PATTERN.search(entry["category_slug"])))
            if entry is None or promote or migrate:
                if source is not None:
                    title = source.get("title") or config[tag].get("ui", {}).get("untitled_article")
                elif entry and not entry.get("placeholder"):
                    title = entry["alias"]
                else:
                    title = registry["articles"]["en"].get(identity, {}).get("alias") or (english or {}).get("title")
                base = _readable(title, "article")
                alias = allocate(base, lambda value: f"/{tag}/{category_slug}/{value}/", owner, reserved=True)
                if old:
                    history.add(old)
                entry = {"category_id": category_id, "category_slug": category_slug, "alias": alias,
                         "history": sorted(history - {f"/{tag}/{category_slug}/{alias}/"}), "fallback": False}
                if source is None and english is not None:
                    entry["placeholder"] = True
                records[identity] = entry
                mark_pending("articles", tag, identity)
            elif category_slug != entry["category_slug"]:
                history.add(old)
                entry["category_slug"] = category_slug
                entry["history"] = sorted(history - {_path(tag, entry)})
                mark_pending("articles", tag, identity)
            path = _path(tag, entry)
            if UUID_PATTERN.search(path):
                raise RouteError(f"UUID in canonical article route: {path}")
            reserve(path, owner)
            if english is not None:
                result["articles"][tag][identity] = path
            remember(path, "articles", identity)
            for old_path in entry.get("history", []):
                remember(_history(old_path, tag), "articles", identity)
            compatibility = f"/{tag}/articles/{identity}/"
            remember(compatibility, "articles", identity)
            if is_new and source is not None:
                # A prior ordinary build may have published this UUID fallback
                # before its generated registry was synchronized to the repo.
                legacy = f"/{tag}/{category_slug}/article-{identity}/"
                entry["history"] = sorted(set(entry["history"]) | {legacy})
                remember(legacy, "articles", identity)
            # Legacy normal builds assigned UUID aliases below any category.
            # Preserve every such old spelling when migrating a fallback record.
            if was_fallback:
                for category in original_categories.get(tag, {}).values():
                    history.add(f"/{tag}/{category['slug']}/article-{identity}/")
                for category in registry["categories"][tag].values():
                    history.add(f"/{tag}/{category['slug']}/article-{identity}/")
                entry["history"] = sorted(history - {path})
                for old_path in entry["history"]:
                    remember(_history(old_path, tag), "articles", identity)
            if source is not None:
                source.update(url=path, markdown_url=path.rstrip("/") + ".md", compatibility_url=compatibility)

    # Build direct redirects after every canonical has been assigned. Replacing
    # any source locale prefix resolves to the same identity in the target locale
    # and updates both localized category and article aliases in one step.
    for key, (kind, identity) in aliases.items():
        if kind != "authors" and UUID_PATTERN.search(key):
            continue
        for tag in tags:
            destination = result[kind][tag].get(identity)
            if destination is None:  # Retired identities reserve aliases only.
                continue
            for tail in sorted(alias_spellings[key]):
                redirect(f"/{tag}{tail}", destination, (kind, tag, identity))
    for path, (kind, tag, identity) in legacy_sources.items():
        destination = result[kind][tag].get(identity)
        if destination is not None:
            redirect(path, destination, (kind, tag, identity))
    result["cross_locale_aliases"] = {key: {"kind": owner[0], "id": owner[1]} for key, owner in aliases.items()}
    if update:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = registry_path.with_suffix(registry_path.suffix + ".tmp")
        temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(registry_path)
    return result


def article_url(routes: dict, locale: str, identity: str) -> str:
    return routes["articles"][locale][identity]


def category_url(routes: dict, locale: str, identity: str) -> str:
    return routes["categories"][locale][identity]


def issue_url(routes: dict, locale: str, identity: str) -> str:
    return routes["issues"][locale][identity]


def author_url(routes: dict, locale: str, name: str) -> str:
    return routes["authors"][locale][name]
