import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

// This complete article fixture is the exact source from archive PR #188.
// Only the existing production transformer, registry, CSS and module arrange it.
const identity = '3ecef108-58f3-42fc-a9c1-be12086c3e87';
const source = fs.readFileSync('.review/water-wine-source.html', 'utf8');
const arranged = execFileSync('python3', ['-c', `
import sys
sys.path.insert(0, 'scripts')
from article_figures import arrange_article_figures, load_figure_rules
print(arrange_article_figures(sys.stdin.read(), load_figure_rules('data/article-image-layouts.json')))
`], { input: source, encoding: 'utf8' });
const css = ['.review/theme.css', 'assets/site.css', 'assets/article-figures.css']
  .map(file => fs.readFileSync(file, 'utf8')).join('\n');
const script = fs.readFileSync('assets/article-figures.js', 'utf8');
const files = new Map(fs.readdirSync('.review/images').map(name =>
  [`/images/articles/${name}`, { body: fs.readFileSync(path.join('.review/images', name)),
    contentType: name.endsWith('.png') ? 'image/png' : 'image/jpeg' }]));
for (const name of ['fonts.css', 'Raleway.woff2', 'Montserrat.woff2']) {
  files.set(`/review-fonts/${name}`, {
    body: fs.readFileSync(path.join('.review/fonts', name)),
    contentType: name.endsWith('.css') ? 'text/css' : 'font/woff2',
  });
}
const figure = (page, number) => page.locator(`figure:has(img[src$="-${number}.${number === 1 || number === 3 ? 'png' : 'jpg'}"])`);

async function mount(page, { width = 1440, fontSize } = {}) {
  await page.setViewportSize({ width, height: 1000 });
  await page.route('**/*', route => {
    const pathname = new URL(route.request().url()).pathname;
    if (files.has(pathname)) return route.fulfill(files.get(pathname));
    if (pathname === '/assets/article-figures.js') {
      return route.fulfill({ contentType: 'text/javascript', body: script });
    }
    if (pathname === '/water-wine-review/') {
      return route.fulfill({ contentType: 'text/html', body: `<!doctype html>
        <html lang="en" dir="ltr"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>God Changes Water into Wine — article review</title>
        <link rel="stylesheet" href="/review-fonts/fonts.css"><style>${css}</style>
        <script type="module" src="/assets/article-figures.js"></script></head>
        <body><main class="article-shell tcc-container">
          <header class="article-heading"><h1>God Changes Water into Wine</h1>
          <p class="article-subtitle">A Recipe for Usefulness</p>
          <p class="article-byline">by Daniel Kenaston</p></header>
          <div class="reading-layout"><aside class="reading-rail">September/October 2003<br>Source pages 12–17</aside>
          <div class="prose"${fontSize ? ` style="font-size:${fontSize}px"` : ''}>${arranged}</div></div>
        </main></body></html>` });
    }
    return route.abort('blockedbyclient');
  });
  await page.goto('http://127.0.0.1:8080/water-wine-review/');
  await expect.poll(() => page.locator('article img').evaluateAll(images =>
    images.map(image => [image.complete, image.naturalWidth, image.naturalHeight])))
    .toEqual([[true, 335, 241], [true, 324, 126], [true, 80, 95], [true, 307, 196], [true, 333, 220]]);
  const fonts = await page.evaluate(async () => {
    const results = await Promise.all(['18px Raleway', '600 18px Raleway', '64px Montserrat']
      .map(font => document.fonts.load(font)));
    await document.fonts.ready;
    return results.map(faces => faces.length);
  });
  expect(fonts, 'Use the real offline reader fonts, never a silent fallback').toEqual([1, 1, 1]);
}

