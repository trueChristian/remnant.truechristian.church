# Article image layouts

The reader arranges source images for the available reading width. Article text,
image bytes, alt text, captions, credits, and Markdown remain authoritative
upstream content; the website adds presentation wrappers and classes only.
It does not crop visible artwork, retouch, or replace the archive's images.
Prose wrapping retains the image's natural dimensions. Small illustrations beside
explicitly marked poems may be displayed at up to twice their original dimensions.
Reviewed transparent canvas padding can be hidden in the reader without editing
the source file.

## Archive review

The 2026-10-20 review used English revision
`918709aaa14615100c469d3545de047031baed9d` and translation revision
`90021153d92e37a558da7e6c702852224b7f5fc7`.

- All 1,168 English articles were structurally inspected. The 969 articles with
  images contain 1,848 image references in 1,838 figures. Every image reference
  resolves to a readable local asset.
- All 1,848 English image references were visually reviewed on 31 contact sheets;
  the 83 images with transparency were additionally checked on white backgrounds.
  This is an image inventory review, not a claim that every article was manually
  viewed in every browser, viewport, and language.
- The markup contains 86 consecutive figure groups in 82 English articles and
  10 figures containing two images. All images are inside figures; no loose
  images or figure-heading-figure sequences were found in this snapshot.
- The structural translation audit covers 2,972 translated articles in 20
  languages: 2,388 with images and 3,384 image references. Reader rules use stable
  article UUIDs and image basenames, so translated captions and text are retained.

## Layout behavior

### Poems and lyrics

Illustrations next to verse use a separate stanza column, rather than prose
floats. This includes `poem` and `lyrics` paragraphs and containers, and
paragraphs with multiple explicit line breaks. In **A Godly Woman**, the opening
illustration stays above the poem; the five remaining illustrations accompany
their stanzas, including the closing image alongside the final stanza.
In **Until the Daybreak**, the twilight photograph stays centered above the
opening stanza at every reading width. Both stanzas retain their original
line breaks.

The generator groups only adjacent source nodes, preserving every word, line
break, image, caption, and their DOM reading order. Groups stop at ordinary prose,
headings, galleries, and unrelated containers. Reviewed standalone images keep
their existing presentation. This works across languages without title-specific
or English-only rules.

On wide screens, the reader measures the longest original verse line in its
actual font. Explicit poems and lyrics use up to 320px of spare width and 600px
of height. Small originals may grow up to twice their natural size, aiming for
240px width. The text column uses its measured line width and the illustration
sits immediately beside it with a gap of at least 24px (normally 27px), aligned
to the top. If there is not enough room for both, it stays above or below the verse
in source order. The text never bends around a picture halfway through a stanza.
Resizing, font loading, larger type, and delayed image loads recalculate the
layout. Right-to-left text puts the illustration on the opposite logical side.
Mobile, print, and JavaScript-disabled reading use bounded, centered images with
full-width stanzas. Images are never cropped. Paragraphs grouped solely because
they contain multiple line breaks, such as book credits and addresses, retain
their previous 180px/300px limits and are not enlarged.

Prose illustrations keep their native width and height when wrapped. A float
requires a reading column of at least 34 text ems, at least 14 text ems beside
the image after its gap, and an illustration no taller than 40 text ems. An image
that cannot fit these conditions stays in the full reading column, with normal
responsive containment on narrow screens.

### Review on 2026-10-28

The structural audit used English revision
`ed75201a8e3b37913a14f4d949de33a7a0daa2c2` and translation revision
`b5b2c1840abb0599ba275cff4ef1598b91cef831`:

- 1,168 English articles, including 966 illustrated articles and 1,844 images.
- 3,006 translations, including 2,421 illustrated articles and 3,422 images.
- Verse arrangements apply to 93 English articles (103 groups) and 436
  translations (436 groups).
- Every article passed exact text/line-break and image-tag preservation checks,
  and applying the layout twice produced the same output.

These are archive-wide structural checks, not a claim of manual inspection of
every page. A browser scan rendered all 3,387 illustrated article bodies with
the site styles at desktop and phone widths (6,774 views). Deferred images were
explicitly loaded and rechecked; the final scan found no broken images, image/text
overlaps, or horizontal overflow. The complete multilingual build also passed
the site checker with zero errors. Browser regressions cover the poem, prose portraits, captions,
galleries, reviewed image pairs, transparent padding, narrow columns, phone
widths, larger type, RTL, JavaScript-disabled reading, and print.

