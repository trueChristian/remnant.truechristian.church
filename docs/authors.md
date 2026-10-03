# Author browsing

The website generates Authors as a third archive view alongside Categories and
Issues. `/en/authors/` lists the canonical authors alphabetically. Each name opens
an author page with recorded details and an issue-style list of articles across
all issues and categories. Article titles link to the existing category-based
canonical reader; no author-nested article copy is generated.

## Data ownership

`scripts/authors.py` derives membership from the authoritative English display
export's structured `byline.authors` entries. `data/author-aliases.json` maps
reviewed spelling variants and alternate names to one canonical author identity.
Names absent from this index remain distinct; the build does not guess from
similar spellings or initials. Raw publisher/source credits are never parsed as
names. Reviewed Anonymous/Unknown credits share the **Anonymous** profile.
An omitted or null person name is supported source metadata, including credits
such as `--The Editor`. These credits retain their exact printed byline, article
body, search attribution and Markdown, without inventing a named author or
assigning them to Anonymous. Empty names, non-text names and malformed recorded
details still fail validation. Regression fixtures preserve the three role-only
bylines from Berean Voice revision `58e50fca41cc0b53c8992502bd95166581036945`.
A shared article appears once under each distinct canonical contributor, even
when the same article credits two aliases of that person. Translations cannot
introduce names or inflate original article totals.

Source names and printed bylines remain unchanged. Source locations, contributor
roles, credentials, life dates, birth/death years and recorded ages are displayed
when present, under a translated explanation that these are details recorded in
the original publications. Distinct values are retained; they do not assert a
current address, role or age. No author portrait or generated biography is used.
Source spelling corrections may still be made in Berean Voice. The website's
small alias index controls grouping; article membership and recorded details
continue to be generated from the source on every build.

## Maintaining reviewed identities

The version-1 alias file contains an `authors` object. Each key is the canonical
display name and its array lists the exact source names that should join it:

```json
{
  "version": 1,
  "authors": {
    "Dean Taylor": ["Brother Dean", "Bro. Dean"]
  }
}
```

Add a newly confirmed spelling to the existing person's array, or add a new
group after reviewing the source. Do not repeat the canonical name in its own
array. Duplicate keys, reused aliases, chains, cycles and malformed names fail
validation. A name cannot belong to two people. Initials and similar family
names need evidence: George R. Brunk, Sr. remains separate from George R. Brunk II.
The file is part of the website repository, so future corrections require only
a normal website change and rebuild.

The first review consolidates 14 groups, including the screenshot-reported
variants. The live 971-article source inventory changes from 408 recorded names to
378 author identities; Anonymous contains 22 distinct articles. John Waldron's
source introduction explicitly connects him to Vincent “John” Bradford Waldron.
C. L. Wenger's initials, surname and Dalton, Ohio details support the Curvin L.
Wenger grouping. Robert Murray M’cheyne is the case-only variant of M’Cheyne,
with identical recorded life dates. Unconfirmed initials such as DT stay separate.

## Routes and publication

The optional `authors` section in the version-1 route registry maps language tags
to canonical author names, with each record containing `slug` and `history`. Existing
registries without this section remain supported. URLs follow
`/<language>/authors/<readable-name>/`. Slug collisions get numeric suffixes, and
UUIDs never appear in canonical author URLs. The authors namespace is reserved
against category conflicts.

The normal durable registry preparation merges the last successful publication
before building. New author aliases are emitted in the site's `routes.json` and
become durable with successful deployment. Existing and retired aliases remain
reserved. Source reordering and new colliding names cannot reassign them.
When author identities merge, both committed and published registries are
reconciled before assigning routes. The canonical author's existing slug wins;
if it has no record, an existing member's slug is retained deterministically.
All other member URLs and their histories become direct redirects to that
canonical author in the requested language. This also preserves retired routes
and prevents an old registry from restoring duplicate authors. Explicit URL
alias edits must retain previous paths in `history`.

## Languages and navigation

All 21 interface languages have the same complete canonical author inventory.
Cards and profiles distinguish total original articles from those available in
the selected language. A profile lists only actual publications in that language,
using the archive's issue chronology and original article sequence. An empty
language view explains the absence and links to the same author in English.

The shared desktop/mobile menu, profile breadcrumbs, reader bylines, search
results and language selector link to author pages. Recorded names within bylines
become links to the unified author without rewriting the printed credit. Each
canonical person receives one link even when several aliases occur in a credit;
structured credits absent from the raw string get separate labeled links. Search
finds both canonical names and their observed source variants. Article HTML and
downloadable source attribution remain unchanged.

Profiles paginate at the existing archive page size of 24. The first page has
reciprocal language alternatives and appears in the sitemap. Later pages are
self-canonical and noindex, and their language selector opens the same author's
first page. Manually changing the prefix on a paginated URL preserves the page
number when available, otherwise redirects to the same author's first page.
Ordinary browsing, pagination and readable redirects work without JavaScript.

## Verification

Focused tests cover reviewed aliases, unmerged names, multiple contributors, historical metadata,
stable route allocation, retired aliases, translated availability, canonical
article links, pagination, and corrupted-output detection. The independent site
checker compares generated author pages with the validated source export.
Browser tests exercise directory-to-author-to-reader navigation, byline return
links, search-result author links, language switching, coauthors, narrow LTR/RTL
layouts and no-JavaScript browsing. The standard PR workflow runs these with the complete source archive.
