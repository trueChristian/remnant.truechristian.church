import { test, expect } from '@playwright/test';
import { fixtureAsset } from './fixture-assets.mjs';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const identity = 'e94f1b0c-ab32-4323-8d3b-4bc60ea82ace';
const imageSource = `/images/articles/${identity}-1.jpg`;
const secondSource = `/images/articles/${identity}-2.jpg`;
const prose = 'A clear reading column gives each thought room to develop. The illustration can remain at its original size while the words continue alongside it, then return to the full width below. Readers should be able to follow each sentence comfortably without losing the order of the paragraphs. ';
const representative = `<article data-article-id="${identity}">
<blockquote><p><em>An opening line remains intact;<br>and another line;<br>and a third;<br>and a final line.</em></p><p>An unchanged reference.</p></blockquote>
<figure><img src="${imageSource}" alt="A tall illustration."></figure>
<p>${prose.repeat(3)}</p><p>${prose.repeat(2)}</p>
<h2>A later section</h2><p>The next illustration retains its separate place.</p>
<figure><img src="${secondSource}" alt="A second illustration."></figure>
<p>${prose.repeat(2)}</p></article>`;
// Representative content keeps this regression independent of upstream wording.
// Optional offline assets exercise the exact article in a visual review.
const source = process.env.LION_SOURCE_PATH ? fs.readFileSync(process.env.LION_SOURCE_PATH, 'utf8') : representative;
const svg = (width, height) => ({ contentType: 'image/svg+xml',
  body: `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="#a5a5a5"/><path d="M12 12H${width - 12}V${height - 12}H12Z" fill="none" stroke="#555"/></svg>` });
const files = new Map([
  [imageSource, process.env.LION_IMAGE_PATH ? { body: fs.readFileSync(process.env.LION_IMAGE_PATH), contentType: 'image/jpeg' } : svg(242, 429)],
  [secondSource, process.env.LION_SECOND_IMAGE_PATH ? { body: fs.readFileSync(process.env.LION_SECOND_IMAGE_PATH), contentType: 'image/jpeg' } : svg(287, 358)],
]);
const fontFiles = new Map();
if (process.env.LION_FONT_DIR) for (const name of ['fonts.css', 'Raleway.woff2', 'Montserrat.woff2']) {
  fontFiles.set(`/lion-fonts/${name}`, { body: fs.readFileSync(path.join(process.env.LION_FONT_DIR, name)),
    contentType: name.endsWith('.css') ? 'text/css' : 'font/woff2' });
}
const baseCss = process.env.LION_THEME_PATH ? fs.readFileSync(process.env.LION_THEME_PATH, 'utf8') : `
  *,*::before,*::after{box-sizing:border-box}body{font-family:var(--tcc-font-body)}
  p{margin:0}img{display:block;max-width:100%;height:auto}
`;
const css = baseCss + '\n' + ['assets/site.css', 'assets/article-figures.css']
  .map(file => fs.readFileSync(file, 'utf8')).join('\n');
const arranged = execFileSync('python3', ['-c', `
import sys
sys.path.insert(0, 'scripts')
from article_figures import arrange_article_figures, load_figure_rules
print(arrange_article_figures(sys.stdin.read(), load_figure_rules('data/article-image-layouts.json')))
`], { input: source, encoding: 'utf8' });
const portrait = page => page.locator(`figure:has(img[src="${imageSource}"])`);

