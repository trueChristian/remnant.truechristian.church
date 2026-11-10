import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const identity = '533e049a-b6ef-473a-ad9f-6b62f7c04d83';
const imageSource = `/images/articles/${identity}-1.jpg`;
const representative = `<article data-article-id="${identity}">
<blockquote><p><em>Each printed line keeps its own clear place<br>The illustration stays beside these words<br>A reader can follow the original thought<br>The lines preserve the writer's chosen form<br>The passage can stand together on the page<br>And the final sentence remains unchanged<br>An unchanged reference</em></p></blockquote>
<figure><img src="${imageSource}" alt="An illustration beside an opening quotation."></figure>
<p><em>This introduction remains below the complete opening quotation and illustration. Its original wording and printed break stay intact.<br>—An unchanged byline</em></p>
<p>The following discussion keeps the full reading column and its original place in the article.</p>
</article>`;
// Normal regression uses representative prose and an intrinsic-size SVG.
// Optional offline files exercise the original article and reader typography.
const source = process.env.HEALING_SOURCE_PATH ? fs.readFileSync(process.env.HEALING_SOURCE_PATH, 'utf8') : representative;
const picture = process.env.HEALING_IMAGE_PATH
  ? { body: fs.readFileSync(process.env.HEALING_IMAGE_PATH), contentType: 'image/jpeg' }
  : { contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="241" height="360"><rect width="241" height="360" fill="#aaa"/><path d="M12 12H229V348H12Z" fill="none" stroke="#555"/></svg>' };
const baseCss = process.env.HEALING_THEME_PATH ? fs.readFileSync(process.env.HEALING_THEME_PATH, 'utf8') : `
  *,*::before,*::after{box-sizing:border-box}body{font-family:var(--tcc-font-body)}
  p{margin:0}img{display:block;max-width:100%;height:auto}
`;
const css = baseCss + '\n' + ['assets/site.css', 'assets/article-figures.css']
  .map(file => fs.readFileSync(file, 'utf8')).join('\n');
const script = fs.readFileSync('assets/article-figures.js', 'utf8');
const fontFiles = new Map();
if (process.env.HEALING_FONT_DIR) for (const name of ['fonts.css', 'Raleway.woff2', 'Montserrat.woff2']) {
  fontFiles.set(`/healing-fonts/${name}`, { body: fs.readFileSync(path.join(process.env.HEALING_FONT_DIR, name)),
    contentType: name.endsWith('.css') ? 'text/css' : 'font/woff2' });
}
const arranged = execFileSync('python3', ['-c', `
import sys
sys.path.insert(0, 'scripts')
from article_figures import arrange_article_figures, load_figure_rules
print(arrange_article_figures(sys.stdin.read(), load_figure_rules('data/article-image-layouts.json')))
`], { input: source, encoding: 'utf8' });
const row = page => page.locator('.article-verse-row');

async function mount(page, { width = 1440, column = 750, fontSize, quoteFontSize } = {}) {
  await page.setViewportSize({ width, height: 1000 });
  await page.unrouteAll({ behavior: 'wait' });
  await page.route('**/*', route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === imageSource) return route.fulfill(picture);
    if (fontFiles.has(pathname)) return route.fulfill(fontFiles.get(pathname));
    if (pathname === '/assets/article-figures.js') return route.fulfill({ contentType: 'text/javascript', body: script });
    if (pathname !== '/native-verse-quote-fixture/') return route.abort('blockedbyclient');
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html>
      <html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
      ${fontFiles.size ? '<link rel="stylesheet" href="/healing-fonts/fonts.css">' : ''}
      <style>${css}\nbody{margin:16px}.prose{max-width:${column}px;margin-inline:auto${fontSize ? `;font-size:${fontSize}px` : ''}}
      ${quoteFontSize ? `.prose blockquote{font-size:${quoteFontSize}px}` : ''}</style>
      <script type="module" src="/assets/article-figures.js"></script></head>
      <body><main class="prose">${arranged}</main></body></html>` });
  });
  await page.goto('http://127.0.0.1:8080/native-verse-quote-fixture/');
  await expect(row(page)).toHaveCount(1);
  await expect.poll(() => page.locator('article img').evaluateAll(images => images.map(image =>
    [image.complete, image.naturalWidth, image.naturalHeight]))).toEqual([[true, 241, 360]]);
  if (fontFiles.size) {
    const faces = await page.evaluate(async () => {
      const loaded = await Promise.all(['italic 21px Raleway', '64px Montserrat']
        .map(font => document.fonts.load(font)));
      await document.fonts.ready;
      return loaded.map(font => font.length);
    });
    expect(faces, 'The original-article review uses its offline reader fonts').toEqual([1, 1]);
  }
}

async function measure(page) {
  return page.evaluate(source => {
    const article = document.querySelector('article');
    const group = article.querySelector('.article-verse-row');
    const quote = group.querySelector('blockquote');
    const figure = group.querySelector('figure');
    const image = figure.querySelector('img');
    const expected = new DOMParser().parseFromString(source, 'text/html').querySelector('article');
    const rect = element => {
      const { left, right, top, bottom, width, height } = element.getBoundingClientRect();
      return { left, right, top, bottom, width, height };
    };
    const attrs = element => Object.fromEntries([...element.attributes].map(attr => [attr.name, attr.value]));
    const quoteAttrs = element => Object.fromEntries([...element.attributes]
      .filter(attr => attr.name !== 'class').map(attr => [attr.name, attr.value]));
    const words = [];
    let segment = 0;
    const walker = document.createTreeWalker(quote, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.nodeType === Node.ELEMENT_NODE) { if (node.tagName === 'BR') segment += 1; continue; }
      for (const match of node.textContent.matchAll(/\S+/g)) {
        const range = document.createRange();
        range.setStart(node, match.index);
        range.setEnd(node, match.index + match[0].length);
        for (const box of range.getClientRects()) if (box.width && box.height) words.push({
          text: match[0], segment, left: box.left, right: box.right, top: box.top, bottom: box.bottom,
        });
      }
    }
    const style = getComputedStyle(quote);
    return { reader: rect(article.closest('.prose')), row: rect(group), rowDisplay: getComputedStyle(group).display,
      quote: rect(quote), paragraph: rect(quote.querySelector('p')), figure: rect(figure), image: rect(image),
      intro: rect(group.nextElementSibling), introHtml: group.nextElementSibling.outerHTML,
      expectedIntro: expected.querySelector('figure').nextElementSibling.outerHTML,
      quoteFont: parseFloat(style.fontSize), border: parseFloat(style.borderInlineStartWidth),
      padding: parseFloat(style.paddingInlineStart), italic: getComputedStyle(quote.querySelector('em')).fontStyle,
      quoteHtml: quote.innerHTML, expectedQuoteHtml: expected.querySelector('blockquote').innerHTML,
      quoteAttributes: quoteAttrs(quote), expectedQuoteAttributes: quoteAttrs(expected.querySelector('blockquote')),
      quoteClasses: [...quote.classList], expectedQuoteClasses: [...expected.querySelector('blockquote').classList],
      figureHtml: figure.innerHTML, expectedFigureHtml: expected.querySelector('figure').innerHTML,
      imageCount: article.querySelectorAll('img').length, attributes: attrs(image),
      expectedAttributes: attrs(expected.querySelector('img')),
      paragraphs: [...article.querySelectorAll('p')].map(node => node.outerHTML),
      expectedParagraphs: [...expected.querySelectorAll('p')].map(node => node.outerHTML),
      text: article.textContent, expectedText: expected.textContent,
      breaks: quote.querySelectorAll('br').length, quoteBeforeFigure: Boolean(quote.compareDocumentPosition(figure) & Node.DOCUMENT_POSITION_FOLLOWING),
      words, segments: segment + 1, viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth };
  }, source);
}

function expectPreserved(result, { print = false } = {}) {
  expect(result.imageCount).toBe(1);
  expect(result.attributes).toEqual(result.expectedAttributes);
  expect(result.figureHtml).toBe(result.expectedFigureHtml);
  expect(result.quoteHtml).toBe(result.expectedQuoteHtml);
  expect(result.quoteAttributes).toEqual(result.expectedQuoteAttributes);
  expect(result.quoteClasses).toEqual(result.expectedQuoteClasses);
  expect(result.paragraphs).toEqual(result.expectedParagraphs);
  expect(result.text).toBe(result.expectedText);
  expect(result.introHtml).toBe(result.expectedIntro);
  expect(result.quoteBeforeFigure).toBe(true);
  expect(result.breaks).toBe(6);
  expect(result.segments).toBe(7);
  expect(result.italic).toBe('italic');
  expect(result.border).toBe(2);
  expect(result.padding).toBeGreaterThanOrEqual(20);
  expect(result.image.width).toBeLessThanOrEqual(241.1);
  expect(result.image.height / result.image.width).toBeCloseTo(360 / 241, 3);
  if (!print) {
    expect(result.image.width).toBeCloseTo(241, 1);
    expect(result.image.height).toBeCloseTo(360, 1);
  }
  expect(result.image.left).toBeGreaterThanOrEqual(result.reader.left - 0.5);
  expect(result.image.right).toBeLessThanOrEqual(result.reader.right + 0.5);
  expect(result.intro.top + 0.5).toBeGreaterThanOrEqual(Math.max(result.quote.bottom, result.image.bottom, result.row.bottom));
  expect(result.intro.width).toBeCloseTo(result.reader.width, 1);
  expect(result.scrollWidth).toBeLessThanOrEqual(result.viewport);
  for (const word of result.words) {
    expect(word.left, word.text).toBeGreaterThanOrEqual(result.paragraph.left - 0.5);
    expect(word.right, word.text).toBeLessThanOrEqual(result.paragraph.right + 0.5);
    const x = Math.min(word.right, result.image.right) - Math.max(word.left, result.image.left);
    const y = Math.min(word.bottom, result.image.bottom) - Math.max(word.top, result.image.top);
    expect(x > 0.5 && y > 0.5, `${word.text} overlaps the illustration`).toBe(false);
  }
}

async function expectBeside(page) {
  await expect(row(page)).toHaveClass(/article-verse-row--aside/);
  const result = await measure(page);
  expectPreserved(result);
  expect(result.rowDisplay).toBe('grid');
  expect(result.quote.left).toBeCloseTo(result.reader.left, 1);
  expect(Math.abs(result.quote.top - result.image.top)).toBeLessThanOrEqual(8);
  expect(Math.abs(result.words[0].top - result.image.top)).toBeLessThan(result.quoteFont * 1.2);
  const gap = result.image.left - result.quote.right;
  expect(gap).toBeGreaterThanOrEqual(24);
  expect(gap).toBeLessThanOrEqual(48);
  const visibleGap = result.image.left - Math.max(...result.words.map(word => word.right));
  expect(visibleGap).toBeGreaterThanOrEqual(24);
  expect(visibleGap).toBeLessThanOrEqual(48);
  expect(new Set(result.words.map(word => Math.round(word.top))).size).toBe(7);
  for (let segment = 0; segment < 7; segment += 1) {
    expect(new Set(result.words.filter(word => word.segment === segment)
      .map(word => Math.round(word.top))).size, `Printed line ${segment + 1} stays intact`).toBe(1);
  }
  return result;
}

async function expectStacked(page, { print = false } = {}) {
  if (!print) await expect(row(page)).not.toHaveClass(/article-verse-row--aside/);
  const result = await measure(page);
  expectPreserved(result, { print });
  expect(result.rowDisplay).toBe('flow-root');
  expect(result.figure.top + 0.5).toBeGreaterThanOrEqual(result.quote.bottom);
  expect(result.quote.width).toBeCloseTo(result.reader.width, 1);
  expect(Math.abs(result.image.left + result.image.right - result.reader.left - result.reader.right)).toBeLessThan(1);
  return result;
}

async function evidence(page, testInfo, name) {
  const result = await measure(page);
  const jsonPath = testInfo.outputPath(`${name}.json`);
  fs.writeFileSync(jsonPath, JSON.stringify(result, null, 2));
  await testInfo.attach(`${name}-geometry`, { path: jsonPath, contentType: 'application/json' });
  const offset = await page.evaluate(() => ({ x: scrollX, y: scrollY }));
  const top = Math.max(0, result.row.top + offset.y - 16);
  const imagePath = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path: imagePath, fullPage: true, animations: 'disabled', clip: {
    x: Math.max(0, result.reader.left + offset.x - 16), y: top,
    width: Math.min(result.viewport, result.reader.width + 32),
    height: result.intro.bottom + offset.y + 16 - top,
  } });
  await testInfo.attach(name, { path: imagePath, contentType: 'image/png' });
}

test('the native illustration sits right of seven intact printed lines', async ({ page }, testInfo) => {
  for (const width of [1440, 768]) {
    await mount(page, { width });
    await expectBeside(page);
    await evidence(page, testInfo, `healing-desktop-${width}`);
  }
});

test('phones, narrow columns, and larger quotations stack without shrinking the illustration', async ({ page }, testInfo) => {
  for (const options of [{ width: 390 }, { width: 320 }, { column: 500 },
    { fontSize: 24, quoteFontSize: 28 }, { fontSize: 28, quoteFontSize: 32 }]) {
    await mount(page, options);
    await expectStacked(page);
    if (options.width === 390 || options.quoteFontSize === 28) await evidence(page, testInfo,
      options.width ? 'healing-mobile-390' : 'healing-large-type');
  }
});

test('print restores source reading order from the enhanced desktop opening', async ({ page }, testInfo) => {
  await mount(page);
  await expectBeside(page);
  await page.emulateMedia({ media: 'print' });
  await expectStacked(page, { print: true });
  await evidence(page, testInfo, 'healing-print');
  await page.emulateMedia({ media: 'screen' });
  await expectBeside(page);
});

test('JavaScript-disabled reading keeps the quotation, native photograph, and introduction', async ({ browser }, testInfo) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const page = await context.newPage();
    await mount(page);
    await expectStacked(page);
    await evidence(page, testInfo, 'healing-no-javascript');
  } finally { await context.close(); }
});
