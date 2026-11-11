# Reviewed opening compositions and long contributor credits

These are website-only arrangements in the existing
`data/article-image-layouts.json` registry. The English archive, index, original
image files, Markdown, article words, emphasis, captions and printed verse
line breaks remain unchanged. Complete original figures may move; text never
changes its reading order.

## Reviewed articles

- **Soul Sculpture:** the two introductory book/publisher credit paragraphs form
  an aside using the existing site notice treatment. The first illustration
  follows the note and wraps beside the first main paragraph at native size.
- **Keep Thy Heart With All Diligence:** the whole original poem remains one
  uninterrupted column. Both pictures form a nearby, top-aligned illustration
  column; small poem artwork can enlarge within the available measure.
- **Konkomba Testimonies:** the mission emblem stays centered. The second photo
  follows the Scripture quotation and wraps beside the first main paragraph,
  at the explicitly approved display width of 400px. Its 1276×1059 source is
  unchanged. Changed source dimensions disable this size-specific enhancement.
- **William Law:** the original first two illustrations frame the opening
  quotation at its physical upper-left and lower-right corners, at native size.
  CSS exclusion shapes reserve their rectangular footprints. Bounded layout
  measurement keeps the lower corner against the quote instead of leaving a
  large empty area below the text. The following prose clears the composition.
- **Year End Financial Report:** the first figure moves beside the first main
  paragraph. Explicitly reviewed lists flow beside their original illustrations
  and regain the full column underneath, retaining native list semantics.
- **Amy Carmichael of Dohnavur:** the first paragraph spans the full column. The
  complete portrait and caption accompany the following Scripture quotation;
  the photograph retains its 240×365 dimensions.
- **The Sisters Holy Desires:** long contributor bylines use responsive columns
  in the article header and listing cards. All original names and links remain
  visible in DOM/keyboard order. The same CSS applies to other bylines with at
  least six direct author links; ordinary credits are unchanged.
- **They Crucified God:** its unchanged illustration is right-aligned immediately
  above, not floated through, the complete poem.
- **Dry, Shriveled Seeds or Mature, Productive Plants?:** the first mission emblem
  stays centered. The seed and fruit pictures stay together beside paragraph
  one at their native dimensions where they fit.
- **Two Sacrifices:** the first source illustration wraps beside paragraph one;
  the second source image (the mission logo) is an independent centered block.

## Registry and rendering

The optional `editorial` object contains `kind` and ordered image basenames.
Supported kinds are `source-note`, `verse-pictures`, `quote-frame`,
`quote-portrait`, `prose-pair`, `reduced-prose`, and `poem-heading`.
Only `reduced-prose` accepts `width` and `source_size: [width, height]`.
The existing `paragraph_positions` rule performs approved paragraph placement
before grouping. `list_flow` opts in exact image basenames whose immediately
following list, optionally preceded by one ordinary paragraph, may flow.

`scripts/article_editorial.py` uses the existing offset-based HTML parser and
copies original nodes rather than serializing or rewriting them. It requires
unique direct-child figures, contiguous safe boundaries and the expected
paragraph/quotation/poem structure. Missing, repeated, hidden, nested or changed
structures retain the ordinary layout. Corner-frame illustrations must be
caption-free because their exclusion geometry describes the image only.
Applying the renderer twice makes no further changes.

`assets/article-editorial.css` is imported by the shared site stylesheet so long
credits work on cards as well as article pages. `assets/article-editorial.js`
is imported by the existing article enhancement. It uses image readiness,
actual line measures, font loading, column resize and breakpoint changes.
Unreadable narrow layouts, larger reading text, broken images and unsupported
shape rendering fall back to complete stacked content. Print disables floats
and corner positioning. No-JavaScript readers receive all content and images
without depending on the measured arrangements.

## Regression coverage

`tests/test_article_editorial.py` checks source fidelity, composition boundaries,
idempotence, captions, list semantics, and invalid/conflicting registry entries.
`tests/browser/editorial-layouts.spec.mjs` checks all ten real generated readers,
390px/320px screens, native sizes, the explicit photo reduction, quote/image
clearance, compact contributor cards, RTL, large text, print, missing/changed
images, and JavaScript-disabled reading. The normal complete PR browser workflow
runs these alongside the existing suite; no production checks are bypassed.