async function measure(page) {
  return page.evaluate(source => {
    const article = document.querySelector('article');
    const reader = article.closest('.prose');
    const original = new DOMParser().parseFromString(source, 'text/html').querySelector('article');
    const rect = element => {
      const { left, right, top, bottom, width, height } = element.getBoundingClientRect();
      return { left, right, top, bottom, width, height };
    };
    const attrs = element => Object.fromEntries([...element.attributes].map(attr => [attr.name, attr.value]));
    const wordRects = element => {
      const words = [];
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode;
        for (const match of node.textContent.matchAll(/\S+/g)) {
          const range = document.createRange();
          range.setStart(node, match.index);
          range.setEnd(node, match.index + match[0].length);
          for (const box of range.getClientRects()) {
            if (box.width > 0 && box.height > 0) words.push({ text: match[0], left: box.left,
              right: box.right, top: box.top, bottom: box.bottom });
          }
        }
      }
      return words;
    };
    const figures = [...article.querySelectorAll('figure')];
    const targets = [1, 2, 3].map(index => {
      const figure = figures[index];
      const paragraph = figure.nextElementSibling;
      let boundary = paragraph.nextElementSibling;
      while (boundary && !/^H[1-6]$/.test(boundary.tagName)) boundary = boundary.nextElementSibling;
      return { number: index + 1, paragraph: rect(paragraph), words: wordRects(paragraph),
        previous: rect(figure.previousElementSibling), previousText: figure.previousElementSibling.textContent.trim(),
        paragraphText: paragraph.textContent, boundary: boundary ? rect(boundary) : null,
        marginBottom: parseFloat(getComputedStyle(figure).marginBottom) };
    });
    const dropcap = article.querySelector('.drop-cap');
    const firstLetter = document.createRange();
    firstLetter.setStart(dropcap.firstChild, 0);
    firstLetter.setEnd(dropcap.firstChild, 1);
    const dropcapRect = firstLetter.getBoundingClientRect();
    return {
      reader: rect(reader), viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth,
      font: getComputedStyle(reader).font, fontSize: parseFloat(getComputedStyle(reader).fontSize),
      figures: figures.map(figure => ({ box: rect(figure), image: rect(figure.querySelector('img')),
        float: getComputedStyle(figure).float, wrap: figure.classList.contains('article-figure--wrap'),
        src: figure.querySelector('img').getAttribute('src') })), targets,
      paragraphs: [...article.querySelectorAll('p')].map(node => node.outerHTML),
      expectedParagraphs: [...original.querySelectorAll('p')].map(node => node.outerHTML),
      imageAttributes: [...article.querySelectorAll('img')].map(attrs),
      expectedImageAttributes: [...original.querySelectorAll('img')].map(attrs),
      headings: [...article.querySelectorAll('h2')].map(node => node.outerHTML),
      expectedHeadings: [...original.querySelectorAll('h2')].map(node => node.outerHTML),
      galleryCount: article.querySelectorAll('.article-gallery').length,
      lastFigureIsLast: figures[4] === article.lastElementChild,
      firstFigureIsFirst: figures[0] === article.firstElementChild,
      dropcap: { left: dropcapRect.left, right: dropcapRect.right, top: dropcapRect.top, bottom: dropcapRect.bottom,
        font: getComputedStyle(dropcap, '::first-letter').font,
        float: getComputedStyle(dropcap, '::first-letter').float },
    };
  }, source);
}

const overlaps = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 0.5 &&
  Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0.5;

function expectPreserved(result) {
  expect(result.paragraphs).toEqual(result.expectedParagraphs);
  expect(result.headings).toEqual(result.expectedHeadings);
  expect(result.imageAttributes).toEqual(result.expectedImageAttributes);
  expect(result.figures).toHaveLength(5);
  expect(result.galleryCount).toBe(0);
  expect(result.firstFigureIsFirst).toBe(true);
  expect(result.lastFigureIsLast).toBe(true);
  expect(result.scrollWidth).toBeLessThanOrEqual(result.viewport);
  expect(result.font).toContain('Raleway');
  expect(result.dropcap.font).toContain('Montserrat');
  expect(result.targets[0].previousText).toContain('—The editor');
  expect(result.targets[0].paragraphText).toMatch(/^There are some New Testament/);
  expect(result.targets[1].previousText).toBe('We Must See Our Need');
  expect(result.targets[1].paragraphText).toMatch(/^We see a need expressed/);
  expect(result.targets[2].previousText).toBe('We Must Be Clean, Empty Vessels');
  expect(result.targets[2].paragraphText).toMatch(/^Not only were there willing people/);
  const naturalSizes = [[335, 241], [324, 126], [80, 95], [307, 196], [333, 220]];
  for (const [index, figure] of result.figures.entries()) {
    expect(figure.image.width).toBeLessThanOrEqual(naturalSizes[index][0] + 0.1);
    expect(figure.image.height / figure.image.width).toBeCloseTo(naturalSizes[index][1] / naturalSizes[index][0], 3);
    expect(figure.image.left).toBeGreaterThanOrEqual(result.reader.left - 0.5);
    expect(figure.image.right).toBeLessThanOrEqual(result.reader.right + 0.5);
  }
  for (const index of [0, 4]) {
    expect(result.figures[index].float).toBe('none');
    expect(Math.abs(result.figures[index].image.left + result.figures[index].image.right -
      result.reader.left - result.reader.right)).toBeLessThan(1);
  }
  for (const target of result.targets) {
    const image = result.figures[target.number - 1].image;
    expect(target.previous.bottom).toBeLessThanOrEqual(image.top + 0.5);
    expect(target.words.filter(word => overlaps(word, image)), `Image ${target.number} overlaps prose`).toEqual([]);
    expect(target.boundary.top + 0.5).toBeGreaterThanOrEqual(Math.max(image.bottom, target.paragraph.bottom));
    for (const word of target.words) {
      expect(word.left, word.text).toBeGreaterThanOrEqual(result.reader.left - 0.5);
      expect(word.right, word.text).toBeLessThanOrEqual(result.reader.right + 0.5);
    }
  }
  expect(result.targets[0].words.filter(word => word.text !== 'There' && overlaps(word, result.dropcap)),
    'The opening drop cap must not collide with its following text').toEqual([]);
}

