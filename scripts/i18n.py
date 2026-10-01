"""Website-owned, complete locale dictionaries and precision-preserving issue dates.

No text is translated at build time. Source publication text/notices are never
rewritten here. Locale category slugs are persistent inputs to the route registry.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from string import Formatter
from typing import Any, Mapping
import unicodedata
import uuid

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = {"meta", "ui", "categories", "seasons", "months", "chrome"}
UI_KEYS = frozenset('''home articles categories issues search language menu close theme system light dark kicker intro latest_articles latest_issue featured_archive browse_archive browse_categories read_article read_issue all_articles all_issues article_count issue_count topic no_articles_title coming_soon read_english available_languages missing_translation search_placeholder search_hint searching results_count no_results search_error clear all_categories all_issue_filter citation original_issue source_pages author reading_time minutes download_markdown copy_markdown copied copy_fallback prev next pause play breadcrumbs back to_top skip_content subscribe_rss about_archive archive_intro category_intro issue_intro magazine issue volume number untitled_article undated_issue no_issues_title not_found_title not_found_body return_home language_notice english_authoritative cover_placeholder source_pdf related_articles filters apply_filters publication_date translation_status main_navigation footer_navigation social_links copy_error special_edition publisher download pause_updates resume_updates'''.split())
# The upstream registry is separately compared in integration builds. Keeping the
# approved inventory here also makes standalone validation independent of clones.
LOCALE_META = {
    "en": ("eng", "English", "ltr"), "zh-Hans": ("cmn", "简体中文", "ltr"),
    "hi": ("hin", "हिन्दी", "ltr"), "es": ("spa", "Español", "ltr"),
    "ar": ("ara", "العربية", "rtl"), "fr": ("fra", "Français", "ltr"),
    "bn": ("ben", "বাংলা", "ltr"), "pt": ("por", "Português", "ltr"),
    "id": ("ind", "Bahasa Indonesia", "ltr"), "ur": ("urd", "اردو", "rtl"),
    "ru": ("rus", "Русский", "ltr"), "de": ("deu", "Deutsch", "ltr"),
    "nl": ("nld", "Nederlands", "ltr"), "af": ("afr", "Afrikaans", "ltr"),
    "sw": ("swa", "Kiswahili", "ltr"), "ko": ("kor", "한국어", "ltr"),
    "it": ("ita", "Italiano", "ltr"), "he": ("heb", "עברית", "rtl"),
    "el": ("ell", "Ελληνικά", "ltr"), "sv": ("swe", "Svenska", "ltr"),
    "nb": ("nob", "Norsk bokmål", "ltr"),
}
SCRIPT_RANGES = {
    "zh-Hans": ((0x3400, 0x9FFF),), "ko": ((0xAC00, 0xD7AF), (0x1100, 0x11FF)),
    "hi": ((0x0900, 0x097F),), "bn": ((0x0980, 0x09FF),),
    "ar": ((0x0600, 0x06FF),), "ur": ((0x0600, 0x06FF),),
    "he": ((0x0590, 0x05FF),), "ru": ((0x0400, 0x04FF),),
    "el": ((0x0370, 0x03FF), (0x1F00, 0x1FFF)),
}
BRANDS = ("GETBIBLE", "Loudvoice", "SHE Cares", "Amana", "Telegram", "GitHub")
RESERVED_SLUGS = {"articles", "categories", "issues", "search", "assets", "markdown", "missing", "404", "feed.xml", "index.html"}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)


def load_locales(path: str | Path = ROOT / "locales") -> dict[str, dict[str, Any]]:
    """Read and validate all locale files; return a BCP-47-tag-keyed mapping."""
    result = {}
    for file in sorted(Path(path).glob("*.json")):
        locale = _read_json(file)
        tag = locale.get("meta", {}).get("tag")
        if not tag or tag != file.stem:
            raise ValueError(f"{file}: filename must equal meta.tag")
        if tag in result:
            raise ValueError(f"Duplicate locale tag: {tag}")
        result[tag] = locale
    validate_locales(result)
    return result


def _placeholders(value: str) -> set[str]:
    fields = set()
    for _, field, spec, conversion in Formatter().parse(value):
        if field is not None:
            if not re.fullmatch(r"[a-z_]+", field) or spec or conversion:
                raise ValueError(f"Unsupported placeholder: {field!r}")
            fields.add(field)
    return fields


def _chrome_labels(value: Any) -> set[str]:
    labels = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in {"label", "subtitle", "prefix"} and isinstance(child, str):
                labels.add(child)
            else:
                labels.update(_chrome_labels(child))
    elif isinstance(value, list):
        for child in value:
            labels.update(_chrome_labels(child))
    return labels


def _has_script(value: str, tag: str) -> bool:
    return any(start <= ord(char) <= end for char in value for start, end in SCRIPT_RANGES[tag])


def validate_locales(locales: Mapping[str, Any], registry: Mapping[str, Any] | None = None,
                     categories: Any = None, chrome: Any = None) -> None:
    """Fail closed on incomplete/mismatched locale data, without English fallback.

    Optional inputs are the upstream language registry, catalogue categories (or
    complete catalogue), and theme site-chrome document. Returns None on success;
    raises ValueError containing all detected validation errors otherwise.
    """
    errors = []
    expected_tags = set(LOCALE_META)
    if registry is not None:
        configured_tags = {value["tag"] for value in registry.values()} | {"en"}
        if configured_tags != expected_tags:
            errors.append(f"Upstream language inventory changed: {sorted(configured_tags ^ expected_tags)}")
    if set(locales) != expected_tags:
        errors.append(f"Locale inventory differs: missing={sorted(expected_tags - set(locales))}, extra={sorted(set(locales) - expected_tags)}")
    english = locales.get("en", {})
    if not isinstance(english, Mapping):
        raise ValueError("English locale must be an object")
    category_ids = set(english.get("categories", {}))
    if categories is not None:
        if isinstance(categories, Mapping) and "categories" in categories:
            categories = categories["categories"]
        category_ids = set(categories) if isinstance(categories, Mapping) else {item["id"] for item in categories}
    if not category_ids:
        errors.append("At least one category is required")
    chrome_keys = _chrome_labels(chrome) if chrome is not None else set(english.get("chrome", {}))
    if not chrome_keys:
        errors.append("Global chrome labels are required")
    expected_keys = {"ui": UI_KEYS, "categories": category_ids, "chrome": chrome_keys,
                     "months": {str(i) for i in range(1, 13)},
                     "seasons": {"Summer", "Spring", "Winter", "Autumn", "Fall"}}
    for tag, locale in locales.items():
        if not isinstance(locale, Mapping):
            errors.append(f"{tag}: locale must be an object")
            continue
        if set(locale) != SECTIONS:
            errors.append(f"{tag}: expected sections {sorted(SECTIONS)}")
        meta = locale.get("meta", {})
        if not isinstance(meta, Mapping) or set(meta) != {"tag", "native_name", "dir", "code"}:
            errors.append(f"{tag}: invalid metadata shape")
        elif tag in LOCALE_META:
            code, native, direction = LOCALE_META[tag]
            if meta != {"tag": tag, "native_name": native, "dir": direction, "code": code}:
                errors.append(f"{tag}: metadata does not match the approved registry")
            if registry is not None and tag != "en":
                actual = registry.get(code, {})
                if any(meta[key] != actual.get(key) for key in ("tag", "native_name", "dir")):
                    errors.append(f"{tag}: upstream metadata changed")
        for section, keys in expected_keys.items():
            block = locale.get(section, {})
            if not isinstance(block, Mapping):
                errors.append(f"{tag}.{section}: must be an object")
                continue
            if set(block) != keys:
                errors.append(f"{tag}.{section}: missing={sorted(keys-set(block))}, extra={sorted(set(block)-keys)}")
            if section == "categories":
                continue
            for key, value in block.items():
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{tag}.{section}.{key}: empty or non-text value")
                    continue
                if "\ufffd" in value or any(unicodedata.category(c) == "Cc" for c in value):
                    errors.append(f"{tag}.{section}.{key}: invalid control/replacement character")
                original = english.get(section, {}).get(key)
                if isinstance(original, str):
                    try:
                        if _placeholders(value) != _placeholders(original):
                            errors.append(f"{tag}.{section}.{key}: placeholders differ from English")
                        if section == "ui":
                            required_fields = {"count"} if key in {"article_count", "issue_count", "results_count", "minutes"} else set()
                            if _placeholders(value) != required_fields:
                                errors.append(f"{tag}.{section}.{key}: unexpected or missing required placeholders")
                    except ValueError as exc:
                        errors.append(f"{tag}.{section}.{key}: {exc}")
        seen_slugs = set()
        descriptions = []
        category_block = locale.get("categories", {})
        for cid, category in (category_block.items() if isinstance(category_block, Mapping) else []):
            try:
                uuid.UUID(cid)
            except (ValueError, AttributeError):
                errors.append(f"{tag}: invalid category UUID {cid!r}")
            if not isinstance(category, Mapping) or set(category) != {"name", "description", "slug"}:
                errors.append(f"{tag}.categories.{cid}: invalid shape")
                continue
            if any(not isinstance(v, str) or not v.strip() for v in category.values()):
                errors.append(f"{tag}.categories.{cid}: empty or non-text value")
                continue
            description, slug = category["description"], category["slug"]
            descriptions.append(description)
            if len(description) < 15:
                errors.append(f"{tag}.categories.{cid}: description is not substantive")
            if tag != "en" and description == english.get("categories", {}).get(cid, {}).get("description"):
                errors.append(f"{tag}.categories.{cid}: untranslated description")
            if (slug in RESERVED_SLUGS or slug in seen_slugs or slug != unicodedata.normalize("NFC", slug)
                    or slug.startswith("-") or slug.endswith("-") or "--" in slug
                    or not all(c == "-" or unicodedata.category(c)[0] in "LMN" for c in slug)):
                errors.append(f"{tag}.categories.{cid}: unsafe, reserved, duplicate, or non-NFC slug {slug!r}")
            seen_slugs.add(slug)
            if tag in SCRIPT_RANGES and any(not _has_script(category[k], tag) for k in ("name", "description")):
                errors.append(f"{tag}.categories.{cid}: expected script missing")
        if len(descriptions) != len(set(descriptions)):
            errors.append(f"{tag}: duplicate category descriptions")
        for key in ("intro", "coming_soon", "missing_translation", "archive_intro", "category_intro", "issue_intro"):
            text = locale.get("ui", {}).get(key, "")
            if tag != "en" and text == english.get("ui", {}).get(key):
                errors.append(f"{tag}.ui.{key}: untranslated English fallback")
            if tag in SCRIPT_RANGES and isinstance(text, str) and not _has_script(text, tag):
                errors.append(f"{tag}.ui.{key}: expected script missing")
        for brand in BRANDS:
            if locale.get("chrome", {}).get(brand) != brand:
                errors.append(f"{tag}.chrome.{brand}: proper brand name changed")
        if "The Heartbeat of the Remnant" not in locale.get("ui", {}).get("intro", ""):
            errors.append(f"{tag}.ui.intro: magazine brand name must remain unchanged")
    if errors:
        raise ValueError("Locale validation failed:\n" + "\n".join(errors))


def format_issue_date(issue_or_date: Mapping[str, Any], locale: Mapping[str, Any]) -> str:
    """Localize only recorded date precision; never synthesize a month or day.

    Catalogue labels are retained for unknown forms, so new editorial qualifiers
    are not silently lost. Known 'Special Edition' labels have a localized label.
    Seasonal names describe the original edition; hemispheres are not inferred.
    """
    date = issue_or_date.get("date", issue_or_date)
    if not isinstance(date, Mapping):
        return locale["ui"]["undated_issue"]
    year = date.get("year")
    label = str(date.get("label") or "").strip()
    precision = date.get("precision")
    if year is None:
        return label or locale["ui"]["undated_issue"]
    year = str(year)
    tag = locale["meta"]["tag"]
    year_label = year + ("年" if tag == "zh-Hans" else "년" if tag == "ko" else "")
    def with_year(text: str) -> str:
        return f"{year_label} {text}" if tag in {"zh-Hans", "ko"} else f"{text} {year_label}"
    if precision == "season" and date.get("season") in locale["seasons"]:
        return with_year(locale["seasons"][date["season"]])
    if precision in {"month", "month_range", "day"}:
        months = date.get("months")
        if months is None and date.get("month") is not None:
            months = [date["month"]]
        if isinstance(months, list) and months and all(str(m) in locale["months"] for m in months):
            month_text = "/".join(locale["months"][str(m)] for m in months)
            if precision == "day" and date.get("day") is not None and len(months) == 1:
                day = str(date["day"])
                if tag == "zh-Hans":
                    return f"{year_label}{month_text}{day}日"
                if tag == "ko":
                    return f"{year_label} {month_text} {day}일"
                if tag == "en":
                    return f"{month_text} {day}, {year}"
                # Neutral numeric display avoids incorrect inflection of localized
                # month names in languages with grammatical date cases.
                return f"{day.zfill(2)}.{str(months[0]).zfill(2)}.{year}"
            return with_year(month_text)
    if precision == "year":
        if re.fullmatch(r"(?:Special Edition\s+" + re.escape(year) + r"|" + re.escape(year) + r"\s+Special Edition)", label, re.I):
            return with_year(locale["ui"]["special_edition"])
        return label if label and label != year else year_label
    return label or year_label


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locales", type=Path, default=ROOT / "locales")
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--catalogue", type=Path)
    parser.add_argument("--chrome", type=Path)
    args = parser.parse_args()
    locales = load_locales(args.locales)
    validate_locales(locales, *(_read_json(path) if path else None for path in (args.registry, args.catalogue, args.chrome)))
    print(f"Validated {len(locales)} complete locales, {len(locales['en']['ui'])} UI keys, and {len(locales['en']['categories'])} categories per locale")


if __name__ == "__main__":
    main()
