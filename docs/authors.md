# Author browsing

The website generates Authors as a third archive view alongside Categories and
Issues. `/en/authors/` lists the recorded authors alphabetically. Each name opens
an author page with recorded details and an issue-style list of articles across
all issues and categories. Article titles link to the existing category-based
canonical reader; no author-nested article copy is generated.

## Data ownership

`scripts/authors.py` derives membership from the authoritative English display
export's structured `byline.authors` entries. The exact recorded name is the
website identity. Punctuation, capitalization, spelling variants and initials
are not consolidated. Raw publisher/source credits are never parsed as names.
Explicit Anonymous/Unknown names remain exactly as recorded. A shared article
appears once under each credited contributor, without increasing the archive's
article inventory. Translations cannot introduce names or inflate original
article totals.

Names and the printed byline remain unchanged. Source locations, contributor
roles, credentials, life dates, birth/death years and recorded ages are displayed
when present, under a translated explanation that these are details recorded in
the original publications. Distinct values are retained; they do not assert a
current address, role or age. No author portrait or generated biography is used.
Source spelling corrections or future identity consolidation belong in
Berean Voice. There is no second manually maintained author catalogue here.

## Routes and publication

The optional `authors` section in the version-1 route registry maps language tags
to exact source names, with each record containing `slug` and `history`. Existing
registries without this section remain supported. URLs follow
`/<language>/authors/<readable-name>/`. Slug collisions get numeric suffixes, and
UUIDs never appear in canonical author URLs. The authors namespace is reserved
against category conflicts.

The normal durable registry preparation merges the last successful publication
before building. New author aliases are emitted in the site's `routes.json` and
become durable with successful deployment. Existing and retired aliases remain
reserved. Source reordering and new colliding names cannot reassign them.
Explicit alias edits must retain previous paths in `history`; historical paths
redirect directly to the same author's canonical page in the requested language.

## Languages and navigation

All 21 interface languages have the same complete source author inventory.
Cards and profiles distinguish total original articles from those available in
the selected language. A profile lists only actual publications in that language,
using the archive's issue chronology and original article sequence. An empty
language view explains the absence and links to the same author in English.

The shared desktop/mobile menu, profile breadcrumbs, reader bylines and language
selector link to author pages. Recorded names within bylines become links without
rewriting the printed credit; structured credits absent from the raw string get
separate labeled links. Article HTML and downloadable source attribution remain
unchanged.

Profiles paginate at the existing archive page size of 24. The first page has
reciprocal language alternatives and appears in the sitemap. Later pages are
self-canonical and noindex, and their language selector opens the same author's
first page. Manually changing the prefix on a paginated URL preserves the page
number when available, otherwise redirects to the same author's first page.
Ordinary browsing, pagination and readable redirects work without JavaScript.

## Verification

Focused tests cover exact names, multiple contributors, historical metadata,
stable route allocation, retired aliases, translated availability, canonical
article links, pagination, and corrupted-output detection. The independent site
checker compares generated author pages with the validated source export.
Browser tests exercise directory-to-author-to-reader navigation, byline return
links, language switching, coauthors, narrow LTR/RTL layouts and no-JavaScript
browsing. The standard PR workflow runs these with the complete source archive.
