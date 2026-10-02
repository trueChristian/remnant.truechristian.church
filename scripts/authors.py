"""Derive public author navigation from English bylines and reviewed aliases.

Only names explicitly listed in the maintained alias file share an identity.
Unlisted names remain distinct; source bylines are never edited and raw
attributions are never interpreted as people.
"""
from __future__ import annotations

import json
from pathlib import Path
import unicodedata


class AuthorError(ValueError):
    """Structured source authors cannot be represented without guessing."""


DETAIL_FIELDS = (
    "location", "role", "birth_year", "death_year", "life_dates", "age", "credentials",
)
INTEGER_FIELDS = {"birth_year", "death_year", "age"}
DEFAULT_AUTHOR_ALIASES = Path(__file__).resolve().parents[1] / "data" / "author-aliases.json"


def _validate_alias_name(name: object) -> str:
    if (not isinstance(name, str) or not name or len(name) > 1024 or name != name.strip()
            or any(unicodedata.category(character).startswith("C") for character in name)):
        raise AuthorError(f"Invalid author alias name: {name!r}")
    return name


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuthorError(f"Duplicate key in author aliases: {key!r}")
        result[key] = value
    return result


def _validated_aliases(aliases: dict[str, str]) -> dict[str, str]:
    """Validate a flat, one-step mapping without modifying the caller's map."""
    if not isinstance(aliases, dict):
        raise AuthorError("Author aliases must be a recorded-name to canonical-name mapping")
    for recorded, canonical in aliases.items():
        _validate_alias_name(recorded)
        _validate_alias_name(canonical)
        if aliases.get(canonical, canonical) != canonical:
            raise AuthorError(f"Author alias chains or cycles are not allowed: {recorded!r} -> {canonical!r}")
    return aliases


def load_author_aliases(path: str | Path = DEFAULT_AUTHOR_ALIASES) -> dict[str, str]:
    """Load reviewed names as a flat mapping, including canonical self entries.

    The versioned JSON contains ``authors: {canonical: [exact aliases]}``.
    Duplicate JSON keys, repeated aliases, cross-group collisions and aliases
    that are another group's canonical name fail the build. This makes future
    editorial additions reviewable without introducing fuzzy name matching.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuthorError(f"Cannot read author aliases from {path}: {error}") from error
    if not isinstance(data, dict) or set(data) != {"version", "authors"}:
        raise AuthorError("Author aliases must contain only version and authors")
    if type(data["version"]) is not int or data["version"] != 1:
        raise AuthorError("Unsupported author aliases version; expected 1")
    groups = data["authors"]
    if not isinstance(groups, dict):
        raise AuthorError("Author aliases authors must be an object")
    aliases = {_validate_alias_name(name): name for name in groups}
    for canonical, recorded_names in groups.items():
        if not isinstance(recorded_names, list):
            raise AuthorError(f"Author aliases for {canonical!r} must be a list")
        for recorded in recorded_names:
            _validate_alias_name(recorded)
            if recorded in aliases:
                raise AuthorError(f"Duplicate or conflicting author alias: {recorded!r}")
            aliases[recorded] = canonical
    return aliases


def canonical_author_name(name: str, aliases: dict[str, str] | None = None) -> str:
    """Resolve one exact recorded name; an unlisted name stays unchanged."""
    if not isinstance(name, str) or not name.strip():
        raise AuthorError("Author name must be nonempty text")
    resolved = load_author_aliases() if aliases is None else _validated_aliases(aliases)
    return resolved.get(name, name)


def build_author_index(model: dict, aliases: dict[str, str] | None = None) -> list[dict]:
    """Return canonical authors, their distinct articles, and recorded details.

    Each record contains canonical ``id`` and ``name``, observed ``source_names``
    preserving exact English spellings, ``article_ids`` in English model order,
    and ``details`` mapping allowlisted fields to unique recorded values across
    aliases. Details are historical article metadata; their presence does not
    assert a current location, position, or age. Passing an empty aliases map
    explicitly disables grouping, which is useful when auditing source names.

    Only English source metadata establishes membership. Translations neither
    add authors nor increase counts. The caller filters article IDs for each
    language's availability and constructs its own routes and presentation.
    Absent bylines and raw strings yield no authors. Malformed structured
    authors fail with article context rather than silently dropping a credit.
    """
    if not isinstance(model, dict) or not isinstance(model.get("articles"), dict):
        raise AuthorError("Author index requires an English article collection")
    articles = model["articles"].get("en")
    if not isinstance(articles, list):
        raise AuthorError("Author index requires an English article list")
    aliases = load_author_aliases() if aliases is None else _validated_aliases(aliases)

    authors: dict[str, dict] = {}
    membership: dict[str, set[str]] = {}
    for article in articles:
        if not isinstance(article, dict):
            raise AuthorError("Invalid English article in author index")
        identity = article.get("id")
        if not isinstance(identity, str) or not identity.strip():
            raise AuthorError("Author index article has no identity")
        source = article.get("source_metadata", article)
        if not isinstance(source, dict):
            raise AuthorError(f"Invalid English source metadata for article {identity}")
        byline = source.get("byline")
        if byline is None or isinstance(byline, str):
            continue
        if not isinstance(byline, dict):
            raise AuthorError(f"Invalid byline for article {identity}: expected an object or raw text")
        recorded = byline.get("authors", [])
        if not isinstance(recorded, list):
            raise AuthorError(f"Invalid authors for article {identity}: expected a list")

        for position, person in enumerate(recorded, start=1):
            context = f"article {identity}, author {position}"
            if not isinstance(person, dict):
                raise AuthorError(f"Invalid structured author in {context}: expected an object")
            name = person.get("name")
            if not isinstance(name, str) or not name.strip():
                raise AuthorError(f"Invalid author name in {context}: expected nonempty text")
            canonical = aliases.get(name, name)
            author = authors.setdefault(canonical, {
                "id": canonical, "name": canonical, "source_names": [], "article_ids": [], "details": {},
            })
            if name not in author["source_names"]:
                author["source_names"].append(name)
            included = membership.setdefault(canonical, set())
            if identity not in included:
                author["article_ids"].append(identity)
                included.add(identity)
            for field in DETAIL_FIELDS:
                value = person.get(field)
                if value is None:
                    continue
                expected = int if field in INTEGER_FIELDS else str
                if type(value) is not expected:
                    raise AuthorError(f"Invalid author {field} in {context}: expected {expected.__name__}")
                if isinstance(value, str) and not value.strip():
                    continue
                values = author["details"].setdefault(field, [])
                if value not in values:
                    values.append(value)

    return [authors[name] for name in sorted(authors, key=lambda value: (value.casefold(), value))]
