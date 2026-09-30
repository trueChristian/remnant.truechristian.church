"""Read only the supported, checksum-verified public display exports.

English is authoritative. A missing/invalid translation bundle degrades explicitly
and never permits an older translation bundle to accompany newer English.
"""
from __future__ import annotations

import copy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any
import uuid


class ContentError(ValueError):
    """An input display export is invalid or cannot safely be published."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContentError(message)


def _read_json(path: Path) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, f"Duplicate JSON key in {path.name}: {key}")
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, ValueError) as error:
        raise ContentError(f"Cannot read {path.name}: {error}") from error


def _file(root: Path, relative: str) -> Path:
    _require(isinstance(relative, str) and bool(relative), "Missing exported path")
    _require(not relative.startswith("/") and "\\" not in relative, f"Unsafe exported path: {relative}")
    _require(all(part not in {"", ".", ".."} for part in relative.split("/")), f"Unsafe exported path: {relative}")
    path = root
    for part in relative.split("/"):
        path /= part
        _require(not path.is_symlink(), f"Exported symlinks are forbidden: {relative}")
    _require(path.is_file(), f"Missing exported file: {relative}")
    return path


def _identity(value: Any) -> str:
    try:
        _require(isinstance(value, str) and str(uuid.UUID(value)) == value, f"Invalid UUID: {value}")
    except (ValueError, AttributeError) as error:
        raise ContentError(f"Invalid UUID: {value}") from error
    return value


def _verify_bundle(root: Path, version: str) -> dict:
    _require(not root.is_symlink(), "Export root cannot be a symlink")
    manifest = _read_json(root / "manifest.json")
    _require(manifest.get("format_version") == version, "Unsupported export format")
    _require(manifest.get("base_path") == "/", "The custom-domain website requires root-base exports")
    _require(bool(re.fullmatch(r"[a-f0-9]{40}", manifest.get("source_revision", ""))), "Missing exact English revision")
    files = manifest.get("files")
    _require(isinstance(files, dict) and "index.json" in files, "Missing export file inventory")
    for relative, expected in files.items():
        actual = hashlib.sha256(_file(root, relative).read_bytes()).hexdigest()
        _require(actual == expected, f"Export checksum mismatch: {relative}")
    return manifest


class FragmentText(HTMLParser):
    """Collect display text and image/caption metadata without reserializing HTML."""
    BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "div", "section", "article", "figure", "figcaption", "br", "td", "th", "tr", "dt", "dd", "aside", "footer"}
    VOID = {"br", "img", "hr", "wbr", "area", "base", "col", "embed", "input", "link", "meta", "param", "source", "track"}

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.article_ids: list[str | None] = []
        self.images: list[dict] = []
        self.notice_count = 0
        self.notice_depth = 0
        self.stack: list[str] = []
        self.figure_images: list[dict] | None = None
        self.caption_parts: list[str] | None = None
        self.figure_caption: str | None = None
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        _require(tag not in {"script", "iframe", "object", "embed", "style", "form", "input", "button"}, f"Unsafe exported HTML element: {tag}")
        _require(not any(key.startswith("on") for key in attributes), "Active HTML attribute in export")
        if tag == "article":
            self.article_ids.append(attributes.get("data-article-id"))
        if tag == "aside" and attributes.get("data-translation-notice") == "ai":
            self.notice_count += 1
            self.notice_depth = len(self.stack) + 1
        if not self.notice_depth:
            if tag in self.BLOCK:
                self.parts.append("\n")
            if tag == "figure":
                self.figure_images = []
                self.figure_caption = None
            if tag == "figcaption":
                self.caption_parts = []
            if tag == "img":
                item = {"public_path": attributes.get("src"), "alt": attributes.get("alt", "")}
                self.images.append(item)
                if self.figure_images is not None:
                    self.figure_images.append(item)
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "figcaption" and self.caption_parts is not None:
            self.figure_caption = re.sub(r"\s+", " ", "".join(self.caption_parts)).strip()
            self.caption_parts = None
        if tag == "figure" and self.figure_images is not None:
            for image in self.figure_images:
                image["caption"] = self.figure_caption
            self.figure_images = None
        if not self.notice_depth and tag in self.BLOCK:
            self.parts.append("\n")
        if self.notice_depth and len(self.stack) == self.notice_depth:
            self.notice_depth = 0
        if self.stack:
            _require(self.stack[-1] == tag, f"Mismatched exported HTML: {tag}")
            self.stack.pop()

    def handle_data(self, data):
        if not self.notice_depth:
            self.parts.append(data)
            if self.caption_parts is not None:
                self.caption_parts.append(data)

    @property
    def text(self):
        return "\n".join(re.sub(r"[\t \r\f\v]+", " ", line).strip() for line in "".join(self.parts).split("\n") if line.strip())


def excerpt(text: str, limit: int = 220) -> str:
    """A verbatim prefix, never a generated paraphrase."""
    flat = re.sub(r"\s+", " ", text).strip()
    if len(flat) <= limit:
        return flat
    cut = flat.rfind(" ", 0, limit + 1)
    if cut < limit // 2:  # Unsegmented CJK and very long words.
        cut = limit
    return flat[:cut].rstrip() + "…"


def _normalize(source: dict, html: str, locale: str, root: Path, translation: dict | None = None) -> dict:
    article = copy.deepcopy(source)
    article["html_source"] = copy.deepcopy(article.get("html"))
    article["locale"] = locale
    article["html"] = html
    article["source_metadata"] = copy.deepcopy(source)
    parsed = FragmentText(html)
    _require(not parsed.stack, "Unclosed exported HTML")
    _require(parsed.article_ids == [article["id"]], f"Article identity mismatch: {article['id']}")
    article["text"] = parsed.text
    article["excerpt"] = excerpt(parsed.text)
    original_images = {image["public_path"]: image for image in source.get("images", [])}
    _require(set(original_images) == {image["public_path"] for image in parsed.images}, "Exported HTML image inventory mismatch")
    article["images"] = []
    for display in parsed.images:
        item = copy.deepcopy(original_images[display["public_path"]])
        item.update(display)  # Localized HTML caption/alt; retain source credit.
        article["images"].append(item)
    article["image"] = article["images"][0] if article["images"] else None
    article["translation"] = copy.deepcopy(translation)
    if translation:
        for name in ("title", "subtitle", "section"):
            article[name] = translation[name]
        article["language"] = locale
        article["direction"] = translation["direction"]
        article["human_reviewed"] = translation["human_reviewed"]
        article["ai_notice_required"] = translation["ai_notice_required"]
        _require(parsed.notice_count == int(bool(article["ai_notice_required"])), "Translation AI notice is missing or disagrees with export metadata")
        _require(article["human_reviewed"] != article["ai_notice_required"], "Invalid translation review/notice state")
    else:
        article.update(direction="ltr", human_reviewed=True, ai_notice_required=False)
        _require(parsed.notice_count == 0, "Unexpected AI notice in English")
    return article


def ordered_issues(model: dict) -> list[dict]:
    """Newest bibliographic year/period first, catalogue order for ties.

    Season ordinals are sorting keys, NOT asserted publication dates. A year-only
    issue has unknown within-year order and follows finer-grained issues. Date
    objects and their precision are never altered and no date is synthesized.
    """
    seasons = {"winter": 1, "spring": 4, "summer": 7, "fall": 10, "autumn": 10}
    def key(item):
        index, issue = item
        date = issue.get("date", {})
        months = date.get("months") or []
        period = max(months) if months else date.get("month") or seasons.get(str(date.get("season", "")).lower(), 0)
        return (-int(date.get("year") or 0), -int(period), index)
    return [issue for _, issue in sorted(enumerate(model["issues"]), key=key)]


def load_content(english_export: Path, translation_export: Path | None = None, *, strict_translations: bool = False) -> dict:
    root = Path(english_export)
    manifest = _verify_bundle(root, "2.0")
    index = _read_json(root / "index.json")
    catalogue = _read_json(root / "catalogue.json")
    _require(index.get("format_version") == "2.0" and catalogue.get("format_version") == "2.0", "Unsupported English content format")
    _require(index.get("export", {}).get("source_revision") == manifest["source_revision"], "English revision mismatch")
    _require("skipped" not in index and "review_candidates" not in catalogue, "Input is not a display export")
    model = {kind: copy.deepcopy(catalogue[kind]) for kind in ("issues", "categories", "topics", "series")}
    groups = {kind: {_identity(item["id"]): item for item in model[kind]} for kind in model}
    for kind in groups:
        _require(len(groups[kind]) == len(model[kind]), f"Duplicate {kind} identity")
    model.update(articles={"en": []}, warnings=[], translation_status="unavailable", english_export=root,
                 source_revision=manifest["source_revision"], translation_revision=None,
                 source_repository=manifest.get("source_repository"), translation_omissions=[])
    english_by_id = {}
    for item in index["articles"]:
        identity = _identity(item["id"])
        _require(identity not in english_by_id, f"Duplicate article identity: {identity}")
        _require(item["issue_id"] in groups["issues"], "Unknown article issue")
        _require(item["categories"]["primary"] in groups["categories"], "Unknown primary category")
        _require(all(c in groups["categories"] for c in item["categories"].get("additional", [])), "Unknown additional category")
        _require(all(t in groups["topics"] for t in item.get("topics", [])), "Unknown article topic")
        if item.get("series"):
            _require(item["series"]["id"] in groups["series"], "Unknown article series")
        _require(isinstance(item["sequence"], int), "Invalid article sequence")
        article = _normalize(item, _file(root, item["html"]["repository_path"]).read_text(encoding="utf-8"), "en", root)
        article["issue"] = copy.deepcopy(groups["issues"][item["issue_id"]])
        article["source_revision"] = manifest["source_revision"]
        english_by_id[identity] = article
        model["articles"]["en"].append(article)
    _require(len(english_by_id) == manifest["counts"]["articles"], "English article count mismatch")
    if translation_export is None or not Path(translation_export).exists():
        model["warnings"].append("Translations unavailable: publishing the current English export only; no previous translations reused.")
    else:
        try:
            translated, metadata = _load_translations(Path(translation_export), model, english_by_id)
            model["articles"].update(translated)
            model.update(metadata)
        except (ContentError, OSError, KeyError, TypeError, ValueError) as error:
            if strict_translations:
                raise ContentError(f"Translation export rejected: {error}") from error
            model["translation_status"] = "failed"
            model["warnings"].append(f"Translation export rejected; English-only build, no stale reuse: {error}")
    order = {issue["id"]: position for position, issue in enumerate(ordered_issues(model))}
    for articles in model["articles"].values():
        articles.sort(key=lambda item: (order[item["issue_id"]], item["sequence"], item["id"]))
    return model


def _load_translations(root: Path, model: dict, english_by_id: dict) -> tuple[dict, dict]:
    manifest = _verify_bundle(root, "1.0")
    index = _read_json(root / "index.json")
    _require(manifest["source_revision"] == index.get("source_revision") == model["source_revision"], "Translations were not exported against the selected English checkout")
    revision = manifest.get("translation_revision", "")
    _require(bool(re.fullmatch(r"[a-f0-9]{40}", revision)) and revision == index.get("translation_revision"), "Translation revision mismatch")
    _require(index.get("format_version") == "1.0", "Unsupported translation index")
    result: dict[str, list] = {}
    seen = set()
    for item in index["articles"]:
        identity = _identity(item["id"])
        locale = item["language_tag"]
        _require(bool(re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", locale)) and locale != "en", "Invalid translation locale")
        _require((locale, identity) not in seen, "Duplicate translation")
        seen.add((locale, identity))
        _require(identity in english_by_id, "Translation refers to a removed English article")
        _require(item.get("status") == "ready", "Unpublished translation in display export")
        source = english_by_id[identity]["source_metadata"]
        _require(item["issue_id"] == source["issue_id"], "Translation issue mismatch")
        sidecar = _read_json(_file(root, item["metadata"]))
        _require(set(sidecar) == {"title", "subtitle", "section"}, "Unexpected translated metadata")
        _require(all(sidecar[k] == item[k] for k in sidecar), "Translated sidecar/index mismatch")
        html = _file(root, item["html"]).read_text(encoding="utf-8")
        _require(hashlib.sha256(html.encode()).hexdigest() == item["html_sha256"], "Translated HTML fingerprint mismatch")
        article = _normalize(source, html, locale, root, item)
        article["issue"] = copy.deepcopy(english_by_id[identity]["issue"])
        article["source_revision"] = model["source_revision"]
        result.setdefault(locale, []).append(article)
    _require(len(seen) == manifest["article_count"], "Translation count mismatch")
    return result, {"translation_status": "ready", "translation_revision": revision, "translation_omissions": copy.deepcopy(manifest.get("omitted", []))}
