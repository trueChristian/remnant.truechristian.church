// Temporary original-article placement review; removed before final delivery.
import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const identity = 'ba78ab40-e1d1-4b82-9b71-194439cd6f86';
const source = fs.readFileSync('.review/tragedy-source.html', 'utf8');
const arranged = execFileSync('python3', ['-c', `
import sys
sys.path.insert(0, 'scripts')
from article_figures import arrange_article_figures, load_figure_rules
print(arrange_article_figures(sys.stdin.read(), load_figure_rules('data/article-image-layouts.json')))
`], { input: source, encoding: 'utf8' });
const css = ['.review/theme.css', 'assets/site.css', 'assets/article-figures.css']
  .map(file => fs.readFileSync(file, 'utf8')).join('\n');
const script = fs.readFileSync('assets/article-figures.js', 'utf8');
const resources = new Map([
  [`/images/articles/${identity}-1.jpg`, { contentType: 'image/jpeg', body: fs.readFileSync('.review/tragedy-boy.jpg') }],
  [`/images/articles/${identity}-2.jpg`, { contentType: 'image/jpeg', body: fs.readFileSync('.review/tragedy-family.jpg') }],
]);
for (const name of ['fonts.css', 'Raleway.woff2', 'Montserrat.woff2']) {
  resources.set(`/tragedy-fonts/${name}`, { body: fs.readFileSync(path.join('.review/fonts', name)),
    contentType: name.endsWith('.css') ? 'text/css' : 'font/woff2' });
}

