import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

const identity = 'a94bdd52-efcf-40e1-bbfd-33758f2b782e';
const filename = `${identity}-1.png`;
const imagePath = process.env.CONTOUR_IMAGE_PATH || `dist/images/articles/${filename}`;
if (!fs.existsSync(imagePath)) {
  throw new Error(`Missing contour artwork: ${imagePath}. Build the site or set CONTOUR_IMAGE_PATH to the original PNG.`);
}
const illustration = fs.readFileSync(imagePath);

// Keep the actual opening prose and image attributes. The production transformer
// supplies the reviewed contour; the test does not duplicate its polygons.
const source = `<article data-article-id="${identity}">
<figure>
  <img src="/images/articles/${filename}" alt="A wide view of workers gathering grain">
</figure>
<p>I want to show you clearly, from the word of God, that “tribulation worketh.” Tribulation has its place in your life today. As long as you are clothed in your body of flesh, it will be a part of your life. It is not something that you should try to run from. I don’t believe that you should try to run into it, but neither should you try to run from it, because God says that “tribulation worketh.”</p>
<p>For our Scripture passage, let’s turn to Romans chapter five. I’d like to read the first eight verses:</p>
</article>`;
const arranged = execFileSync('python3', ['-c', `
import sys
sys.path.insert(0, 'scripts')
from article_figures import arrange_article_figures, load_figure_rules
print(arrange_article_figures(sys.stdin.read(), load_figure_rules('data/article-image-layouts.json')))
`], { input: source, encoding: 'utf8' });
const css = ['assets/site.css', 'assets/article-figures.css']
  .map(file => fs.readFileSync(file, 'utf8')).join('\n');
const script = fs.readFileSync('assets/article-figures.js', 'utf8');
const openingSelector = '.article-contour-opening';
const activeClass = /article-contour-opening--active/;

async function mount(page, { width = 1440, column = 750, direction = 'ltr', serveImage } = {}) {
  await page.setViewportSize({ width, height: 1000 });
  await page.route('**/*', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === `/images/articles/${filename}`) {
      if (serveImage) return serveImage(route);
      return route.fulfill({ contentType: 'image/png', body: illustration });
    }
    if (path === '/assets/article-figures.js') {
      return route.fulfill({ contentType: 'text/javascript', body: script });
    }
    if (path === '/contour-fixture/') {
      return route.fulfill({ contentType: 'text/html', body: `<!doctype html>
        <html lang="en" dir="${direction}"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
          /* Minimal chrome reset; all article layout rules below are production CSS. */
          *, *::before, *::after { box-sizing: border-box; }
          body { margin: 16px; font-family: var(--tcc-font-body); }
          p { margin: 0; }
          img { display: block; max-width: 100%; }
          ${css}
          .prose { max-width: ${column}px; margin-inline: auto; }
        </style><script type="module" src="/assets/article-figures.js"></script>
        </head><body><main class="prose">${arranged}</main></body></html>` });
    }
    return route.fulfill({ status: 404, body: 'Not part of the contour fixture.' });
  });
  await page.goto('http://127.0.0.1:8080/contour-fixture/', { waitUntil: 'domcontentloaded' });
}

async function waitForImage(page) {
  await expect.poll(() => page.locator('article img').evaluate(image =>
    [image.complete, image.naturalWidth, image.naturalHeight])).toEqual([true, 1045, 261]);
}

