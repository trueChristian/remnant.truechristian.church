# Shared homepage selections and original issues

## Static Pages, shared clock

The homepage is progressively enhanced with a deterministic schedule. Visitors
viewing the same locale, published inventory and UTC ten-minute slot receive the
same feature, archive group and categories. Slots start at :00, :10, :20, :30,
:40 and :50. No per-reader cookie, storage history, server, database, paid job or
GitHub rebuild is required. The browser's clock supplies UTC epoch time, so a
wrong device clock can select a different slot.

`assets/home-selection.js` is a pure, separately tested engine. Each section has
a locale-seeded shuffled circle of permanent UUIDs. It never restarts at midnight
or reshuffles at the end of a cycle; that would allow near-immediate repeats.
Canonical ordering means source array order and browser locale cannot alter the
result. An inventory change establishes a new schedule, so the non-repeat
interval applies while the eligible inventory is unchanged.

The homepage order is:

1. Featured magazine paired with **its own** editor's remarks
2. Three archive articles, all visible together
3. Six latest articles, retaining bibliographic chronology
4. Eight rotating category tiles, with the complete category link retained

The authoritative English title/section identifies editorials. Localized entries
are joined by permanent article UUID, never a guessed translated title. Only
actual translated pairs enter a locale's feature pool when available. A locale
without translated editorials keeps a random issue with a localized empty state
and a link to the corresponding English editorial or issue. It never silently
pairs another issue's article. No hero claims to be the latest issue/article.

## What the no-repeat rule guarantees

- Archive uses three positions per ten-minute slot. With at least **435 eligible
  articles**, a repeated article's display starts at least 145 slots later,
  leaving a full 24 hours after its previous ten-minute display ended
- A smaller pool uses every eligible article before the continuous sequence
  repeats. A group that crosses the end of the circle can contain previously
  shown items only after all remaining unseen items have been consumed
- Hero issue/editorial pairs and categories also cycle through the complete
  available pool before repeating. They cannot promise a day of absence when
  there are fewer than 145 pairs (or 1,160 category positions for groups of eight)
- All editorials in the locale's feature pool are excluded from its archive pool
- Latest articles are chronological, fixed content and outside this rule. They
  are excluded from the rotating archive when at least three other articles
  remain. Tiny locales can overlap Latest and Archive rather than hide their
  only real content. A locale with fewer than three eligible articles displays
  only the available unique articles; empty pools remain useful empty states

The verified October 1, 2026 export has 722 English articles, 54 editorial pairs,
663 eligible English archive articles, four Afrikaans articles (one editorial,
three archive articles), and no compatible published articles in the other
locales. The English archive's minimum interval is 221 slots: 36h50m between
starts, or 36h40m absent. Hero pairs cycle every nine hours. These counts are
observations of that export, not hard-coded publication limits.

## Accessibility, payloads and fallbacks

Digest-addressed same-origin preview JSON contains escaped card/feature markup,
not full article bodies or the search corpus. Deterministic gzip is preferred,
with a plain JSON fallback. The independent output checker audits the schema,
digest, gzip parity, active-HTML exclusion and all preview links/images.

Visible tabs update at the shared boundary without animation or live-region
announcements. A section containing keyboard focus waits until focus leaves;
other sections update normally. Returning from a hidden tab, restored page or
sleep recomputes the current slot. Static HTML remains navigable with JavaScript
disabled or if preview loading fails; that fallback intentionally does not claim
timed rotation. Full article routes, issue chronology, feeds and search stay
static and unchanged.

Navigation arrows are decorative, `currentColor` SVG paths rather than Unicode
emoji-capable glyphs. Link/button accessible names remain text, and RTL layouts
mirror the directional icon.

## Verified publisher downloads

`data/issue-pdfs.json` maps issue UUIDs to original Berean Voice URLs. Each record
preserves the exact observed official archive href, label, source metadata,
source SHA-256 and verification evidence. All 63 mapped files were fetched from
the official publisher and their PDF headers and SHA-256 values matched the
converted source catalogue. Seven local filenames include browser download
suffixes, which are deliberately **not** used to derive URLs.

Issue actions appear as article count, Publisher, then Download (PDF), with
localized labels in all 21 interfaces. Publisher points to
<https://bereanvoice.com/>. Download is an ordinary external original-PDF link;
browsers may open their PDF viewer instead of saving immediately. No PDFs are
copied into this website or relocated.

`scripts/publisher.py` rejects altered hashes, unverified records, duplicate
identities and off-publisher URLs. A future unmapped issue omits Download rather
than guessing a path. Add a reviewed record after observing the official link
and comparing the downloaded PDF hash with that issue's source hash. Existing
mapped issues fail closed if their source PDF changes until the mapping is
reviewed again.
