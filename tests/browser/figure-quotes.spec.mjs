import { test, expect } from '@playwright/test';
import { fixtureAsset } from './fixture-assets.mjs';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const identity = '84da6b5d-046a-4fe1-bf3f-61c2036e789b';
const imageSource = `/images/articles/${identity}-1.jpg`;
const imageTag = `<img src="${imageSource}" alt="Portrait of Jonathan Edwards.">`;
const quotation = '“A faithful friendship grows through patient care, honest words, and shared hope. The affection that has joined us over many years is more than a passing feeling; it gives strength in difficulty and remains a lasting source of comfort.”';
const representative = `<article data-article-id="${identity}">
<p>An introduction establishes the subject before the portrait and its quotation.</p>
<figure>${imageTag}</figure>
<blockquote><p><em>${quotation}</em></p></blockquote>
<p>The following discussion begins at the full reading width below both the portrait and the quotation. It remains a separate paragraph in the original reading order.</p>
<blockquote><p><em>A later quotation keeps its usual border, spacing, and full reading width.</em></p></blockquote>
</article>`;
// Optional offline assets allow the same checks to review the real article.
// Normal regression runs use representative prose and a small local SVG fixture.
const source = process.env.QUOTE_SOURCE_PATH ? fs.readFileSync(process.env.QUOTE_SOURCE_PATH, 'utf8') : representative;
const picture = process.env.QUOTE_IMAGE_PATH
  ? { body: fs.readFileSync(process.env.QUOTE_IMAGE_PATH), contentType: 'image/jpeg' }
  : { body: '<svg xmlns="http://www.w3.org/2000/svg" width="108" height="171"><rect width="108" height="171" fill="#555"/><ellipse cx="54" cy="56" rx="27" ry="35" fill="#ddd"/><path d="M18 171V124Q54 90 90 124V171" fill="#aaa"/></svg>', contentType: 'image/svg+xml' };
const baseCss = process.env.QUOTE_THEME_PATH ? fs.readFileSync(process.env.QUOTE_THEME_PATH, 'utf8') : `
  *, *::before, *::after { box-sizing: border-box; }
  body { font-family: var(--tcc-font-body); }
  p { margin: 0; } img { display: block; height: auto; max-width: 100%; }
`;
const css = baseCss + '\n' + ['assets/site.css', 'assets/article-figures.css']
  .map(file => fs.readFileSync(file, 'utf8')).join('\n');
const fontFiles = new Map();
if (process.env.QUOTE_FONT_DIR) {
  for (const name of ['fonts.css', 'Raleway.woff2', 'Montserrat.woff2']) {
    fontFiles.set(`/quote-fonts/${name}`, {
      body: fs.readFileSync(path.join(process.env.QUOTE_FONT_DIR, name)),
      contentType: name.endsWith('.css') ? 'text/css' : 'font/woff2',
    });
  }
}
const transformed = new Map();
function arrange(input) {
  if (!transformed.has(input)) transformed.set(input, execFileSync('python3', ['-c', `
import sys
sys.path.insert(0, 'scripts')
from article_figures import arrange_article_figures, load_figure_rules
print(arrange_article_figures(sys.stdin.read(), load_figure_rules('data/article-image-layouts.json')))
`], { input, encoding: 'utf8' }));
  return transformed.get(input);
}

