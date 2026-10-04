"""Read immutable English source objects without executing historical code.

Callers authorize revisions from a verified publication baseline or approved
source export. This module never resolves a branch, chooses another repository,
or substitutes current files when historical acquisition fails.
"""
from __future__ import annotations

import copy
from collections import OrderedDict
from contextlib import contextmanager
import fcntl
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Callable
import uuid


REPOSITORY = "trueChristian/berean-voice"
SOURCE_URL = f"https://github.com/{REPOSITORY}.git"
MAX_FILE_BYTES = 32_000_000
MAX_TREE_BYTES = 16_000_000
MAX_COMMIT_BYTES = 1_000_000
MAX_RECORDS = 100_000
MAX_CACHE_BYTES = 64_000_000
MAX_PARSED_REVISIONS = 8
ARTICLE_FIELDS = frozenset((
    "id", "issue_id", "sequence", "title", "subtitle", "section", "byline",
    "categories", "topics", "series", "images", "rights", "source_pages",
))
FINGERPRINT_FIELDS = frozenset((
    "html_sha256", "metadata_sha256", "text_sha256", "structure_sha256",
    "translation_metadata_sha256",
))
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CONFIG = f'''[core]
    repositoryformatversion = 1
    bare = true
[extensions]
    partialClone = origin
[remote "origin"]
    url = {SOURCE_URL}
    promisor = true
    partialclonefilter = blob:none
'''.encode("ascii")


class HistoricalError(ValueError):
    """Historical source acquisition or validation failed; do not fall back."""


