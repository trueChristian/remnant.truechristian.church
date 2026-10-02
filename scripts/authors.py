"""Derive public author navigation from the authoritative English bylines.

An exact recorded name is the website identity. This module does not reconcile
spelling, punctuation, capitalization, initials, or historical name variants.
It never edits source bylines or interprets a raw attribution as a person.
"""
from __future__ import annotations


class AuthorError(ValueError):
    """Structured source authors cannot be represented without guessing."""


DETAIL_FIELDS = (
    "location", "role", "birth_year", "death_year", "life_dates", "age", "credentials",
)
INTEGER_FIELDS = {"birth_year", "death_year", "age"}


def build_author_index(model: dict) -> list[dict]:
    """Return exact-name authors, their distinct articles, and recorded details.

    Each record contains ``id`` and ``name`` (the unchanged recorded name),
    ``article_ids`` in English model order, and ``details`` mapping allowlisted
    fields to unique recorded values. Details are historical article metadata;
    their presence does not assert a current location, position, or age.

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
            author = authors.setdefault(name, {
                "id": name, "name": name, "article_ids": [], "details": {},
            })
            included = membership.setdefault(name, set())
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
