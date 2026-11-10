// Temporary review of website arrangements from the pristine source archive.
import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const archive = path.resolve(process.env.REVIEW_ARCHIVE_PATH || '../review-archive-main');
const definitions = [
  { key: 'rees-howells', identity: 'dd3379b6-7f59-4c94-baee-65374d62a955',
    dimensions: [[143, 203], [188, 107], [144, 217]], targets: [
      { number: 2, width: 188, side: 'end', prefix: 'Toward the close of the book' },
      { number: 3, width: 144, side: 'start', prefix: 'This book does not only' },
    ] },
  { key: 'godly-home', identity: '4f76f07b-0e77-457d-b59c-12e67222dfc1',
    dimensions: [[320, 205]], standalone: true,
    targets: [{ number: 1, prefix: 'This tape set should be available' }] },
  { key: 'chinese-church', identity: 'f8e9bf03-6695-4bca-90e5-2582673cca69',
    dimensions: [[215, 201], [216, 161], [153, 216], [216, 148], [216, 142]],
    targets: [{ number: 1, width: 215, side: 'start', prefix: 'These verses beautifully describe' }] },
  { key: 'treasure', identity: 'b719fea9-7d48-4b08-ae08-025146d69f31',
    dimensions: [[447, 322], [226, 288]], targets: [
      { number: 1, width: 447, side: 'start', prefix: 'Greetings to all of you' },
      { number: 2, width: 226, side: 'end', prefix: 'Dear ones, once again' },
    ] },
];
const css = ['.review/theme.css', 'assets/site.css', 'assets/article-figures.css']
  .map(file => fs.readFileSync(file, 'utf8')).join('\n');
const script = fs.readFileSync('assets/article-figures.js', 'utf8');
const fonts = new Map(['fonts.css', 'Raleway.woff2', 'Montserrat.woff2'].map(name => [
  `/additional-fonts/${name}`, { body: fs.readFileSync(path.join('.review/fonts', name)),
    contentType: name.endsWith('.css') ? 'text/css' : 'font/woff2' },
]));

function fixture(definition) {
  const source = fs.readFileSync(path.join(archive, 'content/articles', `${definition.identity}.html`), 'utf8');
  const images = new Map();
  for (const match of source.matchAll(/<img\b[^>]*\bsrc="(\/images\/articles\/[^"/]+)"/g)) {
    const imagePath = match[1];
    images.set(imagePath, { body: fs.readFileSync(path.join(archive, 'public', imagePath)),
      contentType: imagePath.endsWith('.png') ? 'image/png' : 'image/jpeg' });
  }
  const arranged = execFileSync('python3', ['-c', `
import sys
sys.path.insert(0, 'scripts')
from article_figures import arrange_article_figures, load_figure_rules
print(arrange_article_figures(sys.stdin.read(), load_figure_rules('data/article-image-layouts.json')))
`], { input: source, encoding: 'utf8' });
  return { ...definition, source, arranged, images };
}