async function mount(page, { width = 1440, column = 750, direction = 'ltr', input = source } = {}) {
  const html = arrange(input);
  await page.setViewportSize({ width, height: 1000 });
  await page.unrouteAll({ behavior: 'wait' });
  await page.route('**/*', route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === imageSource) return route.fulfill(picture);
    if (fontFiles.has(pathname)) return route.fulfill(fontFiles.get(pathname));
    const asset = fixtureAsset(pathname);
    if (asset) return route.fulfill(asset);
    if (pathname !== '/quote-fixture/') return route.abort('blockedbyclient');
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html>
      <html lang="en" dir="${direction}"><head><meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      ${fontFiles.size ? '<link rel="stylesheet" href="/quote-fonts/fonts.css">' : ''}
      <style>${css}\nbody{margin:16px}.prose{max-width:${column}px;margin-inline:auto}</style>
      <script type="module" src="/assets/article-figures.js"></script></head>
      <body><main class="prose">${html}</main></body></html>` });
  });
  await page.goto('http://127.0.0.1:8080/quote-fixture/');
  await expect.poll(() => page.locator('article img').evaluate(image =>
    [image.complete, image.naturalWidth, image.naturalHeight])).toEqual([true, 108, 171]);
  if (fontFiles.size) {
    const loaded = await page.evaluate(async () => {
      const faces = await Promise.all(['21px Raleway', '600 21px Raleway', '64px Montserrat']
        .map(font => document.fonts.load(font)));
      await document.fonts.ready;
      return faces.map(font => font.length);
    });
    expect(loaded, 'The original-article review must use its offline reader fonts').toEqual([1, 1, 1]);
  }
}

async function measure(page, input = source) {
  return page.evaluate(input => {
    const article = document.querySelector('.prose article');
    const figure = article.querySelector('figure');
    const image = figure.querySelector('img');
    const quote = figure.nextElementSibling;
    const paragraph = quote.querySelector('p') || quote;
    const expected = new DOMParser().parseFromString(input, 'text/html').querySelector('article');
    const rect = element => {
      const { left, right, top, bottom, width, height } = element.getBoundingClientRect();
      return { left, right, top, bottom, width, height };
    };
    const attrs = element => Object.fromEntries([...element.attributes].map(attr => [attr.name, attr.value]));
    const quoteStyle = getComputedStyle(quote);
    const words = [];
    const walker = document.createTreeWalker(quote, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      for (const match of walker.currentNode.textContent.matchAll(/\S+/g)) {
        const range = document.createRange();
        range.setStart(walker.currentNode, match.index);
        range.setEnd(walker.currentNode, match.index + match[0].length);
        for (const box of range.getClientRects()) if (box.width && box.height) {
          words.push({ text: match[0], left: box.left, right: box.right, top: box.top, bottom: box.bottom });
        }
      }
    }
    return {
      reader: rect(article.closest('.prose')), figure: rect(figure), image: rect(image),
      quote: rect(quote), paragraph: rect(paragraph), next: rect(quote.nextElementSibling),
      words, direction: getComputedStyle(article).direction,
      float: getComputedStyle(figure).float, quoteDisplay: quoteStyle.display,
      border: parseFloat(quoteStyle.borderInlineStartWidth), borderColor: quoteStyle.borderInlineStartColor,
      padding: parseFloat(quoteStyle.paddingInlineStart), quoteFont: parseFloat(quoteStyle.fontSize),
      italic: getComputedStyle(quote.querySelector('em') || paragraph).fontStyle,
      otherQuotes: [...article.querySelectorAll('blockquote')].filter(node => node !== quote).map(node => ({
        ...rect(node), display: getComputedStyle(node).display,
        border: parseFloat(getComputedStyle(node).borderInlineStartWidth),
        padding: parseFloat(getComputedStyle(node).paddingInlineStart),
      })),
      imageCount: article.querySelectorAll('img').length,
      attributes: attrs(image), expectedAttributes: attrs(expected.querySelector('img')),
      paragraphs: [...article.querySelectorAll('p')].map(node => node.outerHTML),
      expectedParagraphs: [...expected.querySelectorAll('p')].map(node => node.outerHTML),
      quotes: [...article.querySelectorAll('blockquote')].map(node => node.outerHTML),
      expectedQuotes: [...expected.querySelectorAll('blockquote')].map(node => node.outerHTML),
      viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth,
    };
  }, input);
}

function expectPreserved(result) {
  expect(result.imageCount).toBe(1);
  expect(result.attributes).toEqual(result.expectedAttributes);
  expect(result.paragraphs).toEqual(result.expectedParagraphs);
  expect(result.quotes).toEqual(result.expectedQuotes);
  expect(result.image.width).toBeCloseTo(108, 1);
  expect(result.image.height).toBeCloseTo(171, 1);
  expect(result.scrollWidth).toBeLessThanOrEqual(result.viewport);
  expect(result.next.top + 0.5).toBeGreaterThanOrEqual(Math.max(result.image.bottom, result.quote.bottom));
  expect(result.next.width).toBeCloseTo(result.reader.width, 1);
  expect(result.border).toBe(2);
  expect(result.padding).toBeGreaterThanOrEqual(20);
  for (const word of result.words) {
    expect(word.left, word.text).toBeGreaterThanOrEqual(result.paragraph.left - 0.5);
    expect(word.right, word.text).toBeLessThanOrEqual(result.paragraph.right + 0.5);
    const overlapX = Math.min(word.right, result.image.right) - Math.max(word.left, result.image.left);
    const overlapY = Math.min(word.bottom, result.image.bottom) - Math.max(word.top, result.image.top);
    expect(overlapX > 0.5 && overlapY > 0.5, `${word.text} overlaps the portrait`).toBe(false);
  }
  for (const quote of result.otherQuotes) {
    expect(quote.display).toBe('block');
    expect(quote.width).toBeCloseTo(result.reader.width, 1);
    expect(quote.border).toBe(result.border);
    expect(quote.padding).toBe(result.padding);
  }
}

async function expectWrapped(page, { input = source } = {}) {
  await expect(page.locator('article figure')).toHaveClass(/article-figure--wrap/);
  const result = await measure(page, input);
  expectPreserved(result);
  expect(result.quoteDisplay).toBe('flow-root');
  expect(result.italic).toBe('italic');
  expect(Math.abs(result.image.top - result.quote.top)).toBeLessThan(1);
  expect(result.words.filter(word => word.top < result.image.bottom && word.bottom > result.image.top).length).toBeGreaterThan(5);
  expect(result.paragraph.width).toBeGreaterThanOrEqual(result.quoteFont * 14);
  const gap = result.direction === 'rtl'
    ? result.image.left - result.quote.right : result.quote.left - result.image.right;
  expect(gap).toBeGreaterThanOrEqual(24);
  expect(gap).toBeLessThanOrEqual(48);
  if (result.direction === 'rtl') {
    expect(result.image.right).toBeCloseTo(result.reader.right, 1);
    expect(result.quote.right - result.paragraph.right).toBeCloseTo(result.border + result.padding, 1);
  } else {
    expect(result.image.left).toBeCloseTo(result.reader.left, 1);
    expect(result.paragraph.left - result.quote.left).toBeCloseTo(result.border + result.padding, 1);
  }
  return result;
}

async function expectStacked(page, { print = false, input = source } = {}) {
  if (!print) await expect(page.locator('article figure')).not.toHaveClass(/article-figure--wrap/);
  const result = await measure(page, input);
  expectPreserved(result);
  expect(result.float).toBe('none');
  expect(result.quoteDisplay).toBe('block');
  expect(result.quote.top + 0.5).toBeGreaterThanOrEqual(result.image.bottom);
  expect(result.quote.width).toBeCloseTo(result.reader.width, 1);
  expect(Math.abs(result.image.left + result.image.right - result.reader.left - result.reader.right)).toBeLessThan(1);
  return result;
}

async function evidence(page, testInfo, name) {
  const geometry = await measure(page);
  const geometryPath = testInfo.outputPath(`${name}.json`);
  fs.writeFileSync(geometryPath, JSON.stringify(geometry, null, 2));
  await testInfo.attach(`${name}-geometry`, { path: geometryPath, contentType: 'application/json' });
  const offset = await page.evaluate(() => ({ x: scrollX, y: scrollY }));
  const top = Math.max(0, Math.min(geometry.image.top, geometry.quote.top) + offset.y - 45);
  const file = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path: file, fullPage: true, animations: 'disabled', clip: {
    x: Math.max(0, geometry.reader.left + offset.x - 16), y: top,
    width: Math.min(geometry.viewport, geometry.reader.width + 32),
    height: Math.min(geometry.next.bottom, geometry.next.top + 120) + offset.y + 16 - top,
  } });
  await testInfo.attach(name, { path: file, contentType: 'image/png' });
}

for (const width of [1440, 768]) {
  test(`reviewed portrait shares its quotation at ${width}px`, async ({ page }, testInfo) => {
    await mount(page, { width });
    await expectWrapped(page);
    await evidence(page, testInfo, `quote-${width}`);
  });
}

test('phones, narrow columns, and larger type restore normal quote blocks', async ({ page }, testInfo) => {
  await mount(page);
  await expectWrapped(page);
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    await expectStacked(page);
    await evidence(page, testInfo, `quote-mobile-${width}`);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator('.prose').evaluate(node => node.style.maxWidth = '500px');
  await expectStacked(page);
  await page.locator('.prose').evaluate(node => node.style.maxWidth = '750px');
  for (const size of [24, 28]) {
    await page.locator('.prose').evaluate((node, size) => node.style.fontSize = `${size}px`, size);
    await expectStacked(page);
  }
  await evidence(page, testInfo, 'quote-large-type');
  await page.locator('.prose').evaluate(node => node.style.fontSize = '18px');
  await expectWrapped(page);
});

test('RTL keeps the portrait at logical start with the quote beside it', async ({ page }, testInfo) => {
  await mount(page, { direction: 'rtl' });
  await expectWrapped(page);
  await evidence(page, testInfo, 'quote-rtl');
});

test('no JavaScript and print retain stacked, uncropped content', async ({ browser, page }, testInfo) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const noScript = await context.newPage();
    await mount(noScript);
    await expectStacked(noScript);
    await evidence(noScript, testInfo, 'quote-no-javascript');
  } finally { await context.close(); }
  await mount(page);
  await expectWrapped(page);
  await page.emulateMedia({ media: 'print' });
  await expectStacked(page, { print: true });
  await evidence(page, testInfo, 'quote-print');
  await page.emulateMedia({ media: 'screen' });
  await expectWrapped(page);
});

test('ordinary quotations wrap automatically while verse and incomplete structures stay stacked', async ({ page }) => {
  const unreviewed = representative.replace(identity, '00000000-0000-4000-8000-000000000001');
  await mount(page, { input: unreviewed });
  await expectWrapped(page, { input: unreviewed });
  const verse = representative.replace(`<em>${quotation}</em>`, '<em>First line of the quotation.<br>Second line stays separate.</em>');
  const nested = representative.replace(`<p><em>${quotation}</em></p>`, `<div><p><em>${quotation}</em></p></div>`);
  const missingParagraph = representative.replace(`<p><em>${quotation}</em></p>`, `<em>${quotation}</em>`);
  const empty = representative.replace(quotation, '');
  for (const input of [verse, nested, missingParagraph, empty]) {
    await mount(page, { input });
    await expectStacked(page, { input });
  }
});