async function measure(page, checkAlpha = false) {
  return page.evaluate(({ source, checkAlpha }) => {
    const article = document.querySelector('article');
    const opening = article.querySelector('.article-contour-opening');
    const figure = opening.querySelector('figure');
    const image = figure.querySelector('img');
    const paragraphs = [...article.querySelectorAll('p')];
    const paragraph = paragraphs[0];
    const expected = new DOMParser().parseFromString(source, 'text/html').querySelector('article');
    const rect = node => {
      const { left, right, top, bottom, width, height } = node.getBoundingClientRect();
      return { left, right, top, bottom, width, height };
    };
    const attributes = node => Object.fromEntries([...node.attributes].map(attr => [attr.name, attr.value]));
    const words = [];
    const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      for (const match of node.textContent.matchAll(/\S+/g)) {
        const range = document.createRange();
        range.setStart(node, match.index);
        range.setEnd(node, match.index + match[0].length);
        for (const box of range.getClientRects()) {
          if (box.width <= 0 || box.height <= 0) continue;
          words.push({ text: match[0], left: box.left, right: box.right,
            top: box.top, bottom: box.bottom });
        }
      }
    }
    const lines = [];
    for (const word of words) {
      let line = lines.find(candidate => Math.abs(candidate.top - word.top) < 0.75);
      if (!line) {
        line = { left: word.left, right: word.right, top: word.top, bottom: word.bottom };
        lines.push(line);
      }
      line.left = Math.min(line.left, word.left);
      line.right = Math.max(line.right, word.right);
      line.bottom = Math.max(line.bottom, word.bottom);
    }
    lines.sort((a, b) => a.top - b.top);
    const imageBox = rect(image);
    const alphaHits = [];
    let sampledPixels = 0;
    if (checkAlpha) {
      const canvas = document.createElement('canvas');
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const context = canvas.getContext('2d', { willReadFrequently: true });
      context.drawImage(image, 0, 0);
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
      const scaleX = canvas.width / imageBox.width;
      const scaleY = canvas.height / imageBox.height;
      for (const word of words) {
        const left = Math.max(word.left, imageBox.left);
        const right = Math.min(word.right, imageBox.right);
        const top = Math.max(word.top, imageBox.top);
        const bottom = Math.min(word.bottom, imageBox.bottom);
        if (left >= right || top >= bottom) continue;
        const x0 = Math.max(0, Math.floor((left - imageBox.left) * scaleX));
        const x1 = Math.min(canvas.width, Math.ceil((right - imageBox.left) * scaleX));
        const y0 = Math.max(0, Math.floor((top - imageBox.top) * scaleY));
        const y1 = Math.min(canvas.height, Math.ceil((bottom - imageBox.top) * scaleY));
        let hit = null;
        for (let y = y0; y < y1; y++) {
          for (let x = x0; x < x1; x++) {
            sampledPixels++;
            const alpha = pixels[(y * canvas.width + x) * 4 + 3];
            if (alpha > 0 && !hit) hit = { word: word.text, x, y, alpha };
          }
        }
        if (hit) alphaHits.push(hit);
      }
    }
    const edges = [...opening.querySelectorAll('.article-contour-edge')];
    return {
      image: imageBox, natural: [image.naturalWidth, image.naturalHeight],
      reader: rect(document.querySelector('.prose')), opening: rect(opening),
      paragraph: rect(paragraph), next: rect(paragraphs[1]), words, lines,
      fontSize: parseFloat(getComputedStyle(paragraph).fontSize),
      figurePosition: getComputedStyle(figure).position,
      imageTransform: getComputedStyle(image).transform,
      edgeBoxes: edges.map(rect), edgeDisplays: edges.map(edge => getComputedStyle(edge).display),
      edgesDecorative: edges.every(edge => edge.getAttribute('aria-hidden') === 'true' &&
        !edge.textContent && edge.children.length === 0),
      childTags: [...opening.children].map(node => node.tagName),
      nextIsSecondParagraph: opening.nextElementSibling === paragraphs[1],
      paragraphs: paragraphs.map(node => node.outerHTML),
      expectedParagraphs: [...expected.querySelectorAll('p')].map(node => node.outerHTML),
      imageAttributes: attributes(image), expectedImageAttributes: attributes(expected.querySelector('img')),
      imageCount: article.querySelectorAll('img').length, figureCount: article.querySelectorAll('figure').length,
      text: article.textContent.replace(/\s+/g, ' ').trim(),
      expectedText: expected.textContent.replace(/\s+/g, ' ').trim(),
      scrollWidth: document.documentElement.scrollWidth, viewport: innerWidth,
      sampledPixels, alphaHits,
    };
  }, { source, checkAlpha });
}

