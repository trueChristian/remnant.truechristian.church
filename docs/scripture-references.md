# Scripture references in articles

Article pages enhance detected Scripture references with an on-demand GetBible
popover. The magazine HTML, downloadable Markdown, source repositories and exact
AI notices are unchanged. No passage text is inserted into the article. No API
key, paid model, background Bible download or browser-side article scan is used.

## What is checked, and when

The build-only OpenBible passage parser is pinned to 4.0.0. Its standard language
modules plus pinned Afrikaans and Bengali data cover all 21 configured locales.
Only eligible prose text is scanned, within block boundaries. Links, code,
scripts, navigation and translation notices are excluded. Original entities,
spacing, digits and emphasis survive byte-for-byte after removing our wrappers.

Detection requires an explicit book and valid coordinates. It rejects ambiguous
book alternatives, invalid/clamped passages and partial-verse suffixes rather
than silently changing their meaning. A small reviewed short-abbreviation list
admits common citations such as `Jn 3:16` and `Ps 23`, while prose-prone `Is`/`Am`
and ambiguous `Ph` remain plain. Bare `verse 16`, times and unrelated blocks do
not inherit book context. Chapter-only references deliberately request the whole
chapter; cross-chapter ranges become separate exact chapter queries. Extremely
large selections (over 12 queries or a range spanning more than 11 chapters) stay
plain. Detection is conservative and can still have false positives/negatives.

The cache key contains article UUID, locale, exact display-fragment SHA-256 and
the detector/configuration version. A normal rebuild never invokes the detector
for unchanged records. New or changed articles alone are scanned. Editing a
Bible selection, UI style or editorial override does not invalidate detection.
Cached records are checked for schema/integrity, source quotation and eligible
source spans before use.

## Durable tracking files

- `data/scripture-ledger.json`: Git-tracked reviewed initial full backfill
- `data/scripture-overrides.json`: Git-tracked editorial suppressions and inclusions;
  this is the file to edit to remove a false positive
- `data/scripture-translations.json`: Git-tracked reviewed static Bible choices,
  inventory evidence, attribution metadata and unresolved edition questions
- `data/scripture-ui.json`: localized popup labels
- `.build/scripture-manifest.json`: current local build snapshot, not committed
- `/scripture/manifest.json`: current published immutable-key scan records, reused
  by later builds; contains only public article references and their short context
- `.build/scripture-report.json`: scan/reuse/suppression totals and anchors requiring
  editorial review; retained in CI evidence and shown in the workflow summary

The workflow reads the previous published manifest before building. It has no new
write permission and never automatically commits scan results. Actions cache is
not the persistence mechanism. A PR's preview artifact also contains its current
manifest. The snapshot omits removed articles and superseded revisions; immutable
record identities do not imply republishing an endless history of article text.

If the live manifest is unavailable, the checked-in initial ledger and any local
snapshot still work. A later article absent from both must be rescanned to recover
its record. The build explains this recovery; it does not claim perfect once-only
execution when every durable copy is unavailable. To seed an offline build, save
the verified current published manifest as `.build/scripture-manifest.json`.

## Remove or correct a false positive

Find the article UUID in its Markdown download URL, then inspect its record in
`data/scripture-ledger.json` or the current manifest. Keep detection records
immutable; deleting one would cause a new scan. Copy the marker's ID and anchor
into `data/scripture-overrides.json`, for example:

```json
{
  "schema_version": 1,
  "articles": {
    "en:00000000-0000-4000-8000-000000000010": [
      {
        "action": "suppress",
        "marker_id": "0123456789abcdef01234567",
        "anchor": {
          "quote": "John 3:16",
          "before": "Exact preceding context",
          "after": "Exact following context"
        },
        "reason": "This mention is not a Scripture citation"
      }
    ]
  }
}
```

