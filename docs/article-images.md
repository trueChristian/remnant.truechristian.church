# Article image layouts

The reader arranges source images for the available reading width. Article text,
image bytes, alt text, captions, credits, and Markdown remain authoritative
upstream content; the website adds presentation wrappers and classes only.
It does not crop visible artwork, retouch, replace, or upscale the archive's images.
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
and galleries clear the complete figure and caption. Narrow screens, narrow
columns, and print remove text wrapping. Logical float sides follow the text
language; physical sides of a paired composition do not reverse.

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

`data/article-image-layouts.json` is the small editorial exception registry.
It records exact image basenames under permanent article UUIDs:

- `paired` contains ordered arrays of images forming one visual composition.
- `standalone` lists images that need an independent reading-width block,
  including existing wide images whose presentation should be preserved.
- `transparent_padding` maps a reviewed single image to its original `width` and
  `height` and the fully transparent `top`, `right`, `bottom`, and `left` insets,
  in source pixels. A responsive viewport hides only those empty edges, retains
  every visible pixel, and keeps the original image tag and caption. These images
  stay independent of galleries and floats; the rule also works without JavaScript,
  in RTL, and in print. Do not use it for white backgrounds or infer it from image
  dimensions. Verify the alpha bounds before adding or updating an entry.
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