function expectPreservedAndContained(result, { loaded = true } = {}) {
  expect(result.paragraphs).toEqual(result.expectedParagraphs);
  expect(result.imageAttributes).toEqual(result.expectedImageAttributes);
  expect(result.text).toBe(result.expectedText);
  expect(result.imageCount).toBe(1);
  expect(result.figureCount).toBe(1);
  expect(result.childTags).toEqual(['FIGURE', 'SPAN', 'SPAN', 'P']);
  expect(result.edgesDecorative).toBe(true);
  expect(result.nextIsSecondParagraph).toBe(true);
  expect(result.scrollWidth).toBeLessThanOrEqual(result.viewport);
  expect(result.image.width).toBeLessThanOrEqual(result.reader.width + 0.5);
  expect(result.image.width).toBeLessThanOrEqual(1045);
  expect(result.imageTransform).toBe('none');
  expect(result.next.top + 0.5).toBeGreaterThanOrEqual(
    Math.max(result.opening.bottom, result.image.bottom, result.paragraph.bottom));
  for (const word of result.words) {
    expect(word.left, word.text).toBeGreaterThanOrEqual(result.reader.left - 0.5);
    expect(word.right, word.text).toBeLessThanOrEqual(result.reader.right + 0.5);
    expect(word.bottom, word.text).toBeLessThanOrEqual(result.opening.bottom + 0.5);
  }
  if (loaded) {
    expect(result.natural).toEqual([1045, 261]);
    expect(result.image.height / result.image.width).toBeCloseTo(261 / 1045, 3);
    expect(Math.abs((result.image.left + result.image.right) -
      (result.reader.left + result.reader.right))).toBeLessThan(1);
  }
}

async function expectContour(page) {
  await waitForImage(page);
  await expect(page.locator(openingSelector)).toHaveClass(activeClass);
  const result = await measure(page, true);
  expectPreservedAndContained(result);
  expect(result.alphaHits, 'No word rectangle may touch even partially opaque PNG pixels').toEqual([]);
  expect(result.sampledPixels).toBeGreaterThan(1000);
  const shapedLines = result.lines.filter(line => line.top < result.image.bottom && line.bottom > result.image.top);
  expect(shapedLines.length, 'The opening must actually enter the transparent arch').toBeGreaterThanOrEqual(2);
  expect(result.lines.some(line => line.top >= result.image.bottom), 'Long prose continues below the image').toBe(true);
  // Word packing need not be monotonic or symmetric, but later lines must
  // occupy substantially more width as the transparent opening grows.
  const first = shapedLines[0];
  expect(Math.max(...shapedLines.slice(1).map(line => line.right - line.left)),
    'Later lines should widen with the transparent opening')
    .toBeGreaterThan(first.right - first.left + result.fontSize * 3);
  expect(result.figurePosition).toBe('absolute');
  expect(result.edgeDisplays).toEqual(['block', 'block']);
  // These remain physical image edges even when the document is right-to-left.
  expect(Math.abs(result.edgeBoxes[0].left - result.image.left)).toBeLessThan(0.5);
  expect(Math.abs(result.edgeBoxes[1].right - result.image.right)).toBeLessThan(0.5);
  expect(result.edgeBoxes[0].right).toBeLessThanOrEqual(result.edgeBoxes[1].left + 0.5);
  return result;
}

async function expectStacked(page, { loaded = true, mayRetainActiveClass = false } = {}) {
  if (loaded) await waitForImage(page);
  if (!mayRetainActiveClass) await expect(page.locator(openingSelector)).not.toHaveClass(activeClass);
  const result = await measure(page);
  expectPreservedAndContained(result, { loaded });
  expect(result.figurePosition).toBe('static');
  expect(result.edgeDisplays).toEqual(['none', 'none']);
  expect(result.paragraph.top + 0.5).toBeGreaterThanOrEqual(result.image.bottom);
  expect(result.lines[0].top + 0.5).toBeGreaterThanOrEqual(result.image.bottom);
}

