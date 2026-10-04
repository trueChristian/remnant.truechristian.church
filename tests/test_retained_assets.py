"""Offline contracts for immutable reader images and their publication provenance."""
import copy
import hashlib
from html import escape
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from scripts.historical_source import HistoricalError, HistoricalFileMissing
from scripts.retained_assets import pin_article_assets


CURRENT = "c" * 40
ORIGINAL = "a" * 40
INTERMEDIATE = "b" * 40
IMAGE = "/images/articles/article-1.jpg"
OLD_BYTES = b"original published image\x00\xff"
NEW_BYTES = b"later image at the same public URL\x00\xfe"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def immutable_url(raw, original=IMAGE):
    return "/images/articles/retained/" + digest(raw) + "/" + original[len("/images/articles/"):]


def origin(raw=OLD_BYTES, revision=ORIGINAL, public_path=None, original=IMAGE):
    return {"revision": revision, "repository_path": "public" + original,
            "sha256": digest(raw), "public_path": public_path or immutable_url(raw, original)}


def article(html=None, public_path=IMAGE):
    image = {"public_path": public_path, "alt": "Original photograph",
             "caption": "Original caption, café.", "credit": "Photo © Printed Name"}
    return {
        "id": "00000000-0000-4000-8000-000000000001",
        "title": "Original article title",
        "byline": {"raw": "Printed Author"},
        "html": html if html is not None else (
            '<article>\r\n<p>Exact words, café &amp; faith.</p>\r\n'
            '<figure><img src="' + escape(public_path, quote=True) + '" alt="Original photograph">'
            '<figcaption>Original caption, café. <small>Photo © Printed Name</small></figcaption>'
            '</figure>\r\n</article>\r\n'),
        "images": [image], "image": copy.deepcopy(image),
    }


class RetainedAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.current = self.root / "current"
        self.current.mkdir()
        self.cache = self.root / "cache"
        self.historical_files = {(ORIGINAL, "public" + IMAGE): OLD_BYTES}
        self.read_historical = Mock(side_effect=self.read)

    def read(self, revision, path):
        try:
            return self.historical_files[revision, path]
        except KeyError:
            raise HistoricalFileMissing(path) from None

    def write_current(self, raw=NEW_BYTES, public_path=IMAGE, public_directory=False):
        path = self.current / ("public" if public_directory else "") / public_path.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def pin(self, value=None, **kwargs):
        options = dict(current_root=self.current, current_revision=CURRENT,
                       read_historical=self.read_historical, cache_dir=self.cache,
                       retained=True, fallback_revisions=(ORIGINAL,))
        options.update(kwargs)
        return pin_article_assets(article() if value is None else value, **options)

    def copied_bytes(self, result):
        copies = result["copies"]
        self.assertEqual(len(copies), len({item["public_path"] for item in copies}))
        for item in copies:
            self.assertEqual(digest(Path(item["source"]).read_bytes()), item["sha256"])
        return {item["public_path"]: Path(item["source"]).read_bytes() for item in copies}

    def test_current_publication_keeps_exact_html_and_current_origin(self):
        self.write_current()
        original = article()
        before = copy.deepcopy(original)
        result = self.pin(original, retained=False)
        expected = origin(NEW_BYTES, CURRENT, IMAGE)
        self.assertEqual(result["article"]["html"], original["html"])
        self.assertEqual(result["article"]["images"], original["images"])
        self.assertEqual(result["origins"], {IMAGE: expected})
        self.assertEqual(result["aliases"], {IMAGE: expected})
        self.assertEqual(result["article"]["asset_origins"], result["origins"])
        self.assertEqual(result["copies"], [])
        self.assertEqual(original, before)
        self.assertFalse(self.cache.exists())
        self.read_historical.assert_not_called()

    def test_html_offsets_count_only_line_feeds_and_preserve_unicode_prose(self):
        for separator in ('\r', '\u2028', '\u2029', '\v', '\f', '\x85', '\r\n'):
            with self.subTest(separator=repr(separator)):
                prefix = '<p>First' + separator + 'line</p>\n'
                source = prefix + '<img src="' + IMAGE + '" alt="photo">'
                result = self.pin(article(html=source))
                self.assertEqual(result['article']['html'],
                    prefix + '<img src="' + immutable_url(OLD_BYTES) + '" alt="photo">')

    def test_current_publication_rejects_missing_image_without_history_substitution(self):
        with self.assertRaisesRegex(ValueError, "Current publication image is absent"):
            self.pin(retained=False)
        self.read_historical.assert_not_called()

    def test_changed_current_image_keeps_original_url_bytes_and_pins_old_reader_bytes(self):
        current_path = self.write_current()
        original = article()
        before = copy.deepcopy(original)
        result = self.pin(original, prior_origins={IMAGE: origin()})
        target = immutable_url(OLD_BYTES)
        self.assertEqual(self.copied_bytes(result), {target: OLD_BYTES})
        self.assertEqual(current_path.read_bytes(), NEW_BYTES)
        self.assertEqual(result["article"]["html"], original["html"].replace(IMAGE, target))
        self.assertEqual(result["article"]["image"]["public_path"], target)
        self.assertEqual(result["origins"], {IMAGE: origin()})
        self.assertEqual(result["aliases"], {})
        self.assertEqual(original, before)
        self.read_historical.assert_called_once_with(ORIGINAL, "public" + IMAGE)

    def test_removed_image_restores_immutable_and_original_url_copies(self):
        result = self.pin(prior_origins={IMAGE: origin()})
        self.assertEqual(self.copied_bytes(result), {immutable_url(OLD_BYTES): OLD_BYTES, IMAGE: OLD_BYTES})
        self.assertEqual(result["origins"], {IMAGE: origin()})
        self.assertEqual(result["aliases"], {IMAGE: origin(public_path=IMAGE)})
        self.assertFalse((self.current / IMAGE.lstrip("/")).exists())

    def test_original_url_alias_retains_its_separate_latest_served_bytes(self):
        self.historical_files[INTERMEDIATE, "public" + IMAGE] = NEW_BYTES
        alias = origin(NEW_BYTES, INTERMEDIATE, IMAGE)
        result = self.pin(prior_origins={IMAGE: origin()}, prior_aliases={IMAGE: alias})
        self.assertEqual(self.copied_bytes(result), {immutable_url(OLD_BYTES): OLD_BYTES, IMAGE: NEW_BYTES})
        self.assertEqual(result["origins"], {IMAGE: origin()})
        self.assertEqual(result["aliases"], {IMAGE: alias})
        self.assertEqual(self.read_historical.call_args_list,
                         [unittest.mock.call(ORIGINAL, "public" + IMAGE),
                          unittest.mock.call(INTERMEDIATE, "public" + IMAGE)])

    def test_prior_origin_digest_mismatch_never_falls_back_to_current_or_other_revision(self):
        self.write_current()
        self.historical_files[ORIGINAL, "public" + IMAGE] = b"corrupted prior bytes"
        with self.assertRaisesRegex(ValueError, "recorded origin"):
            self.pin(prior_origins={IMAGE: origin()}, fallback_revisions=(INTERMEDIATE,))
        self.read_historical.assert_called_once_with(ORIGINAL, "public" + IMAGE)
        self.assertFalse(self.cache.exists())

    def test_prior_origin_missing_is_fatal_even_when_other_sources_have_image(self):
        self.write_current()
        self.historical_files.clear()
        self.historical_files[INTERMEDIATE, "public" + IMAGE] = NEW_BYTES
        with self.assertRaises(HistoricalFileMissing):
            self.pin(prior_origins={IMAGE: origin()}, fallback_revisions=(INTERMEDIATE,))
        self.read_historical.assert_called_once_with(ORIGINAL, "public" + IMAGE)

    def test_prior_alias_digest_mismatch_is_fatal(self):
        self.historical_files[INTERMEDIATE, "public" + IMAGE] = b"corrupted alias"
        with self.assertRaisesRegex(ValueError, "alias digest mismatch"):
            self.pin(prior_origins={IMAGE: origin()},
                     prior_aliases={IMAGE: origin(NEW_BYTES, INTERMEDIATE, IMAGE)})

    def test_prior_alias_read_failure_is_fatal(self):
        for error in (HistoricalFileMissing("alias removed"), HistoricalError("alias unavailable"),
                      PermissionError("alias denied")):
            with self.subTest(error=type(error).__name__):
                reader = Mock(side_effect=[OLD_BYTES, error])
                with self.assertRaises(type(error)):
                    self.pin(read_historical=reader, prior_origins={IMAGE: origin()},
                             prior_aliases={IMAGE: origin(NEW_BYTES, INTERMEDIATE, IMAGE)})
                self.assertEqual(reader.call_count, 2)

    def test_verified_missing_history_advances_to_next_known_source_in_order(self):
        self.write_current()
        result = self.pin(fallback_revisions=(INTERMEDIATE, INTERMEDIATE, ORIGINAL, CURRENT))
        self.assertEqual(result["origins"][IMAGE], origin())
        self.assertEqual(self.copied_bytes(result), {immutable_url(OLD_BYTES): OLD_BYTES})
        self.assertEqual(self.read_historical.call_args_list,
                         [unittest.mock.call(INTERMEDIATE, "public" + IMAGE),
                          unittest.mock.call(ORIGINAL, "public" + IMAGE)])

    def test_only_verified_missing_history_allows_current_image_with_truthful_current_origin(self):
        self.write_current()
        self.historical_files.clear()
        result = self.pin(fallback_revisions=(ORIGINAL, INTERMEDIATE))
        self.assertEqual(result["origins"], {IMAGE: origin(NEW_BYTES, CURRENT)})
        self.assertEqual(self.copied_bytes(result), {immutable_url(NEW_BYTES): NEW_BYTES})
        self.assertEqual(self.read_historical.call_count, 2)

    def test_retained_image_cannot_use_current_without_any_verified_historical_lookup(self):
        self.write_current()
        with self.assertRaises(ValueError):
            self.pin(fallback_revisions=())
        self.read_historical.assert_not_called()

    def test_absent_history_and_current_image_rejects_publication(self):
        self.historical_files.clear()
        with self.assertRaisesRegex(ValueError, "No verified historical or current copy"):
            self.pin()
        self.assertFalse(self.cache.exists())

    def test_denial_network_and_corruption_never_advance_or_use_current_bytes(self):
        self.write_current()
        for error in (HistoricalError("network unavailable"), PermissionError("access denied"),
                      HistoricalError("blob checksum mismatch"), OSError("connection reset")):
            with self.subTest(error=str(error)):
                reader = Mock(side_effect=error)
                with self.assertRaises(type(error)) as raised:
                    self.pin(read_historical=reader, fallback_revisions=(ORIGINAL, INTERMEDIATE))
                self.assertIs(raised.exception, error)
                reader.assert_called_once_with(ORIGINAL, "public" + IMAGE)
                self.assertFalse(self.cache.exists())

    def test_missing_then_unavailable_history_does_not_bypass_unavailable_source(self):
        self.write_current()
        denied = PermissionError("second historical source denied")
        reader = Mock(side_effect=[HistoricalFileMissing("missing"), denied, OLD_BYTES])
        with self.assertRaises(PermissionError) as raised:
            self.pin(read_historical=reader, fallback_revisions=(INTERMEDIATE, ORIGINAL, CURRENT))
        self.assertIs(raised.exception, denied)
        self.assertEqual(reader.call_count, 2)

    def test_exact_prose_markup_captions_credits_and_non_source_attributes_are_preserved(self):
        variants = (
            'src="' + IMAGE + '"', "src='" + IMAGE + "'", "src=" + IMAGE,
            'SRC \t= \"' + IMAGE + '\"', 'src="/images/articles/article&#45;1.jpg"',
        )
        for source_attribute in variants:
            with self.subTest(source_attribute=source_attribute):
                prefix = ('<!doctype html>\r\n<article><!-- exact src="irrelevant" -->\r\n'
                          '<p data-note="src=literal">Café &amp; <em>faith</em>\r\n stays.</p>\r\n'
                          '<figure class=original><IMG ALT="A literal src=\'inside-alt\' caption"\n  ')
                suffix = (' loading=lazy data-credit="Photo © Printed Name" />'
                          '<figcaption>Original <i>caption</i>. Photo © Printed Name.</figcaption>'
                          '</figure>\r\n</article>\r\n')
                original = article(prefix + source_attribute + suffix)
                before = copy.deepcopy(original)
                result = self.pin(original)
                expected = prefix + 'src="' + immutable_url(OLD_BYTES) + '"' + suffix
                self.assertEqual(result["article"]["html"], expected)
                expected_image = dict(original["images"][0], public_path=immutable_url(OLD_BYTES))
                self.assertEqual(result["article"]["images"], [expected_image])
                self.assertEqual(result["article"]["byline"], original["byline"])
                self.assertEqual(result["article"]["title"], original["title"])
                self.assertEqual(original, before)

    def test_duplicate_reused_images_keep_each_caption_and_credit_and_share_one_verified_copy(self):
        original = article('<p>Before.</p><img src="' + IMAGE + '"><p>Between.</p>'
                           '<IMG alt="src=literal" SRC="' + IMAGE + '"><p>After.</p>')
        second = dict(original["images"][0], caption="Second printed caption", credit="Second credit")
        original["images"].append(second)
        result = self.pin(original)
        target = immutable_url(OLD_BYTES)
        self.assertEqual(result["article"]["html"], '<p>Before.</p><img src="' + target + '">'
                         '<p>Between.</p><IMG alt="src=literal" src="' + target + '"><p>After.</p>')
        self.assertEqual(result["article"]["images"],
                         [dict(item, public_path=target) for item in original["images"]])
        self.assertEqual(self.copied_bytes(result), {target: OLD_BYTES, IMAGE: OLD_BYTES})
        self.read_historical.assert_called_once_with(ORIGINAL, "public" + IMAGE)

    def test_unsafe_image_paths_rejected_before_read_or_cache_write(self):
        invalid_paths = (
            "https://example.test" + IMAGE, "//example.test" + IMAGE, "/images/other/image.jpg",
            "/images/articles/../secret.jpg", "/images/articles/%2e%2e/secret.jpg",
            "/images/articles/nested%2f..%2fsecret.jpg", "/images/articles//image.jpg",
            "/images/articles/./image.jpg", "/images/articles/image.jpg?x=1",
            "/images/articles/image.jpg#fragment", "/images/articles/image%00.jpg",
            "/images/articles/image\n.jpg", "/images/articles/a%5cb.jpg",
        )
        for path in invalid_paths:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.pin(article(public_path=path))
        self.read_historical.assert_not_called()
        self.assertFalse(self.cache.exists())

    def test_bad_prior_provenance_rejected_before_historical_read(self):
        changes = ({"revision": "main"}, {"revision": "A" * 40}, {"sha256": "0" * 63},
                   {"repository_path": "public/images/articles/different.jpg"},
                   {"public_path": "/images/articles/../image.jpg"}, {"unexpected": "field"})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.pin(prior_origins={IMAGE: origin() | change})
        self.read_historical.assert_not_called()

    def test_current_export_supports_public_root_layout_without_changing_origin(self):
        path = self.write_current(public_directory=True)
        result = self.pin(retained=False)
        self.assertEqual(result["origins"], {IMAGE: origin(NEW_BYTES, CURRENT, IMAGE)})
        self.assertEqual(path.read_bytes(), NEW_BYTES)

    def test_symlink_current_file_and_directory_are_rejected(self):
        outside = self.root / "outside.jpg"
        outside.write_bytes(NEW_BYTES)
        image = self.write_current()
        image.unlink()
        image.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.pin()
        image.unlink()
        image.parent.rmdir()
        image.parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.pin()
        self.read_historical.assert_not_called()

    def test_symlink_current_root_is_rejected(self):
        root_link = self.root / "linked-export"
        root_link.symlink_to(self.current, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.pin(current_root=root_link)
        self.read_historical.assert_not_called()

    def test_symlink_ancestor_of_export_root_is_rejected(self):
        self.write_current()
        link = self.root / "linked-parent"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.pin(current_root=link / "current", retained=False)

    def test_symlink_ancestor_of_cache_root_is_rejected_before_writing_outside_cache(self):
        outside = self.root / "outside-cache-parent"
        outside.mkdir()
        link = self.root / "linked-cache-parent"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.pin(cache_dir=link / "cache")
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlink_cache_root_and_cached_file_are_rejected(self):
        outside = self.root / "outside-cache"
        outside.mkdir()
        self.cache.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.pin()
        self.cache.unlink()
        self.cache.mkdir()
        external_image = outside / "image.jpg"
        external_image.write_bytes(OLD_BYTES)
        (self.cache / digest(OLD_BYTES)).symlink_to(external_image)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.pin()

    def test_corrupt_cached_bytes_are_rejected_without_overwriting_evidence(self):
        self.cache.mkdir()
        cached = self.cache / digest(OLD_BYTES)
        cached.write_bytes(b"corrupted existing cache")
        with self.assertRaisesRegex(ValueError, "cache digest mismatch"):
            self.pin()
        self.assertEqual(cached.read_bytes(), b"corrupted existing cache")

    def test_duplicate_or_absent_img_source_is_rejected(self):
        for html in ('<img src="' + IMAGE + '" SRC="' + IMAGE + '">', '<img alt="missing">'):
            with self.subTest(html=html), self.assertRaisesRegex(ValueError, "exactly one source"):
                self.pin(article(html))


if __name__ == "__main__":
    unittest.main()