Use the actual values from the record, not the example above. Commit that edit
and trigger the usual website build. It re-renders without rerunning detection.
A source edit re-anchors a suppression only at a unique exact quote/context match.
Suppression also covers an overlapping match expanded by a newer detector. If the
anchor is missing or ambiguous, the build withholds enrichment for that article
and reports review required; it never silently restores a rejected reference.

An `include` rule uses the same unique anchor and a `queries` array, such as
`["43 3:16-18", "43 4:1-2"]`. Numbers are canonical Genesis=1 through
Revelation=66. Each query explicitly includes book, chapter and verse/range.
It can add a missed citation or replace an existing marker's mistaken query.
No public API URL or HTML is accepted in a query. Omitting `marker_id` derives a
stable ID from the rule. Delete a suppression rule only when you want automatic
detection restored.

## Static Bible selection

The catalog and core-book inventories were checked on 2026-09-30 and persisted.
They are not queried at every build. English uses KJV. Other choices favor the
oldest identifiable complete Genesis–Revelation edition in the GetBible catalog,
using edition history rather than module update dates. All 16 available choices
contain core book IDs 1–66; this is not a chapter/verse completeness guarantee.

Bengali, Hindi, Indonesian and Urdu have no matching catalog Bible. The Swahili
candidate contains only 26 books, missing the Old Testament and Philippians.
These five languages remain plain, with no unapproved English fallback. Detection
records are still prepared, so selecting a future complete edition need not
rescan unchanged text.

Important review notes remain visible in the mapping:

- Spanish `sse` is described as an 1865 Reina-Valera revision with 2018 spelling,
  despite a 1569 catalog title. `rv1858` describes a 1909 edition
- Modern Hebrew has no reliable original-edition date or rights provenance
- Dutch refers to the 1637 translation family; the exact catalog text edition is
  unspecified. Portuguese metadata combines 1900/1911 dates
- Swedish 1703 is incomplete (44 books); the selected 1873 edition has all 66
- Afrikaans and Arabic API metadata includes distribution restrictions. The site
  retains translation/provider attribution and requests passages on demand; it
  does not bulk-copy or redistribute a Bible. Publisher rights remain applicable

The mapping is reviewable and does not pretend uncertain edition history or
rights are settled. To change a choice, verify its original publication history
and book inventory once, update the static file and rebuild. Keep English KJV
unless the owner changes that requirement.

## Loader integration and failure behavior

Self-hosted GetBible loader 3.1.0 API, memory, reference and scripture components
are retained with a narrow site adapter. See
`assets/vendor/getbible/3.1.0/PROVENANCE.md` for pinned provenance, MIT notice and exact
compatibility/security changes. Build-time canonical data replaces the upstream
30-character ASCII/innerHTML interpretation path, while the original citation
remains visible. The plain native-title tooltip is replaced by the accessible
site popover.

Hover, focus, keyboard activation and touch open the same bounded popup. Escape,
outside interaction and its close button dismiss it. Requests are deduplicated,
API text is inserted as text, stale asynchronous results cannot replace a newer
selection, and unavailable/corrupt browser storage is optional. Network failures
leave the original article intact and offer the GetBible reader link. The
approved reader base is `https://getbible.life/`.

## Verification

Run `npm ci` before the Python build (Node 20+ and Python 3.11+). `npm test` covers
21-locale fixtures, local digits, numbered/abbreviated books, ranges, inline
emphasis/entities/UTF-16 offsets, false-positive exclusions, exact round-trip
HTML/Markdown/notices, cached no-rescan builds, override corrections, stale and
expanded suppressions, strict API responses, storage and network failures.
`npm run test:browser` adds desktop/mobile, keyboard/touch, RTL/dark, async
race/dismissal and hostile API-text cases. `scripts/check_site.py` strips only
our exact generated wrappers before enforcing the original-source HTML contract.

CI separately probes one live public KJV verse using the actual canonical numeric query.
The explicit availability result is retained in `.build/scripture-provider-report.json`
and the workflow summary. External reachability is non-blocking; a green mocked
browser suite alone is never proof that the live provider was reachable.