### Prose and galleries

Consecutive small photographs become a static responsive gallery. Existing large
landscape images keep their individual reading-column presentation; the review
protects 23 such images in 15 articles from being shrunk into a new gallery.
The existing wide single-image layouts in **God Would Not Let Me Go**, **A Shoulder
to Lean On**, and the opening of **Mothers and the Great Commission** remain
unchanged. Each original figure retains its own caption, while a multi-image
figure keeps its shared
caption below its image row. Ordinary groups can reflow into fewer columns when
space is limited. These arrangements work with JavaScript disabled.

Ten reviewed compositions remain side by side, with their physical left/right
order preserved on narrow screens, in right-to-left languages, and in print.
Their original aspect ratios are retained. Generic grouping never crosses
paragraphs or structural boundaries. For an explicitly reviewed composition,
caption-free panels separated by prose may be reunited at the first panel only
when the exact images occur once, in the expected order, under the same article
or section parent. Article prose remains in its original order.

| Article | Article UUID | Paired image sequences |
| --- | --- | --- |
| Separation | `37272f7d-a8c0-4c15-b884-ebbf333303cb` | 2, 3 — open-Bible photograph halves |
| ‘Til the Storm Passes By | `affa9e6e-7d44-4174-ae66-fd44cfaeeaa0` | 1, 2 — storm landscape halves |
| Not My Will | `71acc7cf-0c85-4e46-9a50-7afaeca6c9ac` | 1, 2 — misty landscape halves |
| Pots | `77cd4a24-14db-4ba2-905f-4f3ecb1d3ea5` | 1, 2 — unequal portions of the potter photograph |
| The Gospel of the Kingdom | `7065efe5-66f5-44c1-bf03-3f88d5ad2c74` | 1, 2 — mirrored horns |
| Bondage in Freedom | `90100e26-9fe9-40a7-bfed-8a44154b0d27` | 1, 2 — left and right shackled forearms |
| The Heart of the Matter | `103f9dba-5fc8-4384-9161-226f96d1ff5a` | 2, 3 — fruit bowl and banana |
| Through the Eye of a Needle | `aec53018-3515-40c2-9347-8276571177cf` | 2, 3 — book groups flanking the original heading |
| The Circuit Rider VS. The Televangelist | `6f61a1ae-d1cc-4748-abea-a8e44a891dc4` | 1, 2 — rider and luxury car from the opening collage |
| FelloWSHIp WITH me | `64555f1c-017c-4ac5-a941-3b577cf58ff3` | 1, 2 — mirrored outstretched sleeves |

Small individual images and portraits may wrap beside adjacent prose when the
screen and reading column leave enough room for comfortable text. The figure's
immediate opening headings can share that space; later sections, quotes, tables,
and galleries clear the complete figure and caption. Eligible illustrations
can also share their immediately following ordinary one-paragraph quotation. Its
border stays beside the image, and subsequent prose clears both. Quotation
padding and the quotation's actual font size are included in the fit calculation.
Verse, hidden or empty quotations, and nested structural content keep their
independent layout. Small landscapes up to a 2.4 aspect ratio share the same
native-size wrapping rules; reviewed wider images can opt in. Lists following the figure
or its opening headings regain the full reading width below the image, as in
**Governing Your Family**. Narrow screens, narrow columns, and print remove text
wrapping. Logical float sides follow the text language; physical sides of a
paired composition do not reverse.

In **Tribulation Worketh**, the first paragraph follows the transparent arch in
the heading illustration. Two reviewed physical edge shapes reserve the visible
artwork while the original image is displayed once at its full available width.
The paragraph retains its normal type size and continues below the illustration;
the second paragraph and all later content keep their ordinary flow. The shapes
follow the PNG's nonzero-alpha boundaries with extra clearance, without changing
the image, text, or source markup.

This enhancement requires the loaded image to match its reviewed dimensions,
CSS Shapes support, a screen at least 48rem wide, and a reading column at least
34 text ems wide. It recalculates when the column or font size changes. Narrow
columns, larger text, image errors, JavaScript-disabled reading, and print retain
the stacked image and paragraph. The artwork and its physical left/right edges
remain in their original orientation in right-to-left languages.

