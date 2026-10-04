import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.authors import AuthorError, build_author_index, canonical_author_name, load_author_aliases


def article(identity, *authors, raw=None):
    return {"id": identity, "byline": {"raw": raw, "authors": list(authors)}}


class AuthorIndexTests(unittest.TestCase):
    def test_unlisted_names_remain_distinct_and_sorted(self):
        names = ["Joel Hostetler", "Joel A. Hostetler", "joel Hostetler", "Joel A Hostetler", " Joel Hostetler "]
        model = {"articles": {"en": [article(str(number), {"name": name}) for number, name in enumerate(names)]}}
        result = build_author_index(model, aliases={})
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
            {"id": "Recorded Author", "name": "Recorded Author", "source_names": ["Recorded Author"],
             "article_ids": ["source"], "details": {}},
        ])
        self.assertEqual(model, original)

    def test_retained_translation_uses_frozen_english_credit_and_ready_uses_current(self):
        english = article('source', {'name': 'Current Author', 'location': 'Current town'})
        retained = article('source', {'name': 'Untrusted display author'})
        retained.update(source_metadata={'byline': {'authors': [{'name': 'Original Author', 'location': 'Old town'}]}},
                        retention={'kind': 'translation', 'status': 'stale', 'source_revision': 'a' * 40})
        ready = article('source', {'name': 'Invented translated author'})
        ready['source_metadata'] = {'byline': {'authors': [{'name': 'Invented source override'}]}}
        model = {'articles': {'en': [english], 'af': [retained], 'fr': [ready]}}
        original = copy.deepcopy(model)
        catalogue = {item['name']: item for item in build_author_index(model, aliases={})}
        self.assertEqual(set(catalogue), {'Current Author', 'Original Author'})
        self.assertEqual(catalogue['Original Author']['details'], {'location': ['Old town']})
        for tag, expected in [('en', 'Current Author'), ('af', 'Original Author'), ('fr', 'Current Author')]:
            with self.subTest(locale=tag):
                selected = build_author_index(model, aliases={}, locale=tag)
                self.assertEqual([item['name'] for item in selected], [expected])
                self.assertEqual(selected[0]['article_ids'], ['source'])
        self.assertEqual(build_author_index(model, aliases={}, locale='de'), [])
        self.assertEqual(model, original)

    def test_retained_copies_never_increase_author_original_article_counts(self):
        english = article('source', {'name': 'Current Author'})
        retained = article('source', {'name': 'Original Author'})
        retained.update(source_metadata=copy.deepcopy(retained),
                        retention={'kind': 'translation', 'status': 'source_removed', 'source_revision': 'a' * 40})
        model = {'articles': {'en': [english], 'af': [retained], 'fr': [copy.deepcopy(retained)]}}
        catalogue = {item['name']: item for item in build_author_index(model, aliases={})}
        self.assertEqual(catalogue['Original Author']['article_ids'], ['source'])
        self.assertEqual(catalogue['Original Author']['source_names'], ['Original Author'])

    def test_retained_author_metadata_cannot_fall_back_to_current_or_display_byline(self):
        english = article('source', {'name': 'Current Author'})
        for source in (None, [], {'byline': {'authors': [{'name': 'Original Author', 'age': True}]}}):
            with self.subTest(source=source):
                retained = article('source', {'name': 'Display Author'})
                retained.update(source_metadata=source,
                                retention={'kind': 'translation', 'status': 'stale', 'source_revision': 'a' * 40})
                with self.assertRaisesRegex(AuthorError, 'article source'):
                    build_author_index({'articles': {'en': [english], 'af': [retained]}})

    def test_raw_source_credits_and_missing_bylines_do_not_invent_authors(self):
        model = {"articles": {"en": [
            {"id": "absent"}, {"id": "null", "byline": None},
            {"id": "raw", "byline": "Published by Christian Printing Mission"},
            {"id": "publisher", "byline": {"raw": "from Herald of His Coming"}},
            article("empty", raw="Author Unknown"),
        ]}}
        self.assertEqual(build_author_index(model), [])

    def test_recorded_anonymous_names_are_explicitly_unified(self):
        model = {"articles": {"en": [
            article("one", {"name": "Unknown"}),
            article("two", {"name": "Author unknown"}),
            article("three", {"name": "Anonymous"}),
        ]}}
        self.assertEqual(build_author_index(model), [{
            "id": "Anonymous", "name": "Anonymous", "source_names": ["Unknown", "Author unknown", "Anonymous"],
            "article_ids": ["one", "two", "three"], "details": {},
        }])

    def test_source_role_only_credits_do_not_invent_named_or_anonymous_authors(self):
        records = json.loads((Path(__file__).parent / 'fixtures/role-only-bylines.json').read_text())
        model = {"articles": {"en": records}}
        original = copy.deepcopy(model)
        self.assertEqual(build_author_index(model), [])
        self.assertEqual(model, original)

    def test_missing_and_null_names_keep_other_credited_authors_and_details_separate(self):
        model = {"articles": {"en": [article("mixed", {}, {"role": "Editor"},
                 {"name": None, "role": "The Editor", "location": "Unassigned town"},
                 {"name": "A Writer", "role": "Words"})]}}
        original = copy.deepcopy(model)
        self.assertEqual(build_author_index(model), [{
            "id": "A Writer", "name": "A Writer", "source_names": ["A Writer"],
            "article_ids": ["mixed"], "details": {"role": ["Words"]},
        }])
        self.assertEqual(model, original)

    def test_aliases_union_articles_and_details_without_changing_recorded_names(self):
        model = {"articles": {"en": [
            article("shared", {"name": "Curvin L Wenger", "location": "Town", "role": "Words"},
                    {"name": "Curvin Wenger", "location": "Town", "role": "Music"}),
            article("later", {"name": "Curvin L. Wenger", "location": "County", "role": "Words"}),
            article("shared", {"name": "Curvin Wenger", "age": 50}),
        ]}}
        original = copy.deepcopy(model)
        self.assertEqual(build_author_index(model), [{
            "id": "Curvin L. Wenger", "name": "Curvin L. Wenger",
            "source_names": ["Curvin L Wenger", "Curvin Wenger", "Curvin L. Wenger"],
            "article_ids": ["shared", "later"],
            "details": {"location": ["Town", "County"], "role": ["Words", "Music"], "age": [50]},
        }])
        self.assertEqual(model, original)

    def test_confirmed_names_group_but_generations_and_unreviewed_variants_stay_distinct(self):
        names = ["George Brunk II", "George R. Brunk II", "George R. Brunk, Sr.",
                 "George R Brunk II", "Brother Dean", "Dean Taylor", "Bro. Denny", "Denny Kenaston"]
        model = {"articles": {"en": [article(str(number), {"name": name}) for number, name in enumerate(names)]}}
        result = {item["name"]: item for item in build_author_index(model)}
        self.assertEqual(result["George R. Brunk II"]["article_ids"], ["0", "1"])
        self.assertEqual(result["George R. Brunk, Sr."]["article_ids"], ["2"])
        self.assertEqual(result["George R Brunk II"]["article_ids"], ["3"])
        self.assertEqual(result["Dean Taylor"]["article_ids"], ["4", "5"])
        self.assertEqual(result["Denny Kenaston"]["article_ids"], ["6", "7"])

    def test_custom_aliases_override_defaults_and_need_no_self_entries(self):
        model = {"articles": {"en": [article("one", {"name": "Unknown"}, {"name": "A. Writer"})]}}
        result = build_author_index(model, aliases={"A. Writer": "A Writer"})
        self.assertEqual([item["name"] for item in result], ["A Writer", "Unknown"])

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
                           *({"authors": [{"name": name}]} for name in ("", " \t", False, 42, [], {}))]
        for byline in invalid_bylines:
            with self.subTest(byline=byline), self.assertRaisesRegex(AuthorError, "article broken"):
                build_author_index({"articles": {"en": [{"id": "broken", "byline": byline}]}})

    def test_malformed_detail_values_are_never_coerced(self):
        for field, value in (("location", ["Town"]), ("role", 42), ("birth_year", "1900"), ("age", True), ("death_year", 1980.5)):
            for name in ("A Writer", None):
                with self.subTest(field=field, value=value, name=name), self.assertRaisesRegex(AuthorError, f"Invalid author {field}.*article broken"):
                    build_author_index({"articles": {"en": [article("broken", {"name": name, field: value})]}})

    def test_english_inventory_and_source_metadata_must_be_well_formed(self):
        for model in ({}, {"articles": {}}, {"articles": {"en": {}}}, {"articles": {"en": [None]}},
                      {"articles": {"en": [{}]}}, {"articles": {"en": [{"id": "bad", "source_metadata": []}]}}):
            with self.subTest(model=model), self.assertRaises(AuthorError):
                build_author_index(model)