class HistoricalFileMissing(HistoricalError):
    """A successfully verified pinned Git tree does not contain this path."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HistoricalError(message)


def _revision(value: str) -> str:
    _require(isinstance(value, str) and bool(_SHA.fullmatch(value)),
             "Historical source requires a full lowercase commit SHA")
    return value


def _identity(value: str) -> str:
    try:
        valid = isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        valid = False
    _require(valid, "Invalid historical source UUID")
    return value


def _path(value: str) -> str:
    _require(isinstance(value, str) and 0 < len(value) <= 1024,
             "Invalid historical source path")
    _require(not any(ord(char) < 32 or ord(char) == 127 for char in value)
             and "\\" not in value and not value.startswith("/")
             and all(part not in {"", ".", ".."} for part in value.split("/")),
             "Unsafe historical source path")
    if value in {"index.json", "catalogue.json"}:
        return value
    if value.startswith("content/articles/") and value.endswith(".html"):
        identity = value[len("content/articles/"):-len(".html")]
        _identity(identity)
        return value
    if value.startswith("public/images/articles/"):
        relative = value[len("public/images/articles/"):]
        _require(bool(relative) and all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", part)
                                      for part in relative.split("/")),
                 "Unsafe historical image path")
        return value
    raise HistoricalError("Disallowed historical source path")


def _canonical_hash(value: object) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise HistoricalError("Invalid historical canonical JSON") from error
    return hashlib.sha256(raw).hexdigest()


def _read_bytes(read: Callable[[str, str], bytes], revision: str, path: str) -> bytes:
    raw = read(revision, _path(path))
    _require(isinstance(raw, bytes) and len(raw) <= MAX_FILE_BYTES,
             "Historical source file exceeds bounds or is not bytes")
    return raw


def _json(raw: bytes, name: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, f"Duplicate historical JSON key in {name}")
            result[key] = value
        return result

    def constant(value):
        raise HistoricalError(f"Non-finite historical JSON value in {name}")

    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            constant(value)
        return parsed

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_constant=constant, parse_float=number)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise HistoricalError(f"Invalid historical {name}: {error}") from error
    _require(isinstance(result, dict) and result.get("format_version") == "2.0",
             f"Unsupported historical {name} format")
    return result


@lru_cache(maxsize=8)
def _catalogue(raw: bytes) -> dict:
    result = _json(raw, "catalogue")
    result.pop("normalization", None)
    result.pop("review_candidates", None)
    seen = set()
    for kind in ("issues", "categories", "topics", "series"):
        records = result.get(kind)
        _require(isinstance(records, list) and len(records) <= MAX_RECORDS,
                 f"Invalid historical catalogue {kind}")
        for record in records:
            _require(isinstance(record, dict), f"Malformed historical {kind} record")
            identity = _identity(record.get("id"))
            _require(identity not in seen, "Duplicate historical catalogue identity")
            seen.add(identity)
            for key in ("name", "slug", "publication", "publisher"):
                _require(key not in record or isinstance(record[key], str),
                         f"Malformed historical {kind} label")
            if kind == "issues":
                _require("date" not in record or isinstance(record["date"], dict),
                         "Malformed historical issue date")
    return result


def _validate_article(article: dict, groups: dict, *, frozen: bool = False) -> None:
    _require(isinstance(article, dict), "Malformed historical article")
    if frozen:
        _require(set(article) == ARTICLE_FIELDS, "Unexpected retained snapshot article fields")
    identity = _identity(article.get("id"))
    _require(isinstance(article.get("issue_id"), str) and article["issue_id"] in groups["issues"],
             "Missing historical article issue")
    _require(type(article.get("sequence")) is int and article["sequence"] > 0,
             "Invalid historical article sequence")
    for key in ("title", "subtitle", "section"):
        _require(article.get(key) is None or isinstance(article[key], str),
                 "Invalid historical article text metadata")
    _require(article.get("byline") is None or isinstance(article["byline"], dict),
             "Invalid historical article byline")
    _require(isinstance(article.get("source_pages"), dict), "Invalid historical article source pages")
    categories = article.get("categories")
    _require(isinstance(categories, dict) and isinstance(categories.get("primary"), str)
             and categories["primary"] in groups["categories"],
             "Missing historical primary category")
    additional, topics = categories.get("additional", []), article.get("topics", [])
    _require(isinstance(additional, list) and all(isinstance(value, str) and value in groups["categories"]
                                                for value in additional),
             "Missing historical additional category")
    _require(isinstance(topics, list) and all(isinstance(value, str) and value in groups["topics"]
                                            for value in topics), "Missing historical article topic")
    _require(len(set(additional)) == len(additional) and categories["primary"] not in additional
             and len(set(topics)) == len(topics), "Duplicate historical article grouping")
    series = article.get("series")
    _require(series is None or (isinstance(series, dict) and isinstance(series.get("id"), str)
                               and series["id"] in groups["series"]),
             "Missing historical article series")
    rights = article.get("rights")
    _require(isinstance(rights, dict) and rights.get("status") == "eligible"
             and rights.get("article_specific_permission_notice_detected") is False,
             "Historical article is not rights-eligible")
    images = article.get("images")
    _require(isinstance(images, list) and len(images) <= 1000, "Invalid historical image inventory")
    seen = set()
    for image in images:
        _require(isinstance(image, dict), "Invalid historical image metadata")
        repository_path = _path(image.get("repository_path"))
        _require(repository_path.startswith("public/images/articles/")
                 and image.get("public_path") == repository_path[len("public"):],
                 "Historical image paths disagree")
        _require(repository_path not in seen, "Duplicate historical image identity")
        seen.add(repository_path)
    if not frozen:
        _require(article.get("language") == "en" and isinstance(article.get("html"), dict)
                 and article["html"].get("repository_path") == f"content/articles/{identity}.html",
                 "Historical article language or HTML path disagrees")


@lru_cache(maxsize=8)
def _documents(index_raw: bytes, catalogue_raw: bytes) -> tuple[dict, dict, dict]:
    catalogue = _catalogue(catalogue_raw)
    groups = {kind: {item["id"]: item for item in catalogue[kind]}
              for kind in ("issues", "categories", "topics", "series")}
    index = _json(index_raw, "index")
    articles = index.get("articles")
    _require(isinstance(articles, list) and len(articles) <= MAX_RECORDS,
             "Invalid historical article index")
    seen = set().union(*(set(group) for group in groups.values()))
    result, sequences = {}, set()
    for article in articles:
        _validate_article(article, groups)
        identity = article["id"]
        _require(identity not in seen, "Duplicate historical article identity")
        seen.add(identity)
        position = article["issue_id"], article["sequence"]
        _require(position not in sequences, "Duplicate historical issue article sequence")
        sequences.add(position)
        public = copy.deepcopy(article)
        public.pop("verification", None)
        public.pop("source_labels", None)
        result[identity] = public
    return result, catalogue, groups


def _source_documents(revision: str, read: Callable[[str, str], bytes]):
    revision = _revision(revision)
    provider = getattr(read, "__self__", None)
    # Only this exact verified Git reader may reuse documents by commit alone.
    # Generic/injected readers can change bytes under the same claimed revision;
    # they must continue through the byte-keyed cache on every call.
    if (isinstance(provider, HistoricalSources)
            and getattr(read, "__func__", None) is HistoricalSources.read):
        return provider._source_documents(revision)
    return _documents(_read_bytes(read, revision, "index.json"),
                      _read_bytes(read, revision, "catalogue.json"))


def _html(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeError as error:
        raise HistoricalError("Historical article HTML is not UTF-8") from error


def verify_retained_source(spec: dict, expected_id: str, expected_revision: str,
                           read: Callable[[str, str], bytes]) -> dict:
    """Verify an approved exported snapshot against its pinned English objects.

    ``metadata_sha256`` fingerprints the original source metadata, not the
    normalized frozen article. The six-field snapshot digest binds that frozen
    article, original fingerprints and translation key to exact historical HTML.
    """
    identity, revision = _identity(expected_id), _revision(expected_revision)
    _require(isinstance(spec, dict), "Missing retained source specification")
    _require(spec.get("repository") == REPOSITORY and spec.get("revision") == revision
             and spec.get("article_id") == identity, "Retained source identity or revision mismatch")
    html_path = f"content/articles/{identity}.html"
    _require(spec.get("html_repository_path") == html_path
             and spec.get("index_repository_path") == "index.json"
             and spec.get("catalogue_repository_path") == "catalogue.json",
             "Retained source paths mismatch")
    for key in ("html_sha256", "snapshot_sha256", "translation_key"):
        _require(isinstance(spec.get(key), str) and bool(_DIGEST.fullmatch(spec[key])),
                 f"Invalid retained source {key}")
    fingerprints = spec.get("fingerprints")
    _require(isinstance(fingerprints, dict) and set(fingerprints) == FINGERPRINT_FIELDS,
             "Invalid retained source fingerprints")
    _require(all(isinstance(value, str) and _DIGEST.fullmatch(value) for value in fingerprints.values()),
             "Invalid retained source fingerprint digest")
    _require(spec.get("metadata_sha256", fingerprints["metadata_sha256"]) == fingerprints["metadata_sha256"],
             "Retained source metadata fingerprint mismatch")
    expected_key = _canonical_hash({key: fingerprints[key] for key in (
        "text_sha256", "structure_sha256", "translation_metadata_sha256")})
    _require(spec["translation_key"] == expected_key, "Retained source translation key mismatch")
    articles, catalogue, groups = _source_documents(revision, read)
    _require(identity in articles, "Retained article is absent from pinned source index")
    article = spec.get("article")
    _validate_article(article, groups, frozen=True)
    _require(article["id"] == identity, "Retained snapshot article identity mismatch")
    raw = _read_bytes(read, revision, html_path)
    digest = hashlib.sha256(raw).hexdigest()
    _require(digest == spec["html_sha256"] == fingerprints["html_sha256"],
             "Retained source HTML fingerprint mismatch")
    html = _html(raw)
    snapshot = {"article": article, "fingerprints": fingerprints, "html": html,
                "repository": REPOSITORY, "revision": revision,
                "translation_key": spec["translation_key"]}
    _require(_canonical_hash(snapshot) == spec["snapshot_sha256"],
             "Retained source snapshot checksum mismatch")
    public = copy.deepcopy(article)
    public.update(html={"repository_path": html_path}, language="en")
    return {"article": public, "html": html, "catalogue": copy.deepcopy(catalogue),
            "revision": revision}


class HistoricalSources:
    """A shared, credential-free partial Git cache for the fixed source repo.

    Every object is verified against its Git SHA-1 before use. Explicit fetches
    request only immutable object IDs; lazy fetch and all other protocols are
    disabled. Missing files are established by walking verified tree objects.
    ``runner`` exists only to make transport failures testable without network.
    """

    def __init__(self, cache_dir: Path, *, runner=None):
        self.cache_dir = Path(cache_dir).absolute()
        self.repository_path = self.cache_dir / "berean-voice.git"
        self._runner = runner or subprocess.run
        self._commits = {}
        self._trees = {}
        self._files = OrderedDict()
        self._cache_bytes = 0
        self._parsed_documents = OrderedDict()

    def _source_documents(self, revision: str) -> tuple[dict, dict, dict]:
        """Keep private parsed documents bound to this reader and pinned commit.

        Public article/catalogue/snapshot methods copy their returned metadata;
        this internal tuple is never exposed for a caller to mutate.
        """
        if revision not in self._parsed_documents:
            documents = _documents(_read_bytes(self.read, revision, "index.json"),
                                   _read_bytes(self.read, revision, "catalogue.json"))
            self._parsed_documents[revision] = documents
            while len(self._parsed_documents) > MAX_PARSED_REVISIONS:
                self._parsed_documents.popitem(last=False)
        self._parsed_documents.move_to_end(revision)
        return self._parsed_documents[revision]

    @staticmethod
    def _environment() -> dict:
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("GIT_") and key not in {"GH_TOKEN", "GITHUB_TOKEN"}}
        environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_SYSTEM=os.devnull,
                           GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_COUNT="0",
                           GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="/bin/false",
                           SSH_ASKPASS="/bin/false", GIT_NO_REPLACE_OBJECTS="1",
                           GIT_NO_LAZY_FETCH="1", GIT_LITERAL_PATHSPECS="1")
        return environment

    def _run(self, *args, data=None, initializing=False) -> bytes:
        command = ["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=",
                   "-c", "credential.interactive=false", "-c", "protocol.allow=never",
                   "-c", "protocol.https.allow=always", "-c", "http.followRedirects=false",
                   "-c", "http.extraHeader=", "-c", "gc.auto=0", "-c", "maintenance.auto=false"]
        if not initializing:
            command += ["--git-dir", str(self.repository_path)]
        try:
            completed = self._runner(command + list(args), input=data, capture_output=True,
                                     env=self._environment(), timeout=120, check=False)
        except (OSError, subprocess.SubprocessError) as error:
            raise HistoricalError("Historical Git access failed; no source substituted") from error
        _require(completed.returncode == 0,
                 "Historical Git command failed; no source substituted")
        _require(isinstance(completed.stdout, bytes)
                 and len(completed.stdout) <= MAX_FILE_BYTES + 1024,
                 "Historical Git output exceeds bounds")
        return completed.stdout

    @contextmanager
    def _locked(self):
        try:
            for parent in (self.cache_dir, *self.cache_dir.parents):
                _require(not parent.is_symlink(), "Historical cache cannot contain symlinks")
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            lock_path = self.cache_dir / ".historical-source.lock"
            _require(not lock_path.is_symlink(), "Historical cache lock cannot be a symlink")
            with lock_path.open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                self._initialize()
                yield
        except OSError as error:
            raise HistoricalError("Historical cache access failed; no source substituted") from error

    def _initialize(self):
        path = self.repository_path
        _require(not path.is_symlink(), "Historical Git cache cannot be a symlink")
        if not path.exists():
            self._run("init", "--bare", "--template=", "--object-format=sha1", str(path),
                      initializing=True)
            (path / "config").write_bytes(_CONFIG)
        for relative in ("config", "objects", "objects/info", "objects/pack"):
            _require(not (path / relative).is_symlink(), "Historical cache contains a symlink")
        _require(path.is_dir() and (path / "config").is_file()
                 and (path / "config").read_bytes() == _CONFIG,
                 "Historical Git cache configuration is untrusted")
        _require(not (path / "objects/info/alternates").exists()
                 and not (path / "objects/info/http-alternates").exists(),
                 "Historical Git object alternates are forbidden")

    def _fetch(self, identity: str):
        self._run("fetch", "--no-tags", "--no-recurse-submodules", "--no-auto-maintenance",
                  "--no-write-fetch-head", "--depth=1", "--filter=blob:none", "origin", identity)

    def _object(self, identity: str, kind: str, limit: int) -> bytes:
        _revision(identity)
        def information():
            return self._run("cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                             data=(identity + "\n").encode("ascii"))
        information_raw = information()
        if information_raw == f"{identity} missing\n".encode("ascii"):
            self._fetch(identity)
            information_raw = information()
        match = re.fullmatch(rb"([0-9a-f]{40}) (blob|tree|commit|tag) ([0-9]+)\n", information_raw)
        _require(match is not None and match[1].decode() == identity and match[2].decode() == kind,
                 "Historical Git object type or identity mismatch")
        size = int(match[3])
        _require(size <= limit, "Historical Git object exceeds size limit")
        raw = self._run("cat-file", kind, identity)
        actual = hashlib.sha1(f"{kind} {len(raw)}\0".encode("ascii") + raw).hexdigest()
        _require(len(raw) == size and actual == identity, "Historical Git object checksum mismatch")
        return raw

    def _commit_tree(self, revision: str) -> str:
        if revision not in self._commits:
            raw = self._object(revision, "commit", MAX_COMMIT_BYTES)
            match = re.match(rb"tree ([0-9a-f]{40})\n", raw)
            _require(match is not None, "Malformed historical commit tree")
            self._commits[revision] = match[1].decode("ascii")
        return self._commits[revision]

    def _tree(self, identity: str) -> dict:
        if identity not in self._trees:
            raw = self._object(identity, "tree", MAX_TREE_BYTES)
            entries, offset = {}, 0
            while offset < len(raw):
                space, end = raw.find(b" ", offset), raw.find(b"\0", offset)
                _require(offset < space < end and end + 21 <= len(raw),
                         "Malformed historical Git tree")
                mode, name = raw[offset:space], raw[space + 1:end]
                _require(name and b"/" not in name and name not in {b".", b".."}
                         and name not in entries, "Invalid or duplicate historical Git tree entry")
                entries[name] = (mode, raw[end + 1:end + 21].hex())
                offset = end + 21
            self._trees[identity] = entries
        return self._trees[identity]

    def read(self, revision: str, repository_path: str) -> bytes:
        revision, repository_path = _revision(revision), _path(repository_path)
        key = revision, repository_path
        if key in self._files:
            self._files.move_to_end(key)
            return self._files[key]
        with self._locked():
            tree = self._commit_tree(revision)
            parts = repository_path.split("/")
            for index, part in enumerate(parts):
                entry = self._tree(tree).get(part.encode("utf-8"))
                if entry is None:
                    raise HistoricalFileMissing(f"Missing pinned source file: {revision}:{repository_path}")
                mode, identity = entry
                final = index == len(parts) - 1
                _require(mode in ({b"100644", b"100755"} if final else {b"40000"}),
                         "Historical source path is a symlink or non-regular file")
                if final:
                    raw = self._object(identity, "blob", MAX_FILE_BYTES)
                    self._files[key] = raw
                    self._cache_bytes += len(raw)
                    while self._cache_bytes > MAX_CACHE_BYTES:
                        _, evicted = self._files.popitem(last=False)
                        self._cache_bytes -= len(evicted)
                    return raw
                tree = identity
        raise HistoricalError("Invalid historical source file")

    def catalogue(self, revision: str) -> dict:
        revision = _revision(revision)
        return copy.deepcopy(_catalogue(_read_bytes(self.read, revision, "catalogue.json")))

    def article(self, revision: str, identity: str) -> dict:
        revision, identity = _revision(revision), _identity(identity)
        articles, catalogue, _ = _source_documents(revision, self.read)
        _require(identity in articles, "Historical article is absent from pinned source index")
        article = articles[identity]
        html = _html(_read_bytes(self.read, revision, article["html"]["repository_path"]))
        return {"article": copy.deepcopy(article), "html": html,
                "catalogue": copy.deepcopy(catalogue), "revision": revision}