The review marks 135 images as standalone. Of these, 112 contain sheet music,
text-bearing graphics, handwritten letters, maps, tables, clippings, or
decorative section dividers; the other 23 are existing large landscape images.
These do not become floating illustrations or join neighboring galleries.
Printed material retains the available reading width rather than being shrunk
into a photo grid. Illustrations nested in quotes, lists, tables, or callouts
keep their source placement. Repeated images remain separate section markers.

Whole paragraphs marked `drop-cap` remain ordinary paragraph blocks; only their
first letter receives drop-cap styling. This prevents an opening paragraph from
floating beside and squeezing subsequent images. Inline drop-cap spans retain
their existing behavior.

## Maintaining reviewed exceptions

### Website review on 2026-11-10

The review uses English archive revision
`6c3e27346b6b031f46e29e723e884fe8407806b7`. All placement changes are applied by
the website renderer; no archive changes or index updates are required.

| Requested article | Website arrangement |
| --- | --- |
| Religious Affections | Native 108 × 171 portrait at the left of its ordinary quotation |
| God’s Faithfulness Through Tragedy | Family photograph beside the preceding paragraph, portrait beside the following paragraph, each with its complete caption |
| The Spirit of Fear | Native 242 × 429 lion after the epigraph and beside the opening prose |
| The Power of God’s Word to Heal | Native 241 × 360 image beside the opening verse quotation |
| I AM HABIT | Illustration enlarged from 120 × 137 to 240 × 274 when it fits, close to the measured verse column and aligned at the top |
| The Radical Chinese House Churches (part II) | First photograph after the epigraph and beside the opening paragraph |
| Godly Home Series • 2003 | Complete photograph and caption above the availability announcement; the ordered list keeps its full width |
| Rees Howells: Intercessor | Building photograph wraps beside its paragraph at native size |
| Do We Treasure God’s Word? | Original logo beside P1; second photograph beside P3 |

The same reviewed opening placement is applied to 20 further illustrations
separated from their introductory prose by an epigraph. Ordinary quotations,
small landscapes, and preservation of native prose-image dimensions use shared
layout rules. The structural poetry audit covers all 1,168 articles and finds
102 existing verse groups in 92 articles: 98 explicit poem/lyrics groups and
four reference/credit groups that retain their original sizing policy. Existing
standalone and paired compositions retain their intended boundaries.