class AuthorAliasConfigurationTests(unittest.TestCase):
    def load_text(self, content):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "aliases.json"
            path.write_text(content, encoding="utf-8")
            return load_author_aliases(path)

    def test_groups_load_as_flat_mapping_including_canonical_names(self):
        self.assertEqual(self.load_text(json.dumps({"version": 1, "authors": {
            "A Writer": ["A. Writer", "Writer, A"], "Another Writer": [],
        }})), {"A Writer": "A Writer", "A. Writer": "A Writer", "Writer, A": "A Writer",
               "Another Writer": "Another Writer"})

    def test_reviewed_default_groups_cover_reported_spellings(self):
        aliases = load_author_aliases()
        expected = {
            "A.W. Tozer": "A. W. Tozer", "Bro. Dean": "Dean Taylor", "Brother Dean": "Dean Taylor",
            "Bro. Denny": "Denny Kenaston", "Brother Denny": "Denny Kenaston",
            "Charles Finney": "Charles G. Finney", "Curvin L Wenger": "Curvin L. Wenger",
            "C. L. Wenger": "Curvin L. Wenger", "John Waldron": "Vincent “John” Waldron, MD",
            "E. M Bounds": "E. M. Bounds", "F. B. Myer": "F. B. Meyer",
            "George Brunk II": "George R. Brunk II", "George Muller": "George Müller",
            "Joel Hostetler": "Joel A. Hostetler", "Vincent \"John\" Waldron": "Vincent “John” Waldron, MD",
            "Robert Murray M’cheyne": "Robert Murray M’Cheyne",
            "Wolf Miggiani M.D.": "Wolf Miggiani MD",
        }
        for recorded, canonical in expected.items():
            with self.subTest(recorded=recorded):
                self.assertEqual(canonical_author_name(recorded, aliases), canonical)
                self.assertEqual(aliases[canonical], canonical)
        for recorded in ("Anon.", "Anonymous", "anonymous godly woman", "Author Unknown", "Author unknown",
                         "(Author unknown)", "An Anonymous Firstfruit", "Unknown", "Unknown author", "unknown Ghanian"):
            with self.subTest(recorded=recorded):
                self.assertEqual(canonical_author_name(recorded), "Anonymous")
        self.assertEqual(canonical_author_name("A W Tozer", aliases), "A W Tozer")

    def test_duplicate_json_keys_are_rejected_at_every_level(self):
        for content in ('{"version":1,"version":1,"authors":{}}',
                        '{"version":1,"authors":{"A":[],"A":["B"]}}'):
            with self.subTest(content=content), self.assertRaisesRegex(AuthorError, "Duplicate key"):
                self.load_text(content)

    def test_collisions_self_aliases_and_chains_are_rejected(self):
        for groups in ({"A": ["A"]}, {"A": ["B", "B"]}, {"A": ["C"], "B": ["C"]},
                       {"A": ["B"], "B": ["C"]}, {"A": ["B"], "B": ["A"]}):
            with self.subTest(groups=groups), self.assertRaisesRegex(AuthorError, "Duplicate or conflicting"):
                self.load_text(json.dumps({"version": 1, "authors": groups}))

    def test_malformed_names_and_configuration_are_rejected(self):
        invalid = [None, [], {}, {"version": 2, "authors": {}}, {"version": True, "authors": {}},
                   {"version": 1, "authors": []}, {"version": 1, "authors": {}, "extra": {}},
                   {"version": 1, "authors": {"A": "B"}}]
        for name in ("", " ", " A", "A ", "A\nB", "A\x7fB", "A\u200bB", "A\ue000B", "A\ud800B", "A" * 1025):
            invalid.extend(({"version": 1, "authors": {name: []}}, {"version": 1, "authors": {"A": [name]}}))
        for name in (None, 1, False, []):
            invalid.append({"version": 1, "authors": {"A": [name]}})
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(AuthorError):
                self.load_text(json.dumps(data))
        self.assertEqual(self.load_text(json.dumps({"version": 1, "authors": {"A" * 1024: []}})),
                         {"A" * 1024: "A" * 1024})

    def test_missing_file_and_invalid_json_raise_author_errors(self):
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(AuthorError, "Cannot read author aliases"):
            load_author_aliases(Path(temporary) / "missing.json")
        with self.assertRaisesRegex(AuthorError, "Cannot read author aliases"):
            self.load_text("{")

    def test_custom_flat_mappings_reject_chains_cycles_and_invalid_names(self):
        model = {"articles": {"en": []}}
        for aliases in ([], {"A": "B", "B": "C"}, {"A": "B", "B": "A"}, {"A": ""}, {"": "A"}, {"A": None}):
            with self.subTest(aliases=aliases), self.assertRaises(AuthorError):
                build_author_index(model, aliases=aliases)
            with self.subTest(aliases=aliases), self.assertRaises(AuthorError):
                canonical_author_name("A", aliases=aliases)


if __name__ == "__main__":
    unittest.main()
