"""Website-owned stable routes: UUID identity, persisted aliases, explicit history.

Unknown articles publish without waiting for a repository commit, using a UUID
alias. The returned registry is a display-only synchronization artifact. Promote
such aliases deliberately with set_article_alias; never derive them afresh from
mutable titles. Category and issue slugs are similarly frozen by identity.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import unquote
import uuid

RESERVED = {"articles", "issues", "categories", "topics", "series", "search", "assets", "images", "feeds", "rss", "feed", "sitemap", "404", "index", "api", "downloads", "routes"}


class RouteError(ValueError):
    pass


def slugify(value: str | None, fallback: str = "article") -> str:
    """Unicode-safe slug; retain scripts rather than an invented transliteration."""
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


def _path(locale: str, record: dict) -> str:
    return f"/{_locale(locale)}/{_slug(record['category_slug'])}/{_slug(record['alias'])}/"


def _history(path: str, locale: str) -> str:
    decoded = unquote(path)
    if not path.startswith(f"/{locale}/") or not path.endswith("/") or "\\" in path or "?" in path or "#" in path or any(part in {".", ".."} for part in decoded.split("/")):
        raise RouteError(f"Unsafe redirect history: {path!r}")
    return path


def set_article_alias(registry: dict, locale: str, identity: str, alias: str, category_slug: str | None = None) -> None:
    """Explicit editorial migration; persist returned registry after validation.

    Keeps every old route (and every UUID fallback category route) as history.
    initialize_routes verifies global collisions before output can be published.
    """
    entry = registry["articles"][locale][identity]
    previous = _path(locale, entry)
    history = set(entry.get("history", []))
    history.add(previous)
    if entry.get("fallback"):
        for category in registry["categories"][locale].values():
            history.add(f"/{locale}/{category['slug']}/article-{identity}/")
    entry["alias"] = _slug(alias)
    if category_slug is not None:
        entry["category_slug"] = _slug(category_slug)
    entry["history"] = sorted(history - {_path(locale, entry)})
    entry["fallback"] = False


def initialize_routes(model: dict, locales, registry_path: Path, update: bool = False) -> dict:
    """Load registry and return routing maps, attaching paths to model articles.

    update=True is an explicit registry maintenance/bootstrap action: new articles
    receive human-readable title aliases and additions are written atomically.
    Normal update=False builds give unknown IDs stable UUID fallback aliases and
    return the full candidate registry without changing the checked-out source.
    """
    config = locales if isinstance(locales, dict) else {tag: {} for tag in locales}
    tags = list(config)
    for tag in tags:
        _locale(tag)
    if "en" not in tags:
        raise RouteError("English locale is required")
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
    result = {"categories": {}, "issues": {}, "articles": {}, "redirects": {}, "registry": registry, "pending": []}
    occupied: dict[str, tuple[str, str, str]] = {}

    def reserve(path, owner):
        # Browsers percent-encode Unicode: canonical-equivalent spellings collide.
        key = unicodedata.normalize("NFC", unquote(path)).casefold()
        if key in occupied and occupied[key] != owner:
            raise RouteError(f"Route collision: {path} ({occupied[key]} and {owner})")
        occupied[key] = owner

    def redirect(old, new, owner):
        if old == new:
            return
        reserve(old, owner)
        if old in result["redirects"] and result["redirects"][old] != new:
            raise RouteError(f"Ambiguous redirect: {old}")
        result["redirects"][old] = new

    for locale in tags:
        reserve(f"/{locale}/", ("reserved", locale, "home"))
        for reserved in RESERVED:
            reserve(f"/{locale}/{reserved}/", ("reserved", locale, reserved))
        for kind in ("categories", "issues", "articles"):
            registry.setdefault(kind, {}).setdefault(locale, {})
            result[kind][locale] = {}
        for kind in ("categories", "issues"):
            used = {entry["slug"] for entry in registry[kind][locale].values()}
            for group in sorted(model[kind], key=lambda item: item["id"]):
                identity = _uuid(group["id"])
                records = registry[kind][locale]
                if identity not in records:
                    translated = config[locale].get("categories", {}).get(identity, {}) if isinstance(config[locale], dict) and kind == "categories" else {}
                    name = translated.get("slug") or group["slug"]
                    slug = slugify(name, f"{kind[:-1]}-{identity}")
                    if kind == "categories" and slug in RESERVED:
                        slug = "category-" + slug
                    if slug in used:
                        slug += "-" + identity
                    records[identity] = {"slug": slug, "history": []}
                    used.add(slug)
                    result["pending"].append({"kind": kind, "locale": locale, "id": identity})
                entry = records[identity]
                slug = _slug(entry["slug"])
                if kind == "categories" and slug in RESERVED:
                    raise RouteError(f"Category uses reserved namespace: {slug}")
                path = f"/{locale}/" + ("issues/" if kind == "issues" else "") + slug + "/"
                owner = (kind, locale, identity)
                reserve(path, owner)
                result[kind][locale][identity] = path
                for old in entry.get("history", []):
                    redirect(_history(old, locale), path, owner)
        # Reserve all existing article aliases, including temporarily unpublished
        # articles, to prevent an old URL being reassigned to a different UUID.
        for identity, entry in registry["articles"][locale].items():
            _uuid(identity)
            owner = ("articles", locale, identity)
            reserve(_path(locale, entry), owner)
            for old in entry.get("history", []):
                reserve(_history(old, locale), owner)
        for article in sorted(model["articles"].get(locale, []), key=lambda item: item["id"]):
            identity = _uuid(article["id"])
            records = registry["articles"][locale]
            primary = article["categories"]["primary"]
            category_slug = registry["categories"][locale][primary]["slug"]
            owner = ("articles", locale, identity)
            if identity not in records:
                alias = slugify(article.get("title"), "article") if update else "article-" + identity
                path = f"/{locale}/{category_slug}/{alias}/"
                if unicodedata.normalize("NFC", path).casefold() in occupied or alias in RESERVED:
                    alias += "-" + identity
                records[identity] = {"category_id": primary, "category_slug": category_slug, "alias": alias, "history": [], "fallback": not update}
                result["pending"].append({"kind": "articles", "locale": locale, "id": identity})
            entry = records[identity]
            path = _path(locale, entry)
            reserve(path, owner)
            result["articles"][locale][identity] = path
            compatibility = f"/{locale}/articles/{identity}/"
            redirect(compatibility, path, owner)
            for old in entry.get("history", []):
                redirect(_history(old, locale), path, owner)
            if entry.get("fallback"):
                # A new English item must publish immediately. Until its record is
                # synchronized, UUID paths under every category survive moves.
                for category in registry["categories"][locale].values():
                    redirect(f"/{locale}/{category['slug']}/article-{identity}/", path, owner)
            article.update(url=path, markdown_url=f"/{locale}/articles/{identity}.md", compatibility_url=compatibility)
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