The [hosted Chromium review](https://github.com/trueChristian/remnant.truechristian.church/actions/runs/42792163904)
passed on website commit `46342ac8a0fac668400dbecda38a60f89736b9d9`:

- All 966 illustrated articles were checked at 1440px and 390px viewport widths
  (1,932 rendered pages). All 694 active prose floats retained their native
  dimensions, with no detected text/image overlap, clipped captions, horizontal
  overflow, or source-content changes.
- The 102 verse groups in 92 articles and 19 additional poetry controls were
  reviewed at both widths (222 pages), preserving printed line breaks and
  keeping enlarged illustrations beside the measured text column where they fit.
- All 26 focused/corpus checks and 17 separate permanent browser
  regression tests passed. Focused checks also cover narrow columns, larger
  reader text, right-to-left layouts, print, and JavaScript-disabled reading.
- The repository suite passed 528 Python tests (four existing source-cache
  skips) and all 90 Node tests. A structural pass across all 1,168 source articles
  preserved paragraphs, captions, image tags, and line-break counts and confirmed
  that applying the renderer a second time makes no further changes.

The temporary original-archive review harness is retained in that review commit
and its Actions artifact. It is removed from the final PR diff; the permanent
regression tests remain.

### Rule fields

`data/article-image-layouts.json` is the small editorial exception registry.
It records exact image basenames under permanent article UUIDs:

- `paired` contains ordered arrays of images forming one visual composition.
- `opening_order` gives the reviewed order of a complete opening image group
  immediately before the first paragraph. It applies only when every named
  image occurs once in a contiguous, caption-free figure; changed, missing,
  duplicated, captioned, or additional opening images leave the source order intact.
  In **Through the Eye of a Needle**, the two decorative book rows stay paired
  at the top and the cover follows them beside the opening paragraph, using the
  normal responsive wrapping rules.
- `standalone` lists images that need an independent reading-width block,
  including existing wide images whose presentation should be preserved.
- `wrap` permits reviewed small landscape photographs to wrap beside prose even
  when wider than the automatic aspect-ratio limit. The 480px source-width limit
  and all normal viewport, text-measure, and no-upscaling checks still apply.
  In **Technology Dictates Morality**, the phone-and-camera photo wraps beside
  the opening paragraph after the standalone banner. A preceding standalone
  figure does not prevent this wrapping; ordinary consecutive figures stay stacked.
- `verse_quote` identifies a unique image immediately after an opening verse
  quotation. A single paragraph with preserved printed line breaks and its
  original caption-free image form a measured verse row, in source order. In
  **The Power of God’s Word to Heal**, the image remains 241 × 360 to the right
  of its seven-line quotation. The row stacks when both cannot fit at that size.
- `paragraph_positions` maps image basenames to one-based direct article
  paragraph numbers. It moves the complete original figure, including its
  caption, immediately before the selected paragraph in the website only.
  Paragraphs inside quotations and captions do not count. Missing or repeated
  images, missing target paragraphs, nested figures, hidden content, and
  unexpected figure structure leave the source arrangement intact. This
  presentation rule does not modify archive HTML, image filenames, or index data.
- `paragraph_pair` contains two reviewed `{ "image": "basename", "side": "start" | "end" }`
  entries in their intended displayed order. It applies only to those two unique,
  adjacent single-image figures between ordinary paragraphs. Each complete figure,
  including its caption, moves immediately before one of those paragraphs;
  paragraph text and reading order stay intact. In **God’s Faithfulness Through
  Tragedy**, the family photograph moves beside the preceding paragraph at the
  logical end, and Nathanael’s portrait sits beside the following paragraph at
  the logical start. Missing or repeated images, extra figures, loose text,
  verse, or changed neighboring structure retain the source arrangement.
- `transparent_padding` maps a reviewed single image to its original `width` and
  `height` and the fully transparent `top`, `right`, `bottom`, and `left` insets,
  in source pixels. A responsive viewport hides only those empty edges, retains
  every visible pixel, and keeps the original image tag and caption. These images
  stay independent of galleries and floats; the rule also works without JavaScript,
  in RTL, and in print. Do not use it for white backgrounds or infer it from image
  dimensions. Verify the alpha bounds before adding or updating an entry.
- `opening_contour` identifies one caption-free leading `image`, its original
  `width` and `height`, the source-pixel `text_start`, and ordered `edges` rows
  of `[y, left, right]` enclosing the opaque wings around a transparent opening.
  These reviewed bounds create two physical half-width exclusion polygons. The
  renderer groups only that figure and its immediately following ordinary
  paragraph. A missing, repeated, moved, captioned, or structurally changed
  opening keeps the standard layout. Verify the complete alpha boundary before
  adding or updating a contour; dimensions alone do not establish transparency.
- `dimensions` records the original width and height of each reviewed paired
  image. The paired composition uses proportional columns and a common image
  height, preserving unequal panel widths without cropping or upscaling.

Review the actual images and their source context before adding a rule. Do not
infer a composition from similar dimensions, a shared filename prefix, or mere
adjacency. Do not use these rules to reorder article text or change source
content. The generator leaves ambiguous, missing, renamed, duplicated, or
caption-bearing nonadjacent panels in place; incomplete reviewed pairs cannot
silently become a different gallery with their neighbors.

`scripts/article_figures.py` inserts reader-only markup without reserializing
source content. `assets/article-figures.css` supplies static group layouts, and
`assets/article-figures.js` progressively enhances eligible text wrapping and
size-aware arrangements. Focused unit and browser checks protect source text,
image/caption retention, responsive grouping, reviewed compositions, RTL,
no-JavaScript reading, and print behavior.

The final orchid illustration in **Power, Love, and a Sound Mind** has a 460 × 901
canvas whose first 384 rows are entirely transparent. Its reviewed viewport is
460 × 517: it removes the empty top area and scales down on narrow screens,
without upscaling the flowers or changing the following Scripture quotation.
The rule uses the article UUID and image basename, so translations share it.