async function expectWrapped(page) {
  for (const index of [2, 3, 4]) await expect(figure(page, index)).toHaveClass(/article-figure--wrap/);
  const result = await measure(page);
  expectPreserved(result);
  for (const target of result.targets) {
    const image = result.figures[target.number - 1].image;
    const alongside = target.words.filter(word => word.top < image.bottom && word.bottom > image.top);
    expect(alongside.length, `Image ${target.number} must actually have text beside it`).toBeGreaterThan(5);
    const below = target.words.filter(word => word.top >= image.bottom + target.marginBottom - 0.5);
    expect(below.length, `Image ${target.number} must release the column below it`).toBeGreaterThan(0);
    if (target.number === 3) {
      expect(Math.abs(image.left - result.reader.left)).toBeLessThan(0.5);
      expect(Math.min(...below.map(word => word.left))).toBeLessThan(image.right - result.fontSize);
    } else {
      expect(Math.abs(image.right - result.reader.right)).toBeLessThan(0.5);
      expect(Math.max(...below.map(word => word.right))).toBeGreaterThan(image.left + result.fontSize);
    }
  }
  expect(result.figures[2].image.width).toBeCloseTo(80, 1);
  expect(result.figures[2].image.height).toBeCloseTo(95, 1);
  expect(result.dropcap.float).not.toBe('none');
  return result;
}

async function expectStacked(page, { print = false } = {}) {
  if (!print) for (const index of [2, 3, 4]) await expect(figure(page, index)).not.toHaveClass(/article-figure--wrap/);
  const result = await measure(page);
  expectPreserved(result);
  for (const target of result.targets) {
    const figure = result.figures[target.number - 1];
    expect(figure.float).toBe('none');
    expect(target.paragraph.top + 0.5).toBeGreaterThanOrEqual(figure.image.bottom);
    expect(target.words[0].top + 0.5).toBeGreaterThanOrEqual(figure.image.bottom);
  }
  return result;
}

async function evidence(page, testInfo, name, sections = ['opening', 'need', 'pots']) {
  await testInfo.attach(`${name}-geometry`, { body: JSON.stringify(await measure(page), null, 2), contentType: 'application/json' });
  for (const section of sections) {
    const clip = await page.evaluate(section => {
      const article = document.querySelector('article');
      const headings = [...article.querySelectorAll('h2')];
      const heading = text => headings.find(node => node.textContent === text);
      const first = section === 'opening' ? article.firstElementChild :
        heading(section === 'need' ? 'We Must See Our Need' : 'We Must Be Clean, Empty Vessels');
      const last = section === 'opening' ? heading('John 2:1-11') :
        heading(section === 'need' ? 'We Must Be Willing to Obey' : 'We Must Be “Obedient-to-the-Brim” Servants');
      const reader = article.getBoundingClientRect();
      const top = Math.max(0, first.getBoundingClientRect().top + scrollY - 16);
      return { x: Math.max(0, reader.left - 16), y: top,
        width: Math.min(innerWidth, reader.width + 32),
        height: last.getBoundingClientRect().bottom + scrollY + 16 - top };
    }, section);
    const file = testInfo.outputPath(`${name}-${section}.png`);
    await page.screenshot({ path: file, fullPage: true, clip, animations: 'disabled' });
    await testInfo.attach(`${name}-${section}`, { path: file, contentType: 'image/png' });
  }
}

for (const width of [1440, 768]) {
  test(`early illustrations wrap neatly at ${width}px`, async ({ page }, testInfo) => {
    await mount(page, { width });
    await expectWrapped(page);
    await evidence(page, testInfo, `desktop-${width}`);
  });
}

test('mobile keeps the original images and full-width paragraphs', async ({ page }, testInfo) => {
  await mount(page, { width: 390 });
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    await expectStacked(page);
    await evidence(page, testInfo, `mobile-${width}`);
  }
});

test('large reading fonts keep images above their paragraphs', async ({ browser }, testInfo) => {
  for (const fontSize of [24, 28]) {
    const context = await browser.newContext();
    try {
      const page = await context.newPage();
      await mount(page, { fontSize });
      await expectStacked(page);
      await evidence(page, testInfo, `font-${fontSize}`, ['opening']);
    } finally { await context.close(); }
  }
});

test('no-JavaScript and print preserve the stacked reading order', async ({ browser, page }, testInfo) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const noScript = await context.newPage();
    await mount(noScript);
    await expectStacked(noScript);
    await evidence(noScript, testInfo, 'no-javascript', ['opening']);
  } finally { await context.close(); }
  await mount(page);
  await expectWrapped(page);
  await page.emulateMedia({ media: 'print' });
  await expectStacked(page, { print: true });
  await evidence(page, testInfo, 'print', ['opening']);
});
