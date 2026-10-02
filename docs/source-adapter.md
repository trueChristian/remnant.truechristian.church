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
model = load_content(Path('.build/english'), Path('.build/translations'),
                     language_registry=Path('.build/languages.json'))
```

The supported translation export does **not** contain the full configured-language
registry. Source preparation captures `config/languages.json` separately from the
same selected clean translation checkout (including languages with no articles).
Pass that snapshot as `language_registry=Path(...)` or a registry dictionary.
`model['languages']` exposes only folder codes, language tags, names, directions
and aliases; translation guidance is not copied into the public content model.
The generator must call `validate_locales(locales, registry=model['languages'],
categories=model['categories'])`. A newly configured language without its complete
interface then produces an explicit validation failure instead of silently
continuing with the previous inventory.

When translation source acquisition is unavailable, pass `None`; the model emits
an explicit warning that upstream language additions could not be checked, and
valid English can publish with the website's known complete interfaces. An
explicitly supplied missing/malformed registry raises `ContentError`. Available
translation tags, folder codes and text directions must agree with the selected
registry. The `english_export` Path is internal build context only; generated
reports and public output must use explicit field allowlists, never serialize the
whole model.

`model['articles']` maps URL BCP-47 language tags to available articles. All
catalogue categories/issues/topics/series retain their source UUIDs and metadata.
The UI, not the content adapter, is responsible for offering every configured
locale and empty categories. Articles retain the full exported English metadata
under `source_metadata`; ordinary fields remain directly accessible. `html_source`
retains the original HTML path metadata; `html` is the complete display fragment.
`html` is never parsed and reserialized. The renderer preserves translation
notice text and changes only a known English UUID-link `href` to its readable
canonical URL. The source model keeps the original fragment. `translation`
contains only already-public exported translation metadata, not processing state.

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

`ordered_issues(model)` sorts newest first by structured year, then month-range
endpoint, month, or the publisher's annual seasonal sequence (Spring, Summer,
Autumn/Fall, Winter). The [publisher's archive](https://bereanvoice.com/ministries/)
places Winter at the end of its labelled year, so Winter 2024 precedes Autumn
2024 in newest-first displays. This convention applies to every seasonal year,
independently of catalogue array order. Equal/unknown periods preserve catalogue
order; year-only entries follow entries with known periods in the same year.
These are ordering keys, not publication dates, and source date objects are
unchanged. Article lists follow that issue order, then their source sequence and
UUID.

## Route API and persistence

```python
from scripts.routes import initialize_routes
routes = initialize_routes(model, locales, Path('.build/routes.json'))
```

`locales` may be a mapping of language tags to locale dictionaries or an iterable
of tags. A locale dictionary's `categories[uuid]['slug']` is used only when that
category first enters the registry. Article/category/issue maps use
`routes[kind][locale][uuid]`; UUIDs identify content internally. Every available
translation receives one localized canonical article URL, with localized
category and title aliases. Published dictionaries receive `url`,
`compatibility_url` and `markdown_url`; Markdown uses `url.rstrip('/') + '.md'`.
UUIDs never appear in canonical article, category, Markdown, or generated
search-filter URLs. Existing `/<locale>/articles/<uuid>/` addresses remain
compatibility redirect endpoints, and the renderer updates English notice links
to the readable English canonical.

`routes['articles'][locale]` also covers English identities whose translation is
unavailable. Their availability pages use
`/<locale>/articles/<frozen-English-alias>/`: one shared readable tail avoids
allocating a distinct localized category/title combination for every missing
translation. These pages are noindex, contain no translated article body, and
link to English and available translations. When the translation publishes, it
receives a localized category/title canonical and the former availability
address is retained as a redirect. `article_url`, `category_url` and `issue_url`
are lookup helpers.

`routes['redirects']` maps readable prefix/history aliases and original-locale
legacy UUID paths directly to final canonical paths. Changing only the locale
prefix of a readable article, category, or historical path resolves the same
internal identity and redirects to its selected-language canonical without
JavaScript. This includes both category and article segments in an article
address. Legacy UUID histories with a manually changed prefix use the root
404 page and `legacy-route-index.json` for exact known-alias recovery; this
special case requires JavaScript and replaces the browser URL with the readable
canonical. It does not guess unknown aliases or generate every legacy UUID
history under every language prefix.

Category pagination keeps the same category identity after a prefix change. It
opens the corresponding localized page when that page exists; otherwise it
opens the category's localized first page.

Normal navigation, language selectors, search, RSS, and sitemaps link directly
to canonical paths. Canonical article pages have self-referencing canonical
metadata and reciprocal `hreflang` links only to available translations.
Redirects and missing translations are excluded from indexed alternatives.

`data/routes.json` is the committed website-owned editorial registry, not an
export from either content repository. Before generating output,
`scripts/route_registry.py` merges it with the last successfully published
`routes.json` into `.build/routes.json`. Published additions and histories are
retained. Reviewed committed changes take precedence, except a stale committed
UUID fallback cannot replace a migrated readable published alias.

New publications receive readable title aliases automatically. Duplicate aliases
use `title`, `title-2`, `title-3`, and so on; no UUID or issue context is appended.
Allocation is deterministic, Unicode scripts remain readable, and retired aliases
stay reserved. The candidate registry is exposed as `routes['registry']`, with
additions in `routes['pending']`, and written to the generated `routes.json`.
Only successful site publication makes it the next durable baseline. No repository
write or credential is required for ordinary publication.

Saved aliases and original primary-category paths remain frozen after title
corrections, category renaming, or grouping moves. Current breadcrumbs may reflect
updated editorial grouping while established article URLs stay stable. An
intentional alias or category-path change must retain previous paths in history.
Legacy UUID canonical aliases migrate to readable aliases and retain their former
addresses as redirects.

For a reviewed maintenance update, start with the merged registry and pass
`update=True` to save route additions atomically, or use the build's
`--update-routes` with an explicit registry path. Review the resulting registry
before copying it into `data/routes.json` and committing it. Ordinary builds leave
their input registry unchanged. For online/offline preparation and failure
handling, see [operations](operations.md).

For an intentional migration:

```python
from scripts.routes import set_article_alias
set_article_alias(registry, 'af', article_uuid, 'approved-new-alias')
# Optional category_slug= selects a deliberate canonical-category migration.
# Write the registry, rebuild, review collision tests, then commit it.
```

Every previous path remains in `history`; legacy UUID fallback paths remain
recognized for compatibility in their original locale, with changed-prefix
legacy permutations recovered through the JavaScript lookup described above.
Retired aliases cannot be reassigned to another
identity. Registry entries do not republish removed content. Reserved namespaces,
conflicting histories, and cross-language aliases that identify different objects
fail validation before publishing. GitHub Pages redirects are zero-delay HTML
refresh pages with canonical/noindex metadata, not HTTP 301 responses.

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
semantic HTML. The AI notice keeps its exact text and markup except the English
UUID-link `href`, which the site renderer replaces with the authoritative readable
English URL before generating reader Markdown. No notice relabeling, translation,
removal, or paraphrase is performed. Readers should use a CommonMark renderer that
permits semantic HTML.

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_content.py' -v
python3 -m unittest discover -s tests -p 'test_routes.py' -v
python3 -m unittest discover -s tests -p 'test_markdown.py' -v
python3 -m unittest discover -s tests -p 'test_site.py' -v
python3 -m unittest discover -s tests -p 'test_route_registry.py' -v
```

Fixtures exercise failed/absent translations, revision and checksum mismatches,
unreviewed/reviewed notice behavior, unsafe paths, chronology, collision handling,
reserved namespaces, Unicode, changed aliases, category moves, missing titles,
verse lines, nested lists, bylines, tables, image attribution and exact notices.
When `.build/english` exists, the Markdown test also converts every real exported
fragment. This is a structural regression check, not a new editorial review of
source transcriptions or a claim of human translation review.
