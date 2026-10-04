"""Offline proof for pinned source reads and retained snapshot provenance."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import historical_source
from scripts.historical_source import (
    ARTICLE_FIELDS, HistoricalError, HistoricalFileMissing, HistoricalSources,
    REPOSITORY, SOURCE_URL, verify_retained_source,
)


A = "00000000-0000-4000-8000-000000000001"
I = "00000000-0000-4000-8000-000000000002"
C = "00000000-0000-4000-8000-000000000003"
T = "00000000-0000-4000-8000-000000000004"
S = "00000000-0000-4000-8000-000000000005"
OTHER = "00000000-0000-4000-8000-000000000006"
SHA = "a" * 40
HTML_PATH = f"content/articles/{A}.html"
IMAGE_PATH = f"public/images/articles/{A}-1.jpg"
HTML = f'<article data-article-id="{A}"><p>Old words, café.\r\nUnchanged.</p></article>\r\n'


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8"))


def fixture():
    article = {
        "id": A, "issue_id": I, "sequence": 1, "title": "Original title",
        "subtitle": None, "section": "", "byline": {"raw": "Printed Name"},
        "categories": {"primary": C, "additional": []}, "topics": [T],
        "series": {"id": S, "part": 1}, "images": [],
        "rights": {"status": "eligible", "article_specific_permission_notice_detected": False},
        "source_pages": {"start": 3, "end": 5},
        "html": {"repository_path": HTML_PATH}, "language": "en",
        "verification": {"private": "reviewer"}, "source_labels": {"private": "old labels"},
    }
    catalogue = {
        "format_version": "2.0", "issues": [{"id": I, "publication": "Old magazine",
                                               "date": {"year": 2020}}],
        "categories": [{"id": C, "name": "Old category", "slug": "old-category"}],
        "topics": [{"id": T, "name": "Old topic"}],
        "series": [{"id": S, "name": "Old series"}],
        "normalization": [{"private": "normalization"}], "review_candidates": ["private review"],
    }
    index = {"format_version": "2.0", "articles": [article], "skipped": [{"id": OTHER}]}
    return article, catalogue, {"index.json": encoded(index), "catalogue.json": encoded(catalogue),
                                HTML_PATH: HTML.encode("utf-8"), IMAGE_PATH: b"old image bytes"}


def retained_spec(article, revision=SHA):
    fingerprints = {
        "html_sha256": digest(HTML.encode("utf-8")), "metadata_sha256": canonical(article),
        "text_sha256": "1" * 64, "structure_sha256": "2" * 64,
        "translation_metadata_sha256": "3" * 64,
    }
    snapshot = {
        "repository": REPOSITORY, "revision": revision,
        "article": {key: copy.deepcopy(article.get(key)) for key in ARTICLE_FIELDS},
        "fingerprints": fingerprints,
        "translation_key": canonical({key: fingerprints[key] for key in (
            "text_sha256", "structure_sha256", "translation_metadata_sha256")}),
        "html": HTML,
    }
    return {"repository": REPOSITORY, "revision": revision, "article_id": A,
            "html_repository_path": HTML_PATH, "index_repository_path": "index.json",
            "catalogue_repository_path": "catalogue.json", "html_sha256": fingerprints["html_sha256"],
            "metadata_sha256": fingerprints["metadata_sha256"],
            "translation_key": snapshot["translation_key"], "fingerprints": fingerprints,
            "article": snapshot["article"], "snapshot_sha256": canonical(snapshot)}


def refresh_snapshot(spec):
    spec["snapshot_sha256"] = canonical({key: spec[key] for key in (
        "article", "fingerprints", "repository", "revision", "translation_key")} | {"html": HTML})


class RetainedSourceTests(unittest.TestCase):
    def setUp(self):
        self.article, self.catalogue, self.files = fixture()
        self.spec = retained_spec(self.article)
        self.requests = []

    def read(self, revision, path):
        self.requests.append((revision, path))
        self.assertEqual(revision, SHA)
        if path not in self.files:
            raise HistoricalFileMissing(path)
        return self.files[path]

    def verify(self):
        return verify_retained_source(self.spec, A, SHA, self.read)

    def change_index(self, change):
        index = json.loads(self.files["index.json"])
        change(index)
        self.files["index.json"] = encoded(index)

    def change_catalogue(self, change):
        catalogue = json.loads(self.files["catalogue.json"])
        change(catalogue)
        self.files["catalogue.json"] = encoded(catalogue)

    def test_exact_html_public_metadata_and_historical_labels(self):
        result = self.verify()
        self.assertEqual(result["html"], HTML)
        self.assertEqual(result["revision"], SHA)
        self.assertEqual(result["article"]["html"]["repository_path"], HTML_PATH)
        self.assertEqual(result["article"]["language"], "en")
        self.assertEqual(result["catalogue"]["categories"][0]["name"], "Old category")
        self.assertNotIn("verification", result["article"])
        self.assertNotIn("source_labels", result["article"])
        self.assertNotIn("normalization", result["catalogue"])
        self.assertNotIn("review_candidates", result["catalogue"])
        self.assertEqual(set(self.requests), {(SHA, "index.json"), (SHA, "catalogue.json"),
                                               (SHA, HTML_PATH)})

    def test_normalized_snapshot_is_verified_without_rehashing_frozen_metadata(self):
        self.spec["article"]["title"] = "Normalized title from original snapshot"
        refresh_snapshot(self.spec)
        self.assertNotEqual(canonical(self.spec["article"]), self.spec["metadata_sha256"])
        self.assertEqual(self.verify()["article"]["title"], self.spec["article"]["title"])

    def test_exporter_metadata_digest_is_required_inside_fingerprints_not_duplicated(self):
        del self.spec['metadata_sha256']
        self.assertEqual(self.verify()['article']['id'], self.spec['article_id'])
        self.spec['fingerprints']['metadata_sha256'] = '0' * 64
        with self.assertRaisesRegex(HistoricalError, 'snapshot checksum'):
            self.verify()

    def test_snapshot_reconstruction_uses_exact_six_keys_and_unicode(self):
        self.spec["article"]["title"] = "Foi, café, 信仰"
        refresh_snapshot(self.spec)
        self.spec["transport_annotation"] = "not part of the original snapshot"
        self.assertEqual(self.verify()["article"]["title"], "Foi, café, 信仰")

    def test_snapshot_tamper_fails_even_with_valid_individual_fingerprints(self):
        self.spec["article"]["title"] = "Invented title"
        with self.assertRaisesRegex(HistoricalError, "snapshot checksum"):
            self.verify()

    def test_returned_metadata_is_not_shared_or_input_mutated(self):
        before = copy.deepcopy(self.spec)
        result = self.verify()
        result["article"]["byline"]["raw"] = "Changed"
        result["catalogue"]["categories"][0]["name"] = "Changed"
        self.assertEqual(self.spec, before)
        self.assertEqual(self.verify()["catalogue"]["categories"][0]["name"], "Old category")

    def test_unapproved_repository_revision_identity_or_path_rejected_before_read(self):
        variants = {
            "repository": "attacker/berean-voice", "revision": "b" * 40,
            "article_id": OTHER, "html_repository_path": f"content/articles/{OTHER}.html",
            "index_repository_path": "../index.json", "catalogue_repository_path": "other.json",
        }
        for key, value in variants.items():
            with self.subTest(key=key):
                changed = copy.deepcopy(self.spec)
                changed[key] = value
                with self.assertRaises(HistoricalError):
                    verify_retained_source(changed, A, SHA, self.read)
        self.assertEqual(self.requests, [])

    def test_bad_expected_id_or_non_commit_revision_rejected(self):
        for value in ("main", "a" * 39, "A" * 40, "a" * 40 + "^{commit}", None):
            with self.subTest(value=value), self.assertRaises(HistoricalError):
                verify_retained_source(self.spec, A, value, self.read)
        with self.assertRaises(HistoricalError):
            verify_retained_source(self.spec, "not-a-uuid", SHA, self.read)
        self.assertEqual(self.requests, [])

    def test_both_html_fingerprints_checked(self):
        for location in ("outer", "fingerprint", "file"):
            with self.subTest(location=location):
                original_spec, original_file = copy.deepcopy(self.spec), self.files[HTML_PATH]
                if location == "outer":
                    self.spec["html_sha256"] = "f" * 64
                elif location == "fingerprint":
                    self.spec["fingerprints"]["html_sha256"] = "f" * 64
                    refresh_snapshot(self.spec)
                else:
                    self.files[HTML_PATH] = HTML.replace("\r\n", "\n").encode()
                with self.assertRaisesRegex(HistoricalError, "HTML fingerprint"):
                    self.verify()
                self.spec, self.files[HTML_PATH] = original_spec, original_file

    def test_metadata_fingerprint_and_original_translation_key_checked(self):
        self.spec["metadata_sha256"] = "0" * 64
        with self.assertRaisesRegex(HistoricalError, "metadata fingerprint"):
            self.verify()
        self.spec = retained_spec(self.article)
        self.spec["translation_key"] = "0" * 64
        refresh_snapshot(self.spec)
        with self.assertRaisesRegex(HistoricalError, "translation key"):
            self.verify()

    def test_absent_index_article_never_resurrected_from_snapshot_or_skipped(self):
        self.change_index(lambda index: index.update(articles=[], skipped=[self.article]))
        with self.assertRaisesRegex(HistoricalError, "absent from pinned source index"):
            self.verify()

    def test_duplicate_article_and_catalogue_identities_rejected(self):
        self.change_index(lambda index: index["articles"].append(copy.deepcopy(index["articles"][0])))
        with self.assertRaisesRegex(HistoricalError, "Duplicate historical article identity"):
            self.verify()
        self.article, self.catalogue, self.files = fixture()
        self.change_catalogue(lambda cat: cat["topics"].append({"id": C, "name": "Repeated"}))
        with self.assertRaisesRegex(HistoricalError, "Duplicate historical catalogue identity"):
            self.verify()

    def test_unknown_issue_category_topic_and_series_rejected(self):
        for group in ("issues", "categories", "topics", "series"):
            with self.subTest(group=group):
                _, _, self.files = fixture()
                self.change_catalogue(lambda cat: cat.update({group: []}))
                with self.assertRaisesRegex(HistoricalError, "Missing historical"):
                    self.verify()

    def test_malformed_dependencies_rejected_as_historical_errors(self):
        for key, value in (("issue_id", []), ("categories", {"primary": []}),
                           ("topics", [{}]), ("series", {"id": []}), ("images", [None]),
                           ("sequence", True), ("byline", []), ("rights", {})):
            with self.subTest(key=key):
                _, _, self.files = fixture()
                self.change_index(lambda index: index["articles"][0].update({key: value}))
                with self.assertRaises(HistoricalError):
                    self.verify()

    def test_absent_printed_byline_remains_null(self):
        self.spec["article"]["byline"] = None
        refresh_snapshot(self.spec)
        self.change_index(lambda index: index["articles"][0].update(byline=None))
        self.assertIsNone(self.verify()["article"]["byline"])

    def test_frozen_metadata_requires_exact_public_schema_and_valid_dependencies(self):
        for key, value in (("verification", {"private": "x"}), ("issue_id", OTHER),
                           ("id", OTHER), ("topics", [OTHER])):
            with self.subTest(key=key):
                self.spec = retained_spec(self.article)
                self.spec["article"][key] = value
                refresh_snapshot(self.spec)
                with self.assertRaises(HistoricalError):
                    self.verify()

    def test_duplicate_json_keys_and_non_finite_values_fail(self):
        for raw in (b'{"format_version":"2.0","articles":[],"articles":[]}',
                    b'{"format_version":"2.0","articles":[],"n":NaN}',
                    b'{"format_version":"2.0","articles":[],"n":1e999}', b'\xff', b'[]'):
            with self.subTest(raw=raw):
                self.files["index.json"] = raw
                with self.assertRaises(HistoricalError):
                    self.verify()

    def test_missing_and_transport_failures_are_not_silently_replaced(self):
        del self.files[HTML_PATH]
        with self.assertRaises(HistoricalFileMissing):
            self.verify()
        def failed_read(revision, path):
            raise HistoricalError("network refused")
        with self.assertRaisesRegex(HistoricalError, "network refused"):
            verify_retained_source(self.spec, A, SHA, failed_read)

    def test_injected_reader_cannot_reuse_stale_documents_by_claimed_revision(self):
        self.verify()
        self.change_index(lambda index: index.update(articles=[]))
        with self.assertRaisesRegex(HistoricalError, "absent from pinned source index"):
            self.verify()


class HistoricalGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.git("init", "--quiet", "--template=", "--object-format=sha1")
        _, _, files = fixture()
        for name, raw in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        (self.source / "tools").mkdir()
        (self.source / "tools/archive.py").write_text("raise Exception('must never run')\n")
        self.revision = self.commit()
        self.calls = []
        def offline_runner(command, **kwargs):
            self.calls.append(command)
            if "fetch" in command:
                raise AssertionError("Network is forbidden in offline Git fixture")
            return subprocess.run(command, **kwargs)
        self.provider = HistoricalSources(self.root / "cache", runner=offline_runner)
        with self.provider._locked():
            pass
        self.copy_objects()

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.source),
                                        "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                                        *args], stderr=subprocess.PIPE).decode().strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Offline fixture")
        return self.git("rev-parse", "HEAD")

    def copy_objects(self):
        def copy_new(source, destination):
            if not Path(destination).exists():
                shutil.copy2(source, destination)
            return destination
        shutil.copytree(self.source / ".git/objects", self.provider.repository_path / "objects",
                        dirs_exist_ok=True, copy_function=copy_new)

    def test_exact_commit_bytes_catalogue_and_article_without_checkout_or_execution(self):
        self.assertEqual(self.provider.read(self.revision, HTML_PATH), HTML.encode())
        result = self.provider.article(self.revision, A)
        self.assertEqual(result["html"], HTML)
        self.assertEqual(result["revision"], self.revision)
        self.assertNotIn("verification", result["article"])
        self.assertNotIn("normalization", self.provider.catalogue(self.revision))
        self.assertFalse((self.provider.repository_path / "content").exists())
        self.assertFalse(any("archive.py" in " ".join(command) for command in self.calls))

    def test_historical_article_survives_later_edit_and_removal(self):
        (self.source / HTML_PATH).write_text("New text")
        changed = self.commit()
        (self.source / HTML_PATH).unlink()
        removed = self.commit()
        self.copy_objects()
        self.assertEqual(self.provider.read(changed, HTML_PATH), b"New text")
        with self.assertRaises(HistoricalFileMissing):
            self.provider.read(removed, HTML_PATH)
        self.assertEqual(self.provider.read(self.revision, HTML_PATH), HTML.encode())

    def test_shared_bare_cache_reuses_objects_across_instances(self):
        first = self.provider.read(self.revision, IMAGE_PATH)
        second = HistoricalSources(self.root / "cache", runner=self.provider._runner)
        self.assertEqual(second.read(self.revision, IMAGE_PATH), first)
        self.assertFalse(any("fetch" in command for command in self.calls))

    def test_repeated_locale_reads_reuse_verified_bytes(self):
        first = self.provider.read(self.revision, "index.json")
        count = len(self.calls)
        for _ in range(20):
            self.assertIs(self.provider.read(self.revision, "index.json"), first)
        self.assertEqual(len(self.calls), count)

    def test_multiple_articles_and_snapshots_share_parsing_without_mutation_leaks(self):
        index_path = self.source / "index.json"
        index = json.loads(index_path.read_bytes())
        second = copy.deepcopy(index["articles"][0])
        second.update(id=OTHER, sequence=2, title="Second article",
                      html={"repository_path": f"content/articles/{OTHER}.html"})
        index["articles"].append(second)
        index_path.write_bytes(encoded(index))
        (self.source / second["html"]["repository_path"]).write_text(HTML.replace(A, OTHER))
        revision = self.commit()
        self.copy_objects()
        historical_source._catalogue.cache_clear()
        historical_source._documents.cache_clear()
        with (patch.object(historical_source, "_json", wraps=historical_source._json) as parse,
              patch.object(historical_source, "_read_bytes", wraps=historical_source._read_bytes) as read):
            first = self.provider.article(revision, A)
            first["article"]["byline"]["raw"] = "Caller mutation"
            first["catalogue"]["categories"][0]["name"] = "Caller mutation"
            second_result = self.provider.article(revision, OTHER)
            snapshot = retained_spec(index["articles"][0], revision=revision)
            retained = verify_retained_source(snapshot, A, revision, self.provider.read)
            self.assertEqual([call.args[1] for call in parse.call_args_list], ["catalogue", "index"])
            document_reads = [call.args[2] for call in read.call_args_list
                              if call.args[2] in {"index.json", "catalogue.json"}]
            self.assertEqual(document_reads, ["index.json", "catalogue.json"])
        self.assertEqual(second_result["article"]["title"], "Second article")
        self.assertEqual(second_result["article"]["byline"]["raw"], "Printed Name")
        self.assertEqual(second_result["catalogue"]["categories"][0]["name"], "Old category")
        self.assertEqual(retained["article"]["byline"]["raw"], "Printed Name")
        self.assertEqual(retained["catalogue"]["categories"][0]["name"], "Old category")
        self.assertEqual(list(self.provider._parsed_documents), [revision])

    def test_parsed_revision_cache_is_bounded_and_preserves_revision_identity(self):
        index_path = self.source / "index.json"
        index = json.loads(index_path.read_bytes())
        index["articles"][0]["title"] = "Later title"
        index_path.write_bytes(encoded(index))
        later_revision = self.commit()
        self.copy_objects()
        with patch.object(historical_source, "MAX_PARSED_REVISIONS", 1):
            self.assertEqual(self.provider.article(self.revision, A)["article"]["title"], "Original title")
            self.assertEqual(self.provider.article(later_revision, A)["article"]["title"], "Later title")
            self.assertEqual(list(self.provider._parsed_documents), [later_revision])
            self.assertEqual(self.provider.article(self.revision, A)["article"]["title"], "Original title")
            self.assertEqual(list(self.provider._parsed_documents), [self.revision])

    def test_unindexed_file_cannot_become_article(self):
        path = self.source / f"content/articles/{OTHER}.html"
        path.write_text(f'<article data-article-id="{OTHER}">Unindexed</article>')
        revision = self.commit()
        self.copy_objects()
        with self.assertRaisesRegex(HistoricalError, "absent from pinned source index"):
            self.provider.article(revision, OTHER)

    def test_unsafe_revisions_and_paths_do_not_invoke_git(self):
        initial_calls = len(self.calls)
        for path in ("../index.json", "/index.json", "content/articles/../index.json",
                     "content/articles/not-a-uuid.html", "public/images/articles/../x",
                     "public/images/articles//x", "public/images/articles/x?query",
                     "public/images/articles/x\n.jpg", "tools/archive.py", "INDEX.json"):
            with self.subTest(path=path), self.assertRaises(HistoricalError):
                self.provider.read(self.revision, path)
        for revision in ("main", "--help", "a" * 39, "A" * 40, self.revision + "^{}"):
            with self.subTest(revision=revision), self.assertRaises(HistoricalError):
                self.provider.read(revision, "index.json")
        self.assertEqual(len(self.calls), initial_calls)

    def test_symlink_file_and_intermediate_directory_are_invalid_not_missing(self):
        (self.source / HTML_PATH).unlink()
        (self.source / HTML_PATH).symlink_to("../../index.json")
        file_revision = self.commit()
        self.copy_objects()
        with self.assertRaisesRegex(HistoricalError, "symlink") as raised:
            self.provider.read(file_revision, HTML_PATH)
        self.assertNotIsInstance(raised.exception, HistoricalFileMissing)
        shutil.rmtree(self.source / "content")
        (self.source / "content").symlink_to("public")
        directory_revision = self.commit()
        self.copy_objects()
        with self.assertRaisesRegex(HistoricalError, "symlink"):
            self.provider.read(directory_revision, HTML_PATH)

    def test_verified_missing_path_is_distinct_from_git_access_failure(self):
        with self.assertRaises(HistoricalFileMissing):
            self.provider.read(self.revision, f"content/articles/{OTHER}.html")
        def denied(command, **kwargs):
            return subprocess.CompletedProcess(command, 128, b"", b"access denied")
        self.provider._runner = denied
        with self.assertRaises(HistoricalError) as raised:
            self.provider.read(self.revision, HTML_PATH)
        self.assertNotIsInstance(raised.exception, HistoricalFileMissing)

    def test_object_corruption_and_size_limits_rejected(self):
        run = self.provider._runner
        def corrupted(command, **kwargs):
            result = run(command, **kwargs)
            if command[-3:-1] == ["cat-file", "blob"]:
                result.stdout = b"x" * len(result.stdout)
            return result
        self.provider._runner = corrupted
        with self.assertRaisesRegex(HistoricalError, "checksum mismatch"):
            self.provider.read(self.revision, HTML_PATH)
        self.provider._runner = run
        with patch("scripts.historical_source.MAX_FILE_BYTES", 1):
            with self.assertRaisesRegex(HistoricalError, "size limit"):
                self.provider.read(self.revision, HTML_PATH)

    def test_blob_sha_cannot_be_used_as_commit(self):
        blob = self.git("rev-parse", f"{self.revision}:{HTML_PATH}")
        with self.assertRaisesRegex(HistoricalError, "type or identity"):
            self.provider.read(blob, HTML_PATH)

    def test_fetch_is_exact_filtered_noninteractive_and_failure_is_fatal(self):
        recorded = []
        run = self.provider._runner
        def failed_fetch(command, **kwargs):
            recorded.append((command, kwargs))
            if "fetch" in command:
                return subprocess.CompletedProcess(command, 128, b"", b"network unavailable")
            return run(command, **kwargs)
        self.provider._runner = failed_fetch
        with self.assertRaises(HistoricalError) as raised:
            self.provider.read("f" * 40, "index.json")
        self.assertNotIsInstance(raised.exception, HistoricalFileMissing)
        fetches = [(command, kwargs) for command, kwargs in recorded if "fetch" in command]
        self.assertEqual(len(fetches), 1)
        command, kwargs = fetches[0]
        self.assertEqual(command[-2:], ["origin", "f" * 40])
        self.assertIn("--filter=blob:none", command)
        self.assertIn("--no-write-fetch-head", command)
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")
        self.assertEqual(kwargs["env"]["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertIn(SOURCE_URL, (self.provider.repository_path / "config").read_text())

    def test_successful_partial_fetch_then_exact_missing_blob_fetch_offline(self):
        self.git("config", "uploadpack.allowFilter", "true")
        self.git("config", "uploadpack.allowAnySHA1InWant", "true")
        fetched = []
        def local_transport(command, **kwargs):
            if "fetch" in command:
                fetched.append(command[-1])
                self.assertEqual(command[-2], "origin")
                # This test transport redirects only fetch to its temporary local
                # fixture. Production always uses the fixed HTTPS origin.
                command = command[:1] + ["-c", "protocol.file.allow=always"] + command[1:-2]
                command += [self.source.as_uri(), fetched[-1]]
            return subprocess.run(command, **kwargs)
        provider = HistoricalSources(self.root / "partial-cache", runner=local_transport)
        self.assertEqual(provider.read(self.revision, HTML_PATH), HTML.encode())
        blob = self.git("rev-parse", f"{self.revision}:{HTML_PATH}")
        self.assertEqual(fetched, [self.revision, blob])
        provider.read(self.revision, HTML_PATH)
        self.assertEqual(fetched, [self.revision, blob])

    def test_cache_configuration_or_symlink_tampering_rejected(self):
        config = self.provider.repository_path / "config"
        original = config.read_bytes()
        config.write_bytes(original + b'\n[include]\npath = /tmp/other-config\n')
        with self.assertRaisesRegex(HistoricalError, "configuration"):
            self.provider.read(self.revision, HTML_PATH)
        config.write_bytes(original)
        alternate = self.provider.repository_path / "objects/info/alternates"
        alternate.write_text(str(self.source / ".git/objects"))
        with self.assertRaisesRegex(HistoricalError, "alternates"):
            self.provider.read(self.revision, HTML_PATH)


if __name__ == "__main__":
    unittest.main()