async function mount(page, { width = 1440, fontSize } = {}) {
  await page.setViewportSize({ width, height: 1000 });
  await page.route('**/*', route => {
    const pathname = new URL(route.request().url()).pathname;
    if (resources.has(pathname)) return route.fulfill(resources.get(pathname));
    if (pathname === '/assets/article-figures.js') return route.fulfill({ contentType: 'text/javascript', body: script });
    if (pathname !== '/tragedy-review/') return route.abort('blockedbyclient');
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="en"><head>
      <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Tragedy — article layout review</title><link rel="stylesheet" href="/tragedy-fonts/fonts.css">
      <style>${css}\nbody{margin:16px}.prose{max-width:750px;margin-inline:auto${fontSize ? `;font-size:${fontSize}px` : ''}}</style>
      <script type="module" src="/assets/article-figures.js"></script></head>
      <body><main class="prose">${arranged}</main></body></html>` });
  });
  await page.goto('http://127.0.0.1:8080/tragedy-review/');
  await expect.poll(() => page.locator('article img').evaluateAll(images => images.map(image =>
    [image.complete, image.naturalWidth, image.naturalHeight])))
    .toEqual([[true, 276, 378], [true, 151, 224]]);
  const fonts = await page.evaluate(async () => {
    const loaded = await Promise.all(['18px Raleway', '600 12px Raleway']
      .map(font => document.fonts.load(font)));
    await document.fonts.ready;
    return loaded.map(faces => faces.length);
  });
  expect(fonts).toEqual([1, 1]);
}

async function measure(page) {
  return page.evaluate(source => {
    const article = document.querySelector('article');
    const expected = new DOMParser().parseFromString(source, 'text/html').querySelector('article');
    const rect = element => {
      const { left, right, top, bottom, width, height } = element.getBoundingClientRect();
      return { left, right, top, bottom, width, height };
    };
    const words = element => {
      const result = [];
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        for (const match of walker.currentNode.textContent.matchAll(/\S+/g)) {
          const range = document.createRange();
          range.setStart(walker.currentNode, match.index);
          range.setEnd(walker.currentNode, match.index + match[0].length);
          for (const box of range.getClientRects()) if (box.width && box.height) result.push({
            text: match[0], left: box.left, right: box.right, top: box.top, bottom: box.bottom,
          });
        }
      }
      return result;
    };
    const figureSource = figure => ({
      src: figure.querySelector('img').getAttribute('src'), html: figure.innerHTML,
      attributes: Object.fromEntries([...figure.querySelector('img').attributes].map(attr => [attr.name, attr.value])),
      caption: figure.querySelector('figcaption').outerHTML,
    });
    const figures = [...article.querySelectorAll('figure')];
    return {
      reader: rect(article.closest('.prose')), viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth,
      fontSize: parseFloat(getComputedStyle(article).fontSize), galleryCount: article.querySelectorAll('.article-gallery').length,
      sourceFigures: figures.map(figureSource), originalFigures: [...expected.querySelectorAll('figure')].map(figureSource),
      paragraphs: [...article.querySelectorAll('p')].map(node => node.outerHTML),
      originalParagraphs: [...expected.querySelectorAll('p')].map(node => node.outerHTML),
      figures: figures.map(figure => {
        const paragraph = figure.nextElementSibling;
        return {
          figure: rect(figure), image: rect(figure.querySelector('img')), caption: rect(figure.querySelector('figcaption')),
          captionWords: words(figure.querySelector('figcaption')), float: getComputedStyle(figure).float,
          paragraph: rect(paragraph), paragraphText: paragraph.textContent, paragraphWords: words(paragraph),
          previous: rect(figure.previousElementSibling), following: rect(paragraph.nextElementSibling),
        };
      }),
    };
  }, source);
}

function expectPreserved(result) {
  expect(result.galleryCount).toBe(0);
  expect(result.figures).toHaveLength(2);
  // The source archive remains boy, family. Only the reviewed reader order changes.
  expect(result.sourceFigures).toEqual([result.originalFigures[1], result.originalFigures[0]]);
  expect(result.paragraphs).toEqual(result.originalParagraphs);
  expect(result.figures[0].paragraphText).toMatch(/^Loved ones came to the hospitals/);
  expect(result.figures[1].paragraphText).toMatch(/^Warren was hospitalized/);
  expect(result.scrollWidth).toBeLessThanOrEqual(result.viewport);
  expect(result.figures[1].figure.top + 0.5).toBeGreaterThanOrEqual(
    Math.max(result.figures[0].figure.bottom, result.figures[0].paragraph.bottom));
  for (const [index, item] of result.figures.entries()) {
    const [width, height] = index === 0 ? [276, 378] : [151, 224];
    expect(item.image.width).toBeLessThanOrEqual(width + 0.1);
    expect(item.image.height / item.image.width).toBeCloseTo(height / width, 3);
    expect(item.figure.left).toBeGreaterThanOrEqual(result.reader.left - 0.5);
    expect(item.figure.right).toBeLessThanOrEqual(result.reader.right + 0.5);
    expect(item.caption.top + 0.5).toBeGreaterThanOrEqual(item.image.bottom);
    expect(item.caption.bottom).toBeLessThanOrEqual(item.figure.bottom + 0.5);
    expect(item.previous.bottom).toBeLessThanOrEqual(item.figure.top + 0.5);
    for (const word of item.captionWords) {
      expect(word.left, `Caption: ${word.text}`).toBeGreaterThanOrEqual(item.caption.left - 0.5);
      expect(word.right, `Caption: ${word.text}`).toBeLessThanOrEqual(item.caption.right + 0.5);
      expect(word.bottom, `Caption: ${word.text}`).toBeLessThanOrEqual(item.figure.bottom + 0.5);
    }
    for (const word of item.paragraphWords) {
      expect(word.left, word.text).toBeGreaterThanOrEqual(result.reader.left - 0.5);
      expect(word.right, word.text).toBeLessThanOrEqual(result.reader.right + 0.5);
      for (const other of result.figures) {
        const overlapX = Math.min(word.right, other.figure.right) - Math.max(word.left, other.figure.left);
        const overlapY = Math.min(word.bottom, other.figure.bottom) - Math.max(word.top, other.figure.top);
        expect(overlapX > 0.5 && overlapY > 0.5, `${word.text} overlaps image or caption`).toBe(false);
      }
    }
  }
  const boy = result.figures[1];
  expect(boy.following.top + 0.5).toBeGreaterThanOrEqual(Math.max(boy.figure.bottom, boy.paragraph.bottom));
}

async function expectWrapped(page) {
  for (const figure of await page.locator('article figure').all()) await expect(figure).toHaveClass(/article-figure--wrap/);
  const result = await measure(page);
  expectPreserved(result);
  const [family, boy] = result.figures;
  expect(family.image.width).toBeCloseTo(276, 1);
  expect(boy.image.width).toBeCloseTo(151, 1);
  expect(family.figure.right).toBeCloseTo(result.reader.right, 1);
  expect(boy.figure.left).toBeCloseTo(result.reader.left, 1);
  for (const [index, item] of result.figures.entries()) {
    expect(Math.abs(item.paragraphWords[0].top - item.image.top),
      'The paired paragraph must begin beside its own photograph').toBeLessThan(result.fontSize * 1.5);
    const beside = item.paragraphWords.filter(word => word.top < item.image.bottom && word.bottom > item.image.top);
    expect(beside.length, 'The paired paragraph must actually share the photo row').toBeGreaterThan(5);
    for (const word of beside) {
      if (index === 0) expect(word.right).toBeLessThanOrEqual(item.figure.left - 24 + 0.5);
      else expect(word.left).toBeGreaterThanOrEqual(item.figure.right + 24 - 0.5);
    }
  }
  return result;
}

async function expectStacked(page, { print = false } = {}) {
  if (!print) for (const figure of await page.locator('article figure').all()) await expect(figure).not.toHaveClass(/article-figure--wrap/);
  const result = await measure(page);
  expectPreserved(result);
  for (const item of result.figures) {
    expect(item.float).toBe('none');
    expect(item.paragraph.top + 0.5).toBeGreaterThanOrEqual(item.figure.bottom);
    expect(Math.abs(item.image.left + item.image.right - result.reader.left - result.reader.right)).toBeLessThan(1);
  }
  return result;
}

async function evidence(page, testInfo, name) {
  const result = await measure(page);
  const geometryPath = testInfo.outputPath(`${name}.json`);
  fs.writeFileSync(geometryPath, JSON.stringify(result, null, 2));
  await testInfo.attach(`${name}-geometry`, { path: geometryPath, contentType: 'application/json' });
  const offset = await page.evaluate(() => ({ x: scrollX, y: scrollY }));
  for (const [index, item] of result.figures.entries()) {
    const top = Math.max(0, Math.min(item.figure.top, item.paragraph.top) + offset.y - 16);
    const imagePath = testInfo.outputPath(`${name}-${index === 0 ? 'family' : 'boy'}.png`);
    await page.screenshot({ path: imagePath, fullPage: true, animations: 'disabled', clip: {
      x: Math.max(0, result.reader.left + offset.x - 16), y: top,
      width: Math.min(result.viewport, result.reader.width + 32),
      height: Math.max(item.figure.bottom, item.paragraph.bottom) + offset.y + 16 - top,
    } });
    await testInfo.attach(`${name}-${index === 0 ? 'family' : 'boy'}`, { path: imagePath, contentType: 'image/png' });
  }
}

test('Tragedy pairs the family right and boy left with intact captions', async ({ page }, testInfo) => {
  await mount(page);
  await expectWrapped(page);
  await evidence(page, testInfo, 'tragedy-desktop');
});

test('Tragedy stacks each complete photograph and caption on phones', async ({ page }, testInfo) => {
  await mount(page, { width: 390 });
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    await expectStacked(page);
    await evidence(page, testInfo, `tragedy-mobile-${width}`);
  }
});

test('Tragedy keeps safe large-text, print and no-JavaScript layouts', async ({ browser, page }, testInfo) => {
  await mount(page, { fontSize: 24 });
  await expectStacked(page);
  await evidence(page, testInfo, 'tragedy-large-type');
  // The large font lives in the fixture stylesheet, so an inline reset must override it.
  await page.locator('.prose').evaluate(reader => reader.style.fontSize = '18px');
  await expectWrapped(page);
  await page.emulateMedia({ media: 'print' });
  await expectStacked(page, { print: true });
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const noScript = await context.newPage();
    await mount(noScript);
    await expectStacked(noScript);
  } finally { await context.close(); }
});
