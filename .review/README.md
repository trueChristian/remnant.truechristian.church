# Temporary God Changes Water into Wine review

This directory is review infrastructure only. Remove it and the temporary workflow
after inspecting the hosted browser result; it is not part of the permanent fix.

Run from the website repository root:

```sh
npx playwright test --config .review/playwright.config.mjs
```

The five focused cases use no HTTP server or runtime network downloads. Playwright
routes the exact edited archive source, five original images, production figure
module, and offline font files. The production Python transformer reads the current
`data/article-image-layouts.json`; production article CSS is read directly from
`assets/`. The theme CSS is the website's pinned theme revision. Font provenance and
licenses are in `fonts/`.

`water-wine-source.html` is the exact article file from archive PR #188, commit
`9ef58db1`. It preserves the source emblem/editor note/drop cap/Scripture quotation,
all five image tags and attributes, and every original paragraph.

The cases cover 1440px and 768px desktop wrapping, 390px and 320px mobile stacking,
24px and 28px reading fonts, JavaScript disabled, and print. Checks inspect word
rectangles beside each moved image, drop-cap collisions, full-width text below the
floats, section clearing, exact source markup, original image sizes and order, and
page overflow. Screenshots and geometry attachments are written under
`.test-output/water-wine/`; desktop/mobile evidence includes the opening, Need, and
Clean Vessels sections.

Binary assets required for publication are the five files under `images/` and the
two WOFF2 files under `fonts/`. All other files in this directory are text.