async function mount(page, article, width) {
  await page.setViewportSize({ width, height: 1000 });
  await page.unrouteAll({ behavior: 'wait' });
  const fixturePath = `/additional-layout/${article.key}/`;
  await page.route('**/*', route => {
    const pathname = new URL(route.request().url()).pathname;
    if (article.images.has(pathname)) return route.fulfill(article.images.get(pathname));
    if (fonts.has(pathname)) return route.fulfill(fonts.get(pathname));
    if (pathname === '/assets/article-figures.js') return route.fulfill({ contentType: 'text/javascript', body: script });
    if (pathname !== fixturePath) return route.abort('blockedbyclient');
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="en"><head>
      <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
      <title>${article.key} — original article review</title>
      <link rel="stylesheet" href="/additional-fonts/fonts.css">
      <style>${css}\nbody{margin:16px}.prose{max-width:750px;margin-inline:auto}</style>
      <script type="module" src="/assets/article-figures.js"></script></head>
      <body><main class="prose">${article.arranged}</main></body></html>` });
  });
  await page.goto(`http://127.0.0.1:8080${fixturePath}`);
  await expect.poll(() => page.locator('article img').evaluateAll(images => images.map(image =>
    [image.complete, image.naturalWidth, image.naturalHeight])))
    .toEqual(article.dimensions.map(size => [true, ...size]));
  const loaded = await page.evaluate(async () => {
    const fonts = await Promise.all(['18px Raleway', '600 12px Raleway', '64px Montserrat']
      .map(font => document.fonts.load(font)));
    await document.fonts.ready;
    return fonts.map(font => font.length);
  });
  expect(loaded).toEqual([1, 1, 1]);
  const figures = page.locator('article figure');
  for (const figure of await figures.all()) {
    if (width >= 768 && !article.standalone) await expect(figure).toHaveClass(/article-figure--wrap/);
    else await expect(figure).not.toHaveClass(/article-figure--wrap/);
  }
}

async function measure(page, article) {
  return page.evaluate(({ source, targets }) => {
    const current = document.querySelector('article');
    const original = new DOMParser().parseFromString(source, 'text/html').querySelector('article');
    const rect = element => {
      const { left, right, top, bottom, width, height } = element.getBoundingClientRect();
      return { left, right, top, bottom, width, height };
    };
    const words = element => {
      const boxes = [];
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) for (const match of walker.currentNode.textContent.matchAll(/\S+/g)) {
        const range = document.createRange();
        range.setStart(walker.currentNode, match.index);
        range.setEnd(walker.currentNode, match.index + match[0].length);
        for (const box of range.getClientRects()) if (box.width && box.height) boxes.push({
          text: match[0], left: box.left, right: box.right, top: box.top, bottom: box.bottom, height: box.height,
        });
      }
      return boxes;
    };
    const images = root => [...root.querySelectorAll('img')].map(image =>
      Object.fromEntries([...image.attributes].map(attr => [attr.name, attr.value])));
    const signature = root => [...root.querySelectorAll('p,blockquote,ol,ul,h1,h2,h3,h4,h5,h6')]
      .map(node => [node.tagName, node.outerHTML]);
    const proseText = root => {
      const copy = root.cloneNode(true);
      for (const figure of copy.querySelectorAll('figure')) figure.remove();
      return copy.textContent.replace(/\s+/g, ' ').trim();
    };
    const figures = [...current.querySelectorAll('figure')];
    const list = current.querySelector('ol');
    const epigraph = current.querySelector('blockquote');
    const paragraphs = [...current.children].filter(node => node.tagName === 'P');
    return { reader: rect(current.closest('.prose')), viewport: innerWidth,
      scrollWidth: document.documentElement.scrollWidth, fontSize: parseFloat(getComputedStyle(current).fontSize),
      signature: signature(current), expectedSignature: signature(original), images: images(current), expectedImages: images(original),
      text: proseText(current), expectedText: proseText(original),
      figureContents: figures.map(figure => figure.innerHTML),
      expectedFigureContents: [...original.querySelectorAll('figure')].map(figure => figure.innerHTML),
      galleryCount: current.querySelectorAll('.article-gallery').length,
      figures: figures.map(figure => {
        const image = figure.querySelector('img');
        const caption = figure.querySelector('figcaption');
        return { figure: rect(figure), image: rect(image), natural: [image.naturalWidth, image.naturalHeight],
          caption: caption ? rect(caption) : null, captionWords: caption ? words(caption) : [],
          float: getComputedStyle(figure).float };
      }),
      targets: targets.map(({ number }) => {
        const figure = figures[number - 1];
        const paragraph = figure.nextElementSibling;
        return { number, paragraph: rect(paragraph), paragraphText: paragraph.textContent,
          paragraphIndex: paragraphs.indexOf(paragraph), words: words(paragraph),
          previousTag: figure.previousElementSibling?.tagName ?? null,
          previous: figure.previousElementSibling ? rect(figure.previousElementSibling) : null };
      }),
      epigraph: epigraph ? { box: rect(epigraph), paragraphs: epigraph.querySelectorAll('p').length,
        breaks: epigraph.querySelectorAll('br').length } : null,
      list: list ? { box: rect(list), style: getComputedStyle(list).listStyleType,
        markerPosition: getComputedStyle(list).listStylePosition,
        items: [...list.children].map(item => ({ ...rect(item), text: item.textContent, words: words(item) })) } : null,
    };
  }, { source: article.source, targets: article.targets });
}

function expectFidelity(result, article) {
  expect(result.signature).toEqual(result.expectedSignature);
  expect(result.images).toEqual(result.expectedImages);
  expect(result.figureContents).toEqual(result.expectedFigureContents);
  expect(result.text).toBe(result.expectedText);
  expect(result.galleryCount).toBe(0);
  expect(result.figures).toHaveLength(article.dimensions.length);
  expect(result.scrollWidth).toBeLessThanOrEqual(result.viewport);
  for (const item of result.figures) {
    expect(item.image.width).toBeLessThanOrEqual(item.natural[0] + 0.1);
    expect(item.image.height / item.image.width).toBeCloseTo(item.natural[1] / item.natural[0], 3);
    expect(item.figure.left).toBeGreaterThanOrEqual(result.reader.left - 0.5);
    expect(item.figure.right).toBeLessThanOrEqual(result.reader.right + 0.5);
    if (item.caption) {
      expect(item.caption.top + 0.5).toBeGreaterThanOrEqual(item.image.bottom);
      expect(item.caption.bottom).toBeLessThanOrEqual(item.figure.bottom + 0.5);
      for (const word of item.captionWords) {
        expect(word.left).toBeGreaterThanOrEqual(item.caption.left - 0.5);
        expect(word.right).toBeLessThanOrEqual(item.caption.right + 0.5);
      }
    }
  }
  for (const [index, target] of result.targets.entries()) {
    expect(target.paragraphText.startsWith(article.targets[index].prefix)).toBe(true);
    for (const word of target.words) {
      expect(word.left, word.text).toBeGreaterThanOrEqual(result.reader.left - 0.5);
      expect(word.right, word.text).toBeLessThanOrEqual(result.reader.right + 0.5);
      for (const item of result.figures) {
        const x = Math.min(word.right, item.figure.right) - Math.max(word.left, item.figure.left);
        const y = Math.min(word.bottom, item.figure.bottom) - Math.max(word.top, item.figure.top);
        expect(x > 0.5 && y > 0.5, `${word.text} overlaps an image or caption`).toBe(false);
      }
    }
  }
}

function expectPlacement(result, article, width) {
  expectFidelity(result, article);
  for (const [index, target] of result.targets.entries()) {
    const item = result.figures[target.number - 1];
    const settings = article.targets[index];
    if (width >= 768 && !article.standalone) {
      expect(item.image.width).toBeCloseTo(settings.width, 1);
      expect(item.float).toBe(`inline-${settings.side}`);
      expect(settings.side === 'start' ? item.figure.left : item.figure.right)
        .toBeCloseTo(settings.side === 'start' ? result.reader.left : result.reader.right, 1);
      // The Chinese introduction retains its drop cap. Measure its ordinary
      // text separately for top alignment while checking every glyph for overlap.
      const firstBodyWord = target.words.find(word => word.height < result.fontSize * 2);
      expect(Math.abs(firstBodyWord.top - item.image.top)).toBeLessThan(result.fontSize * 1.5);
      const beside = target.words.filter(word => word.top < item.image.bottom && word.bottom > item.image.top);
      expect(beside.length).toBeGreaterThan(5);
      for (const word of beside) {
        if (settings.side === 'start') expect(word.left).toBeGreaterThanOrEqual(item.figure.right + 24 - 0.5);
        else expect(word.right).toBeLessThanOrEqual(item.figure.left - 24 + 0.5);
      }
    } else {
      expect(item.float).toBe('none');
      expect(target.paragraph.top + 0.5).toBeGreaterThanOrEqual(item.figure.bottom);
      expect(Math.abs(item.image.left + item.image.right - result.reader.left - result.reader.right)).toBeLessThan(1);
    }
  }
  if (article.key === 'godly-home') {
    const [photo] = result.figures;
    expect(photo.caption).not.toBeNull();
    expect(result.list.items).toHaveLength(30);
    expect(result.list.style).toBe('decimal');
    expect(result.list.markerPosition).toBe('outside');
    expect(result.list.box.top + 0.5).toBeGreaterThanOrEqual(result.targets[0].paragraph.bottom);
    expect(result.list.box.width).toBeCloseTo(result.reader.width, 1);
    for (const item of result.list.items) {
      expect(item.width).toBeGreaterThanOrEqual(result.reader.width - 60);
      for (const word of item.words) expect(word.right).toBeLessThanOrEqual(result.reader.right + 0.5);
    }
  }
  if (article.key === 'chinese-church') {
    expect(result.epigraph.paragraphs).toBe(2);
    expect(result.epigraph.breaks).toBe(4);
    expect(result.targets[0].previousTag).toBe('BLOCKQUOTE');
    expect(result.epigraph.box.bottom).toBeLessThanOrEqual(result.figures[0].figure.top + 0.5);
    expect(result.targets[0].paragraphIndex).toBe(0);
  }
  if (article.key === 'treasure') {
    expect(result.targets.map(target => target.paragraphIndex)).toEqual([0, 2]);
  }
}

async function evidence(page, testInfo, article, result, width) {
  const name = `${article.key}-${width}`;
  const jsonPath = testInfo.outputPath(`${name}.json`);
  fs.writeFileSync(jsonPath, JSON.stringify(result, null, 2));
  await testInfo.attach(`${name}-geometry`, { path: jsonPath, contentType: 'application/json' });
  for (const target of result.targets) {
    const item = result.figures[target.number - 1];
    const contextTop = article.key === 'chinese-church' ? result.epigraph.box.top : item.figure.top;
    const top = Math.max(0, contextTop - 16);
    const bottom = article.key === 'godly-home' ? result.list.items[4].bottom
      : Math.max(item.figure.bottom, Math.min(target.paragraph.bottom, item.figure.bottom + 160));
    const imagePath = testInfo.outputPath(`${name}-image-${target.number}.png`);
    await page.screenshot({ path: imagePath, fullPage: true, animations: 'disabled', clip: {
      x: Math.max(0, result.reader.left - 16), y: top,
      width: Math.min(result.viewport, result.reader.width + 32), height: bottom + 16 - top,
    } });
    await testInfo.attach(`${name}-image-${target.number}`, { path: imagePath, contentType: 'image/png' });
  }
}

for (const definition of definitions) {
  test(`${definition.key} preserves its source and image layout on desktop and phones`, async ({ page }, testInfo) => {
    const article = fixture(definition);
    for (const width of [1440, 390, 320]) {
      await mount(page, article, width);
      const result = await measure(page, article);
      expectPlacement(result, article, width);
      if (width !== 320) await evidence(page, testInfo, article, result, width);
    }
  });
}