async function mount(page, { width = 1440, column = 750, direction = 'ltr', fontSize } = {}) {
  await page.setViewportSize({ width, height: 1000 });
  await page.unrouteAll({ behavior: 'wait' });
  await page.route('**/*', route => {
    const pathname = new URL(route.request().url()).pathname;
    if (files.has(pathname)) return route.fulfill(files.get(pathname));
    if (fontFiles.has(pathname)) return route.fulfill(fontFiles.get(pathname));
    const asset = fixtureAsset(pathname);
    if (asset) return route.fulfill(asset);
    if (pathname !== '/native-figure-fixture/') return route.abort('blockedbyclient');
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html>
      <html lang="en" dir="${direction}"><head><meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      ${fontFiles.size ? '<link rel="stylesheet" href="/lion-fonts/fonts.css">' : ''}
      <style>${css}\nbody{margin:16px}.prose{max-width:${column}px;margin-inline:auto${fontSize ? `;font-size:${fontSize}px` : ''}}</style>
      <script type="module" src="/assets/article-figures.js"></script></head>
      <body><main class="prose">${arranged}</main></body></html>` });
  });
  await page.goto('http://127.0.0.1:8080/native-figure-fixture/');
  await expect.poll(() => page.locator('article img').evaluateAll(images => images.map(image =>
    [image.complete, image.naturalWidth, image.naturalHeight]))).toEqual([[true, 242, 429], [true, 287, 358]]);
  if (fontFiles.size) {
    const counts = await page.evaluate(async () => {
      const faces = await Promise.all(['18px Raleway', '600 18px Raleway'].map(font => document.fonts.load(font)));
      await document.fonts.ready;
      return faces.map(font => font.length);
    });
    expect(counts, 'The original-article review uses its offline reader fonts').toEqual([1, 1]);
  }
}

async function measure(page) {
  return page.evaluate(({ source, imageSource }) => {
    const article = document.querySelector('article');
    const figure = article.querySelector(`img[src="${imageSource}"]`).closest('figure');
    const image = figure.querySelector('img');
    const original = new DOMParser().parseFromString(source, 'text/html').querySelector('article');
    const rect = element => {
      const { left, right, top, bottom, width, height } = element.getBoundingClientRect();
      return { left, right, top, bottom, width, height };
    };
    const attributes = element => Object.fromEntries([...element.attributes].map(attr => [attr.name, attr.value]));
    const paragraphs = [];
    let next = figure.nextElementSibling;
    while (next?.tagName === 'P') { paragraphs.push(next); next = next.nextElementSibling; }
    const words = [];
    for (const paragraph of paragraphs) {
      const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) for (const match of walker.currentNode.textContent.matchAll(/\S+/g)) {
        const range = document.createRange();
        range.setStart(walker.currentNode, match.index);
        range.setEnd(walker.currentNode, match.index + match[0].length);
        for (const box of range.getClientRects()) if (box.width && box.height) {
          words.push({ text: match[0], left: box.left, right: box.right, top: box.top, bottom: box.bottom });
        }
      }
    }
    return { reader: rect(article.closest('.prose')), image: rect(image), figure: rect(figure),
      previous: rect(figure.previousElementSibling), paragraph: rect(paragraphs[0]),
      boundary: next ? rect(next) : null, words, float: getComputedStyle(figure).float,
      direction: getComputedStyle(article).direction, viewport: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      paragraphs: [...article.querySelectorAll('p')].map(node => node.outerHTML),
      expectedParagraphs: [...original.querySelectorAll('p')].map(node => node.outerHTML),
      quotes: [...article.querySelectorAll('blockquote')].map(node => node.outerHTML),
      expectedQuotes: [...original.querySelectorAll('blockquote')].map(node => node.outerHTML),
      images: [...article.querySelectorAll('img')].map(attributes),
      expectedImages: [...original.querySelectorAll('img')].map(attributes) };
  }, { source, imageSource });
}

function expectPreserved(result, { print = false } = {}) {
  expect(result.paragraphs).toEqual(result.expectedParagraphs);
  expect(result.quotes).toEqual(result.expectedQuotes);
  expect(result.images).toEqual(result.expectedImages);
  expect(result.image.width).toBeLessThanOrEqual(242.1);
  expect(result.image.height / result.image.width).toBeCloseTo(429 / 242, 3);
  if (!print) {
    expect(result.image.width).toBeCloseTo(242, 1);
    expect(result.image.height).toBeCloseTo(429, 1);
  }
  expect(result.scrollWidth).toBeLessThanOrEqual(result.viewport);
  expect(result.previous.bottom).toBeLessThanOrEqual(result.image.top + 0.5);
  if (result.boundary) expect(result.boundary.top + 0.5).toBeGreaterThanOrEqual(result.image.bottom);
  for (const word of result.words) {
    expect(word.left, word.text).toBeGreaterThanOrEqual(result.reader.left - 0.5);
    expect(word.right, word.text).toBeLessThanOrEqual(result.reader.right + 0.5);
    const x = Math.min(word.right, result.image.right) - Math.max(word.left, result.image.left);
    const y = Math.min(word.bottom, result.image.bottom) - Math.max(word.top, result.image.top);
    expect(x > 0.5 && y > 0.5, `${word.text} overlaps the lion`).toBe(false);
  }
}

async function expectWrapped(page) {
  await expect(portrait(page)).toHaveClass(/article-figure--wrap/);
  const result = await measure(page);
  expectPreserved(result);
  const rtl = result.direction === 'rtl';
  expect(result.float).toBe('inline-start');
  expect(Math.abs((rtl ? result.image.right - result.reader.right : result.image.left - result.reader.left))).toBeLessThan(0.5);
  const alongside = result.words.filter(word => word.top < result.image.bottom && word.bottom > result.image.top);
  expect(alongside.length).toBeGreaterThan(10);
  const below = result.words.filter(word => word.top >= result.image.bottom + 30);
  expect(below.length).toBeGreaterThan(0);
  if (rtl) expect(Math.max(...below.map(word => word.right))).toBeGreaterThan(result.image.left + 20);
  else expect(Math.min(...below.map(word => word.left))).toBeLessThan(result.image.right - 20);
  return result;
}

async function expectStacked(page, { print = false } = {}) {
  if (!print) await expect(portrait(page)).not.toHaveClass(/article-figure--wrap/);
  const result = await measure(page);
  expectPreserved(result, { print });
  expect(result.float).toBe('none');
  expect(result.paragraph.top + 0.5).toBeGreaterThanOrEqual(result.image.bottom);
  expect(Math.abs(result.image.left + result.image.right - result.reader.left - result.reader.right)).toBeLessThan(1);
  return result;
}

async function evidence(page, testInfo, name) {
  const result = await measure(page);
  const jsonPath = testInfo.outputPath(`${name}.json`);
  fs.writeFileSync(jsonPath, JSON.stringify(result, null, 2));
  await testInfo.attach(`${name}-geometry`, { path: jsonPath, contentType: 'application/json' });
  const clip = await page.evaluate(({ top, bottom }) => {
    const reader = document.querySelector('.prose').getBoundingClientRect();
    return { x: Math.max(0, reader.left - 16), y: Math.max(0, top + scrollY - 16),
      width: Math.min(innerWidth, reader.width + 32), height: bottom - top + 32 };
  }, { top: result.previous.top, bottom: result.boundary?.bottom ?? result.paragraph.bottom });
  const screenshotPath = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path: screenshotPath, fullPage: true, clip, animations: 'disabled' });
  await testInfo.attach(name, { path: screenshotPath, contentType: 'image/png' });
}

test('the reviewed lion wraps left at full native size, including the 612px boundary', async ({ page }, testInfo) => {
  for (const column of [750, 612]) {
    await mount(page, { column });
    await expectWrapped(page);
    await evidence(page, testInfo, `lion-desktop-${column}`);
  }
});

test('a narrow column, mobile, and large reader text stack instead of shrinking the lion', async ({ page }, testInfo) => {
  for (const options of [{ column: 611 }, { width: 390 }, { width: 320 }, { fontSize: 24 }, { fontSize: 28 }]) {
    await mount(page, options);
    await expectStacked(page);
    if (options.column === 611 || options.width === 390) await evidence(page, testInfo,
      options.width ? `lion-mobile-${options.width}` : `lion-narrow-${options.column}`);
  }
});

test('native-size wrapping follows RTL reading direction without changing the image', async ({ page }) => {
  await mount(page, { direction: 'rtl' });
  await expectWrapped(page);
});

test('print and JavaScript-disabled reading retain the complete epigraph and stacked artwork', async ({ browser, page }, testInfo) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const noScript = await context.newPage();
    await mount(noScript);
    await expectStacked(noScript);
  } finally { await context.close(); }
  await mount(page);
  await expectWrapped(page);
  await page.emulateMedia({ media: 'print' });
  await expectStacked(page, { print: true });
  await evidence(page, testInfo, 'lion-print');
});
