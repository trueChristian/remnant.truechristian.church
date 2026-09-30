# Display exports, stable routes and reader Markdown

## Data ownership and supported export boundary

The site consumes the English archive's **display export**, never its ingestion
records, skipped-article audit, or legacy generated root files. The English
exporter validates the inventory, semantic fragments, catalogue relationships,
rights gate and shared images before producing a checksum-indexed bundle. The
translation exporter performs its own fresh fingerprint scan against the exact
selected clean English checkout, then includes only compatible publications.
Human review is optional: ready unreviewed articles publish with the supplied AI
notice; removing that notice is the translation repository's review workflow.

Run the supported commands from each source checkout, with separate absent/empty
output directories:

```sh
python3 tools/archive.py export --output /path/to/site/.build/english --base /
python3 -m berean_translation export \
  --source-checkout /path/to/english-checkout \
  --output /path/to/site/.build/translations --base /
```

`scripts/export_sources.py` orchestrates exactly these commands. It uses only
Python's standard library, does not install or invoke an AI SDK, and never starts
translation work. The export entry point in the translation repository itself
can run without installing the optional paid worker's dependencies.

```sh
python3 scripts/export_sources.py \
  --english-checkout ../berean-voice \
  --translation-checkout ../berean-translation \
  --english-output .build/english \
  --translation-output .build/translations \
  --report .build/export-report.json
```

Outputs must be absent or empty. No previous translation directory is accepted as
a fallback. English export failure is fatal; translation checkout/export failure
produces an explicit English-only report and leaves English publishable. Any
partial translation output is quarantined under a hidden build-only path, leaving
the expected translation input absent. Use
`--strict-translations` only when intentionally testing the translation integration.
Detailed error reports stay in private build evidence; expose only a safe status
summary in the public site. A consumer must check `translation_status` and must
not consume an output explicitly marked `translation_output_usable: false`.

## Adapter API

```python
from pathlib import Path
from scripts.content import load_content, ordered_issues
model = load_content(Path('.build/english'), Path('.build/translations'))
```

`model['articles']` maps URL BCP-47 language tags to available articles. All
catalogue categories/issues/topics/series retain their source UUIDs and metadata.
The UI, not the content adapter, is responsible for offering every configured
locale and empty categories. Articles retain the full exported English metadata
under `source_metadata`; ordinary fields remain directly accessible. `html_source`
retains the original HTML path metadata; `html` is the complete display fragment.
`html` is never parsed and reserialized, so the exact translation notice remains
unchanged. `translation` contains only the already-public exported translation
metadata, not processing state.

The normalized article includes:

- `locale`, `direction`, `title`, `subtitle`, `section`
- `byline`, `source_pages`, `categories`, `topics`, optional `series`
- `issue`: the original issue record, without invented issue numbers or PDF URLs
- `html`: exact exported fragment; `text`: public article text without its notice
- `excerpt`: a verbatim whitespace-normalized prefix with an ellipsis when cut
- `images`: original metadata/credits joined with display HTML alt text/captions
- `image`: first image metadata record, or `None`
- `human_reviewed` and `ai_notice_required`

All manifest-listed checksums are verified before reading. English validation
failure raises `ContentError`. Translation validation failure discards the entire
invalid bundle, returns current English, sets `translation_status='failed'` and
adds an actionable warning. `strict_translations=True` instead raises. An absent
translation bundle is explicitly `unavailable`. No stale translations are reused.

Compare the **export-level** translation `source_revision` with the English
export's revision. Do not require each publication's historical translation
revision to match current English HEAD: compatible articles correctly retain
older per-publication provenance. The supported exporter is the authority for
translation-key compatibility.

`ordered_issues(model)` sorts by structured year, then month-range endpoint or
bibliographic seasonal order (Winter, Spring, Summer, Autumn/Fall), preserving
catalogue order for equal/unknown periods. Year-only entries follow entries with
known periods in the same year. These are ordering keys, not publication dates.
The source date objects are unchanged. This handles the current catalogue's
Autumn 2024 entry, which appears later in the source array than older issues.
Article lists follow that issue order, then their source sequence and UUID.

## Route API and persistence

