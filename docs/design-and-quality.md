# Design and quality contract

## Shared brand, magazine-specific reading layout

The upstream theme is pinned to `3bd0c28956610506f83e3ecd3af6ea775ac7cb45`.
Its CSS, header behavior, original logo/favicon/skyline assets and complete adjacent footer bands are consumed at build time. The satellite menu changes only the entries after Home, as allowed by the theme. Owner-requested localization changes visible labels while preserving footer destinations, group sequence and external-link behavior.

The original logo retains its white mount, natural 288×77 ratio and unchanged pixels. The white header and light directory footer remain recognizable in dark mode; editorial paper, text, separators and controls adapt to the selected theme. The copyright footer remains the original charcoal band. This is a deliberate magazine adaptation, not a claim that the upstream theme provided dark mode.

The original inactive navigation gray (`#b4b5ba`) is below AA for small text. An explicit specificity-matched local override uses `#62666c` on white. The upstream Joomla compatibility selector otherwise overrides the portable mobile logo width, so the local adapter restores the documented centered 66vw/240px logo. Closed mobile drawers are removed from layout to prevent RTL scroll overflow; open drawers retain focus handling and full viewport height. Cyan remains the brand accent; small text uses darker `#006773` on light paper and `#63e2eb` on dark paper. Montserrat and Raleway retain the documented display/body roles. Google Fonts are optional enhancement; local fallback stacks include the relevant Noto script families. Pages remain readable if font requests fail. Only the current locale's additional script font is requested.

Magazine cards, reading layouts, issue placeholders and controls are new site-owned components. They are not presented as extracted YOOtheme styling. Typographic issue identities use real catalogue dates, never fabricated front covers. Photographs on cards come from the linked source article; original article images, captions and credits remain intact in reading and Markdown views.

## Progressive enhancement and accessibility

- Every reading, category and issue route has its own static HTML file
- All 21 languages and all categories remain visible with honest localized empty states
- Language choices map article/group UUIDs, not guessed translated slugs
- Explicit locale routes always prevail; only `/` uses saved preference, browser locale, then English
- Theme initialization executes before styles and tolerates denied browser storage
- Original theme mobile-menu focus, Escape, close control, inert state and scroll behavior are retained
- Shared ten-minute homepage selections show all three archive cards together, offer Pause/Resume updates, preserve focused content until blur, and catch up after backgrounding; see [selection semantics](homepage-selection.md)
- Print removes navigation controls but retains article text, attribution and required AI notices
- Narrow article figures wrap only beside adjacent readable prose on sufficiently wide screens. Their immediately following opening headings may share that space; later headings and structural blocks still clear the entire figure and caption. Orphan figures, consecutive images, mobile/narrow columns and print stay stacked. Source order and text are unchanged, and logical sides mirror in RTL
- Markdown remains a direct download even if copying fails; the copy fallback is a selectable read-only textarea
- Search results are real links, text highlights use DOM text nodes, and asynchronous request IDs prevent stale result replacement
- Search pagination and filters persist in the URL; Back/Forward restores query state

The scripted browser suite exercises desktop and 360px mobile widths for every locale, English/Afrikaans/French, RTL, system/explicit themes, storage failure, missing translations, source-notice links, no-JavaScript discovery, reduced motion, print, and search history. Screenshots are captured as CI review artifacts for visual inspection, not silently treated as passing pixel comparisons.

No-JavaScript author navigation uses runner-managed contexts and retains normal
motion at desktop and mobile widths. It waits for font layout with runner-side
polling, explicitly scrolls each link into view, and requires a real visible
click. This avoids a pinned Playwright/Chromium retry limitation: in
[run 37149826916](https://github.com/trueChristian/remnant.truechristian.church/actions/runs/37149826916),
font layout instability led to fallback smooth scrolling, an offscreen hit-test,
and a 20ms in-page retry timer that never fired with JavaScript disabled. Manual
context cleanup then obscured that primary failure. The fix keeps normal
actionability checks, the original timeout, native navigation, and Back history.
These browser scenarios run against a healthy full site only after merge to main.
Pull requests run unit and synthetic contract tests without generating a full
site or starting browser builds. The original repair was also verified with five
fresh-context repeats per viewport; that historical evidence is in its PR.

## Measured initial budgets

On the initial selected export (646 English / 5 Afrikaans; English revision `6af08032b5e2a92ff0671605fb89dffa06780892`):

- Largest generated HTML page: approximately 68 KB uncompressed; target <100 KB for current pages
- English full-text index: 6,544,253 bytes JSON; 2,426,430 bytes deterministic gzip; target ≤3 MB compressed at this corpus size
- Empty-language indexes: two-byte JSON arrays
- Current homepage primary source image: 95,367 bytes, with an explicit image box; below-fold images are lazy-loaded
- All source images are shared across locales. Original image bytes are retained rather than multiplied by language

The compressed index is fetched only for the current search locale, on first nonempty query/filter, and decompressed in a Web Worker where supported. Plain JSON remains a compatibility fallback. No homepage downloads the search corpus. Rendering is paginated to 40 results. Query compute target is under 100 ms desktop and 250 ms under a 4× CPU slowdown; transport latency and cold-load time depend on the reader's connection. The first CI browser measurement on the 646-article corpus recorded a worst query of 7 ms at normal CPU speed and 21.2 ms at 4× CPU slowdown (10 representative queries). These are warm compute measurements, not cold-network load promises.

Issue chronology uses structured year plus seasonal/month ordering and original order for ties. Sorting ordinals are not publication dates. RSS omits `pubDate` when the source only gives a season, month range or year; feeds never create a fictional day.

Detailed revisions, translation omission diagnostics and budgets live in non-public `.build/site-build-report.json`. The public artifact contains only display content/assets and a bounded deployment identity used for safe deduplication.

## Review boundaries

Automated schema/script checks do not establish professional native-language proofreading. Dictionaries are complete initial translations; wording can be reviewed without changing article publication eligibility. Local test limitations, CI status and screenshot findings are recorded in the draft PR rather than claiming unrun checks passed.