async function screenshot(page, testInfo, name) {
  const path = testInfo.outputPath(`${name}.png`);
  await page.locator('article').screenshot({ path });
  await testInfo.attach(name, { path, contentType: 'image/png' });
}

for (const width of [1440, 768]) {
  test(`the original opening follows transparent pixels at ${width}px`, async ({ page }, testInfo) => {
    await mount(page, { width });
    await expectContour(page);
    await screenshot(page, testInfo, `contour-${width}`);
  });
}

test('mobile and a narrow reading column restore the stacked layout', async ({ page }, testInfo) => {
  await mount(page);
  await expectContour(page);
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    await expectStacked(page);
    await screenshot(page, testInfo, `stacked-${width}`);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expectContour(page);
  await page.locator('.prose').evaluate(node => node.style.maxWidth = '500px');
  await expectStacked(page);
  await screenshot(page, testInfo, 'stacked-column-500');
  await page.locator('.prose').evaluate(node => node.style.maxWidth = '750px');
  await expectContour(page);
});

test('increased reading font restores the stack without a viewport resize', async ({ page }, testInfo) => {
  await mount(page);
  await expectContour(page);
  for (const size of [24, 28]) {
    await page.locator('.prose').evaluate((node, value) => node.style.fontSize = `${value}px`, size);
    await expectStacked(page);
    await screenshot(page, testInfo, `stacked-font-${size}`);
  }
  await page.locator('.prose').evaluate(node => node.style.fontSize = '18px');
  await expectContour(page);
});

test('RTL prose uses the same physical alpha contours', async ({ page }, testInfo) => {
  await mount(page, { direction: 'rtl' });
  await expectContour(page);
  await screenshot(page, testInfo, 'contour-rtl');
});

test('without JavaScript the intact image stays above the paragraph', async ({ browser }, testInfo) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const page = await context.newPage();
    await mount(page);
    await expectStacked(page);
    await screenshot(page, testInfo, 'stacked-no-javascript');
  } finally {
    await context.close();
  }
});

test('print restores the stack and returning to screen restores the contour', async ({ page }, testInfo) => {
  await mount(page);
  await expectContour(page);
  await page.emulateMedia({ media: 'print' });
  // The screen-only enhancement may retain its class; print must still be safe.
  await expectStacked(page, { mayRetainActiveClass: true });
  await screenshot(page, testInfo, 'stacked-print');
  await page.emulateMedia({ media: 'screen' });
  await expectContour(page);
});

test('the contour activates only after the real image finishes loading', async ({ page }, testInfo) => {
  let release;
  const pendingImage = new Promise(resolve => { release = resolve; });
  try {
    await mount(page, { serveImage: async route => {
      await pendingImage;
      await route.fulfill({ contentType: 'image/png', body: illustration });
    } });
    await expect(page.locator('article img')).toHaveJSProperty('complete', false);
    await expectStacked(page, { loaded: false });
    release();
    await expectContour(page);
    await screenshot(page, testInfo, 'contour-delayed-image');
  } finally {
    release();
  }
});

for (const failure of ['broken', 'wrong-dimensions']) {
  test(`${failure} artwork keeps a safe stacked opening`, async ({ page }, testInfo) => {
    await mount(page, { serveImage: route => failure === 'broken'
      ? route.fulfill({ status: 404, body: 'Missing artwork' })
      : route.fulfill({ contentType: 'image/svg+xml', body:
        '<svg xmlns="http://www.w3.org/2000/svg" width="1046" height="261"><rect width="1046" height="261" fill="#eee"/></svg>' }) });
    await expect(page.locator('article img')).toHaveJSProperty('complete', true);
    await expect(page.locator('article img')).toHaveJSProperty('naturalWidth', failure === 'broken' ? 0 : 1046);
    await expectStacked(page, { loaded: false });
    await screenshot(page, testInfo, `stacked-${failure}`);
  });
}