```python
from scripts.routes import initialize_routes
routes = initialize_routes(model, locales, Path('data/routes.json'))
```

`locales` may be a mapping of language tags to locale dictionaries or an iterable
of tags. A locale dictionary's `categories[uuid]['slug']` is used only when that
category first enters the registry. Article/category/issue maps use
`routes[kind][locale][uuid]`; `routes['redirects']` maps old paths to canonical
paths. `article_url`, `category_url` and `issue_url` are lookup helpers.
Published article dictionaries receive `url`, `compatibility_url` and
`markdown_url`. Markdown routes always use `/<locale>/articles/<uuid>.md`.
The existing English-notice URL `/<locale>/articles/<uuid>/` redirects to the
canonical article path.

`data/routes.json` is the committed website-owned identity registry, not an
export from either content repository. Every initially published article has a
persisted localized title alias. Group paths and the canonical article's original
primary-category path are frozen by UUID: title corrections, category renaming,
and grouping moves cannot silently change shared URLs. Current category pages
and breadcrumbs may reflect an updated editorial grouping while its established
article address stays stable. A deliberate category-path migration uses the same
explicit history mechanism as an alias change.

New English publications must not wait for a registry-maintenance commit. In a
normal read-only build, an unknown article uses `article-<full-uuid>` as its alias,
which is independent of its mutable title. Redirects from that fallback under
**every known category** preserve links through category moves even before its
record is synchronized. The build returns the candidate registry as
`routes['registry']` and lists additions in `routes['pending']`; publish the safe
registry map as a synchronization artifact. A later reviewed maintenance change
can import that map into `data/routes.json` and explicitly select a readable
alias. No automatic repository write or credential is required for publication.

To bootstrap new readable aliases in a development checkout, pass `update=True`.
This writes the registry atomically. It never replaces existing aliases. Review
and commit the resulting file. If a UUID fallback has already published, import
its published registry record first so all fallback redirects survive promotion.

For an intentional migration:

```python
from scripts.routes import set_article_alias
set_article_alias(registry, 'af', article_uuid, 'approved-new-alias')
# Optional category_slug= selects a deliberate canonical-category migration.
# Write the registry, rebuild, review collision tests, then commit it.
```

Every previous path remains in `history`; the helper also adds every possible
UUID fallback route when promoting a fallback record. Retired article aliases
remain reserved and cannot be reassigned to another UUID. Removed articles are
not republished by the existence of a registry entry. New slug collisions use the
full UUID, Unicode scripts remain readable, and reserved namespaces or conflicting
manual histories fail validation before publishing.

## Markdown fidelity

`generate_markdown(article, canonical_url, issue_label)` emits UTF-8 Markdown with
title, subtitle, section, language, exact byline, original magazine attribution,
source pages, filename and canonical reading link. Missing title fallback text is
visibly an interface label and does not mutate source metadata. If supplied,
`article['issue_url']` adds the site issue backlink and `markdown_labels` localizes
metadata labels.

Semantic paragraphs, headings, block quotes, lists, emphasis, meaningful line
breaks and stanza boundaries are preserved. Image URLs are absolute for portable
reader copies; original alt text/captions remain. Image credits that exist only in
source metadata receive a separate attribution section, without inventing a
license or public PDF URL. No runtime state or audit records enter the document.

Tables, underlining, superscripts, definition lists, typed lists and other
structures without a lossless portable Markdown equivalent remain valid embedded
semantic HTML. The AI notice remains its exact HTML, including the authoritative
English UUID link; no relabeling, translation, removal or generated paraphrase is
performed. Readers should use a CommonMark renderer that permits semantic HTML.

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_content.py' -v
python3 -m unittest discover -s tests -p 'test_routes.py' -v
python3 -m unittest discover -s tests -p 'test_markdown.py' -v
```

Fixtures exercise failed/absent translations, revision and checksum mismatches,
unreviewed/reviewed notice behavior, unsafe paths, chronology, collision handling,
reserved namespaces, Unicode, changed aliases, category moves, missing titles,
verse lines, nested lists, bylines, tables, image attribution and exact notices.
When `.build/english` exists, the Markdown test also converts every real exported
fragment. This is a structural regression check, not a new editorial review of
source transcriptions or a claim of human translation review.
