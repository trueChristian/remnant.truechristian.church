# Mission openings and continuous verse

The next reviewed batch uses the existing standalone, native prose wrapping,
paragraph-position and paired-image policies wherever possible:

- Children or Kids: the goat pair remains centered above the opening, with the
  child at the first paragraph. The pair has recorded source dimensions.
- The Foolish, Weak, Nonexistent Things; The Year 2000; Holy Sacrifices: a centered
  mission globe is separate from the native-size illustration at paragraph one.
  Holy Sacrifices retains its complete epigraph and heading above that paragraph.
- Gospel-Spreading: the sower and captioned photograph form a native-size pair
  after the first two prose paragraphs. The globe remains above the epigraph.
- Painful Realities: only the 99×48 ministry logo is enlarged, to 150px wide;
  the portrait wraps at 179×245. Changed source dimensions cancel enlargement.
- Precious Letters from Our Readers, published alias `-24`: the first image wraps
  paragraph one and the flower moves immediately before the unchanged bullet list.
  The policy is tied to UUID `ff756543-8b73-4182-a901-596bfa199152`, not a guessed
  numbering of the many articles with this title.
- A Chosen Vessel: all nine stanza nodes remain in the original reading order.
  The three existing verse rows retain the same image-width calculation and text
  measures. Only the illustrations' vertical positions are independent of stanza
  heights; measured text rectangles prevent overlap. The normal stanza margin
  continues between rows instead of allowing tall cups to insert blank space.

Additional opt-in keys are `list_positions` (image basename to one-based direct
list number), `paragraph_gallery` (`images`, recorded `widths`, and
`after_paragraph`), `enlarged_standalone` (basename to `width` and `source_size`),
and `continuous_verse` (`images` in original order). Invalid, conflicting,
missing, duplicate, hidden or structurally different inputs are not composed.
Standalone enlargement is explicitly limited to at most twice the source width.
The independent gallery wraps onto separate rows on small screens; captions remain
with their complete figures. Continuous verse enhancement declines narrow columns,
large reader type, RTL, incomplete image loading and missing artwork. Print and
JavaScript-disabled reading retain the normal stacked, source-order layout.

`tests/test_article_openings.py` verifies these policies and source fidelity.
`tests/browser/mission-openings.spec.mjs` checks all eight real readers, native
wrapping, compact stanza spacing, before/after cup dimensions, unchanged content,
image/text clearance, desktop and phone widths, print, RTL and no-JavaScript reading.
