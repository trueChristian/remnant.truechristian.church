"""Independent, tiny regressions for retained asset URLs and frozen RSS sources."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import unquote
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build import ORIGIN, Site
from check_site import SiteChecker
from content import ContentError, load_content
from retained_assets import pin_article_assets
from retention import copy_retained_assets, validate_published_assets


A = "00000000-0000-4000-8000-000000000001"
I = "00000000-0000-4000-8000-000000000002"
C = "00000000-0000-4000-8000-000000000003"
CURRENT, ORIGINAL = "b" * 40, "a" * 40
RAW = b"verified original image\x00\xff"


class RetentionReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def pinned_image(self, original):
        current = self.root / "english"
        current.mkdir(exist_ok=True)
        def read(revision, path):
            self.assertEqual(revision, ORIGINAL)
            self.assertEqual(path, "public" + unquote(original, errors="strict"))
            return RAW
        return pin_article_assets(
            {"html": '<article><img src="' + original + '" alt="Original"></article>',
             "images": [{"public_path": original, "alt": "Original"}]},
            current_root=current, current_revision=CURRENT, read_historical=read,
            cache_dir=self.root / "cache", retained=True, fallback_revisions=[ORIGINAL],
        )

    def test_percent_encoded_retained_images_and_original_aliases_are_packaged_for_browser_paths(self):
        for original in ("/images/articles/article%2D1.jpg",
                         "/images/articles/group%2Farticle-2.jpg"):
            with self.subTest(original=original):
                pinned = self.pinned_image(original)
                output = self.root / "dist"
                copy_retained_assets(output, pinned["copies"])
                for asset in pinned["copies"]:
                    browser_path = output / unquote(asset["public_path"], errors="strict").lstrip("/")
                    self.assertEqual(browser_path.read_bytes(), RAW)
                    self.assertEqual(hashlib.sha256(browser_path.read_bytes()).hexdigest(), asset["sha256"])
                    self.assertFalse((output / asset["public_path"].lstrip("/")).exists())
                self.assertEqual(pinned["aliases"][original]["public_path"], original)
                validate_published_assets(output, {
                    "aliases": pinned["aliases"], "images": {"en": {A: pinned["origins"]}},
                })

    def test_percent_encoded_copy_cannot_overwrite_a_distinct_current_file_at_decoded_path(self):
        pinned = self.pinned_image("/images/articles/article%2D1.jpg")
        alias = next(asset for asset in pinned["copies"]
                     if asset["public_path"] == "/images/articles/article%2D1.jpg")
        output = self.root / "dist"
        current = output / "images/articles/article-1.jpg"
        current.parent.mkdir(parents=True)
        current.write_bytes(b"different current source image")
        with self.assertRaisesRegex(ValueError, "replace different current source bytes"):
            copy_retained_assets(output, [alias])
        self.assertEqual(current.read_bytes(), b"different current source image")
        self.assertFalse((output / alias["public_path"].lstrip("/")).exists())

    def test_rss_cites_retained_issue_metadata_when_current_issue_keeps_same_uuid(self):
        # Exercise only the RSS method. No site pages, browser, network or full
        # archive build is needed to prove which issue metadata reaches readers.
        old_issue = {"id": I, "publication": "Original magazine name",
                     "date": {"year": 2020, "precision": "year"}}
        current_issue = {"id": I, "publication": "Current renamed magazine",
                         "date": {"year": 2026, "precision": "year"}}
        article = {"id": A, "issue_id": I, "issue": old_issue, "title": "Retained title",
                   "url": "/af/articles/retained-title/", "excerpt": "Original translated words.",
                   "retention": {"status": "stale", "source_revision": ORIGINAL}}
        site = Site.__new__(Site)
        site.locales = {"af": json.loads((ROOT / "locales/af.json").read_bytes())}
        site.articles = {"af": [article]}
        site.issue_map = {I: current_issue}
        site.routes = {"issues": {"af": {I: "/af/issues/original-edition/"}}}
        site.output, site.written = self.root / "dist", set()
        site.rss("af")
        feed = ET.parse(site.output / "af/feed.xml")
        citation = feed.find("channel/item/source")
        self.assertEqual(citation.text, "Original magazine name · 2020")
        self.assertEqual(citation.get("url"), ORIGIN + "/af/issues/original-edition/")
        self.assertNotIn("Current renamed magazine", (site.output / "af/feed.xml").read_text())
        checker = SiteChecker(site.output)
        checker.check_rss("af", [article], site.issue_map, site.routes["issues"]["af"],
                          "Untitled", locale=site.locales["af"])
        self.assertEqual(checker.errors, [])
        citation.text = "Current renamed magazine · 2026"
        feed.write(site.output / "af/feed.xml", encoding="unicode")
        checker.check_rss("af", [article], site.issue_map, site.routes["issues"]["af"],
                          "Untitled", locale=site.locales["af"])
        self.assertTrue(any("citation differs from recorded source" in error for error in checker.errors))

    def test_consumed_current_image_cannot_be_omitted_from_verified_export_inventory(self):
        english = self.root / "english"
        image_path = "images/articles/original.jpg"
        html_path = f"content/articles/{A}.html"
        article = {"id": A, "issue_id": I, "sequence": 1, "title": "Source title",
                   "subtitle": None, "section": "", "byline": {"raw": "Printed Author"},
                   "source_pages": {"start": 1, "end": 1}, "topics": [],
                   "categories": {"primary": C, "additional": []}, "language": "en",
                   "html": {"repository_path": html_path},
                   "images": [{"public_path": "/" + image_path, "alt": "Original"}]}
        index = {"format_version": "2.0", "export": {"source_revision": CURRENT},
                 "articles": [article]}
        catalogue = {"format_version": "2.0", "issues": [{"id": I, "publication": "Magazine"}],
                     "categories": [{"id": C, "name": "Category"}], "topics": [], "series": []}
        files = {"index.json": json.dumps(index).encode(),
                 "catalogue.json": json.dumps(catalogue).encode(), image_path: RAW,
                 html_path: (f'<article data-article-id="{A}"><img src="/{image_path}" '
                             'alt="Original"></article>').encode()}
        for name, raw in files.items():
            path = english / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        manifest = {"format_version": "2.0", "base_path": "/", "source_revision": CURRENT,
                    "counts": {"articles": 1},
                    "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}}
        manifest_path = english / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        self.assertEqual(load_content(english)["articles"]["en"][0]["id"], A)
        del manifest["files"][image_path]
        manifest_path.write_text(json.dumps(manifest))
        (english / image_path).write_bytes(b"unverified replacement bytes")
        with self.assertRaisesRegex(ContentError, "file inventory"):
            load_content(english)


if __name__ == "__main__":
    unittest.main()
