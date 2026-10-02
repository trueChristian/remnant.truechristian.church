import copy
import unittest

from scripts.authors import AuthorError, build_author_index


def article(identity, *authors, raw=None):
    return {"id": identity, "byline": {"raw": raw, "authors": list(authors)}}


class AuthorIndexTests(unittest.TestCase):
    def test_exact_recorded_names_remain_distinct_and_sorted(self):
        names = ["Joel Hostetler", "Joel A. Hostetler", "joel Hostetler", "Joel A Hostetler", " Joel Hostetler "]
        model = {"articles": {"en": [article(str(number), {"name": name}) for number, name in enumerate(names)]}}
        result = build_author_index(model)
        self.assertEqual([item["name"] for item in result], sorted(names, key=lambda value: (value.casefold(), value)))
        self.assertEqual(len(result), len(names))
        self.assertTrue(all(item["id"] == item["name"] for item in result))
        self.assertTrue(all(len(item["article_ids"]) == 1 for item in result))

    def test_shared_article_appears_once_under_each_recorded_author(self):
        model = {"articles": {"en": [
            article("shared", {"name": "Mark Brubaker"}, {"name": "Ann Brubaker"}, {"name": "Mark Brubaker"}),
            article("later", {"name": "Mark Brubaker"}),
        ]}}
        result = {item["name"]: item for item in build_author_index(model)}
        self.assertEqual(result["Ann Brubaker"]["article_ids"], ["shared"])
        self.assertEqual(result["Mark Brubaker"]["article_ids"], ["shared", "later"])

    def test_only_authoritative_english_source_creates_authors_and_counts(self):
        english = article("source", {"name": "Changed display credit"})
        english["source_metadata"] = {"byline": {"authors": [{"name": "Recorded Author"}]}}
        model = {"articles": {
            "en": [english],
            "af": [article("source", {"name": "Translated Author"})],
            "de": [article("source", {"name": "Recorded Author"}), article("unpublished", {"name": "Extra Author"})],
        }}
        original = copy.deepcopy(model)
        self.assertEqual(build_author_index(model), [
            {"id": "Recorded Author", "name": "Recorded Author", "article_ids": ["source"], "details": {}},
        ])
        self.assertEqual(model, original)

    def test_raw_source_credits_and_missing_bylines_do_not_invent_authors(self):
        model = {"articles": {"en": [
            {"id": "absent"}, {"id": "null", "byline": None},
            {"id": "raw", "byline": "Published by Christian Printing Mission"},
            {"id": "publisher", "byline": {"raw": "from Herald of His Coming"}},
            article("empty", raw="Author Unknown"),
        ]}}
        self.assertEqual(build_author_index(model), [])

    def test_recorded_anonymous_names_are_not_unified_or_inferred(self):
        model = {"articles": {"en": [
            article("one", {"name": "Unknown"}),
            article("two", {"name": "Author unknown"}),
            article("three", {"name": "Anonymous"}),
        ]}}
        self.assertEqual([item["name"] for item in build_author_index(model)], ["Anonymous", "Author unknown", "Unknown"])

    def test_historical_details_are_allowlisted_unique_and_preserve_types(self):
        model = {"articles": {"en": [
            article("one", {"name": "A Writer", "location": "Old Town", "role": "Words", "birth_year": 1900,
                            "age": 25, "photo": "/portrait.jpg", "private_note": "Do not display"}),
            article("two", {"name": "A Writer", "location": "New Town", "role": "Music", "birth_year": 1900,
                            "death_year": 1980, "life_dates": "1900–1980", "credentials": "MD"}),
            article("three", {"name": "A Writer", "location": "Old Town", "role": "Words", "age": 26}),
        ]}}
        result = build_author_index(model)[0]
        self.assertEqual(result["details"], {
            "location": ["Old Town", "New Town"], "role": ["Words", "Music"], "birth_year": [1900],
            "age": [25, 26], "death_year": [1980], "life_dates": ["1900–1980"], "credentials": ["MD"],
        })
        self.assertEqual(result["article_ids"], ["one", "two", "three"])
        result["details"]["role"].append("Editor")
        self.assertEqual(model["articles"]["en"][0]["byline"]["authors"][0]["role"], "Words")

    def test_missing_empty_and_null_details_are_omitted(self):
        model = {"articles": {"en": [article("one", {"name": "A Writer", "location": None, "role": " ", "credentials": ""})]}}
        self.assertEqual(build_author_index(model)[0]["details"], {})

    def test_malformed_structured_bylines_fail_with_article_context(self):
        invalid_bylines = [False, 5, [], {"authors": None}, {"authors": {}}, {"authors": ["A Writer"]},
                           {"authors": [{}]}, {"authors": [{"name": None}]}, {"authors": [{"name": " \t"}]}]
        for byline in invalid_bylines:
            with self.subTest(byline=byline), self.assertRaisesRegex(AuthorError, "article broken"):
                build_author_index({"articles": {"en": [{"id": "broken", "byline": byline}]}})

    def test_malformed_detail_values_are_never_coerced(self):
        for field, value in (("location", ["Town"]), ("role", 42), ("birth_year", "1900"), ("age", True), ("death_year", 1980.5)):
            with self.subTest(field=field, value=value), self.assertRaisesRegex(AuthorError, f"Invalid author {field}.*article broken"):
                build_author_index({"articles": {"en": [article("broken", {"name": "A Writer", field: value})]}})

    def test_english_inventory_and_source_metadata_must_be_well_formed(self):
        for model in ({}, {"articles": {}}, {"articles": {"en": {}}}, {"articles": {"en": [None]}},
                      {"articles": {"en": [{}]}}, {"articles": {"en": [{"id": "bad", "source_metadata": []}]}}):
            with self.subTest(model=model), self.assertRaises(AuthorError):
                build_author_index(model)


if __name__ == "__main__":
    unittest.main()
