"""Completeness, script, route-input and honest-date tests for every locale."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from i18n import LOCALE_META, UI_KEYS, format_issue_date, load_locales, validate_locales


class LocaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.locales = load_locales(ROOT / "locales")

    def modified(self):
        return copy.deepcopy(self.locales)

    def test_all_configured_locales_and_complete_keysets(self):
        self.assertEqual(set(self.locales), set(LOCALE_META))
        validate_locales(self.locales)
        for locale in self.locales.values():
            self.assertEqual(set(locale["ui"]), UI_KEYS)
            self.assertEqual(set(locale["categories"]), set(self.locales["en"]["categories"]))
            self.assertEqual(set(locale["chrome"]), set(self.locales["en"]["chrome"]))

    def test_upstream_registry_comparison(self):
        registry = {code: {"tag": tag, "native_name": native, "dir": direction}
                    for tag, (code, native, direction) in LOCALE_META.items() if tag != "en"}
        validate_locales(self.locales, registry=registry)
        registry["jpn"] = {"tag": "ja", "native_name": "日本語", "dir": "ltr"}
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            validate_locales(self.locales, registry=registry)

    def test_new_source_category_requires_every_locale(self):
        categories = [{"id": cid} for cid in self.locales["en"]["categories"]]
        categories.append({"id": "00000000-0000-4000-8000-000000000001"})
        with self.assertRaisesRegex(ValueError, "categories: missing"):
            validate_locales(self.locales, categories=categories)

    def test_missing_locale_is_not_silently_english(self):
        locales = self.modified()
        del locales["fr"]
        with self.assertRaisesRegex(ValueError, "missing=.*fr"):
            validate_locales(locales)

    def test_missing_ui_even_in_english_fails(self):
        locales = self.modified()
        del locales["en"]["ui"]["copy_markdown"]
        with self.assertRaisesRegex(ValueError, "copy_markdown"):
            validate_locales(locales)

    def test_inconsistent_placeholder_fails(self):
        locales = self.modified()
        locales["fr"]["ui"]["article_count"] = "Articles : {total}"
        with self.assertRaisesRegex(ValueError, "placeholders differ"):
            validate_locales(locales)

    def test_placeholder_access_expression_is_rejected(self):
        locales = self.modified()
        locales["fr"]["ui"]["article_count"] = "Articles : {count.__class__}"
        with self.assertRaisesRegex(ValueError, "Unsupported placeholder"):
            validate_locales(locales)

    def test_rtl_and_native_names_match_registry(self):
        self.assertEqual({tag for tag, locale in self.locales.items() if locale["meta"]["dir"] == "rtl"}, {"ar", "he", "ur"})
        locales = self.modified()
        locales["ar"]["meta"]["dir"] = "ltr"
        with self.assertRaisesRegex(ValueError, "metadata"):
            validate_locales(locales)

    def test_script_and_english_fallback_checks(self):
        locales = self.modified()
        locales["hi"]["ui"]["intro"] = "A transliterated placeholder."
        with self.assertRaisesRegex(ValueError, "expected script"):
            validate_locales(locales)
        locales = self.modified()
        category_id = next(iter(locales["fr"]["categories"]))
        locales["fr"]["categories"][category_id]["description"] = locales["en"]["categories"][category_id]["description"]
        with self.assertRaisesRegex(ValueError, "untranslated description"):
            validate_locales(locales)

    def test_descriptions_are_specific_and_distinct(self):
        for locale in self.locales.values():
            descriptions = [c["description"] for c in locale["categories"].values()]
            self.assertEqual(len(descriptions), len(set(descriptions)))
            self.assertTrue(all(len(text) >= 15 for text in descriptions))

    def test_slug_path_traversal_reserved_namespace_and_collision(self):
        for invalid in ("../escape", "articles", "a/b", "a%2fb", "-bad", "bad--slug"):
            locales = self.modified()
            category_id = next(iter(locales["en"]["categories"]))
            locales["en"]["categories"][category_id]["slug"] = invalid
            with self.assertRaisesRegex(ValueError, "slug"):
                validate_locales(locales)
        locales = self.modified()
        categories = list(locales["fr"]["categories"].values())
        categories[1]["slug"] = categories[0]["slug"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_locales(locales)

    def test_brands_do_not_get_translated(self):
        locales = self.modified()
        locales["fr"]["chrome"]["GETBIBLE"] = "PRENEZLABIBLE"
        with self.assertRaisesRegex(ValueError, "proper brand"):
            validate_locales(locales)

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "en.json").write_text('{"meta":{}, "meta":{}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                load_locales(directory)

    def test_filename_must_match_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "fr.json").write_text(json.dumps(self.locales["en"]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "filename must equal"):
                load_locales(directory)

    def test_seasons_never_become_invented_dates(self):
        date = {"label": "Summer 2024", "year": 2024, "season": "Summer", "precision": "season"}
        self.assertEqual(format_issue_date(date, self.locales["en"]), "Summer 2024")
        self.assertEqual(format_issue_date({"date": date}, self.locales["fr"]), "Été 2024")
        for locale in self.locales.values():
            result = format_issue_date(date, locale)
            self.assertIn(locale["seasons"]["Summer"], result)
            self.assertIn("2024", result)
            self.assertNotIn("01", result)

    def test_cjk_year_first(self):
        date = {"year": 2024, "season": "Summer", "precision": "season"}
        self.assertTrue(format_issue_date(date, self.locales["zh-Hans"]).startswith("2024年"))
        self.assertTrue(format_issue_date(date, self.locales["ko"]).startswith("2024년"))

    def test_month_range_keeps_all_recorded_months_without_day(self):
        date = {"year": 2013, "months": [7, 8], "precision": "month_range"}
        self.assertEqual(format_issue_date(date, self.locales["fr"]), "juillet/août 2013")
        self.assertEqual(format_issue_date(date, self.locales["en"]), "July/August 2013")
        date["months"] = [10, 11, 12]
        self.assertEqual(format_issue_date(date, self.locales["en"]), "October/November/December 2013")

    def test_year_special_edition_localized_without_added_precision(self):
        for label in ("2007 Special Edition", "Special Edition 2007"):
            for locale in self.locales.values():
                result = format_issue_date({"label": label, "year": 2007, "precision": "year"}, locale)
                self.assertIn(locale["ui"]["special_edition"], result)
                self.assertIn("2007", result)
                self.assertNotIn("01", result)
        self.assertEqual(format_issue_date({"year": 2007, "precision": "year"}, self.locales["en"]), "2007")

    def test_unknown_date_qualifier_is_not_silently_discarded(self):
        date = {"label": "2007 Commemorative Edition", "year": 2007, "precision": "year"}
        self.assertEqual(format_issue_date(date, self.locales["fr"]), date["label"])
        self.assertEqual(format_issue_date({}, self.locales["fr"]), self.locales["fr"]["ui"]["undated_issue"])

    def test_exact_day_used_only_if_recorded(self):
        date = {"year": 2024, "month": 7, "day": 8, "precision": "day"}
        self.assertEqual(format_issue_date(date, self.locales["en"]), "July 8, 2024")
        date["precision"] = "month"
        self.assertEqual(format_issue_date(date, self.locales["en"]), "July 2024")


if __name__ == "__main__":
    unittest.main()
