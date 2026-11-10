// Temporary offline review of original archive articles; removed before final delivery.
import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const archive = path.resolve(root, process.env.REVIEW_ARCHIVE_PATH || '../review-archive-main');
const audit = JSON.parse(fs.readFileSync(path.join(root, '.review/verse-corpus-audit.json'), 'utf8'));
const rowsByArticle = new Map();
for (const row of audit.rows) {
  if (!rowsByArticle.has(row.id)) rowsByArticle.set(row.id, []);
  rowsByArticle.get(row.id).push(row);
}
const boundaries = audit.verse_or_poetry_articles_with_images_without_rows.filter(item => item.poetry_category);
const identities = [...new Set([...rowsByArticle.keys(), ...boundaries.map(item => item.id)])];
const originals = JSON.parse(execFileSync('python3', ['-c', `
import json, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from article_figures import arrange_article_figures, load_figure_rules, FigureElements
archive = Path(sys.argv[1])
rules = load_figure_rules('data/article-image-layouts.json')
result = []
for identity in json.load(sys.stdin):
    source = (archive / 'content/articles' / (identity + '.html')).read_text(encoding='utf-8')
    result.append({'id': identity, 'source': source,
                   'arranged': arrange_article_figures(source, rules),
                   'images': [node.attrs['src'] for node in FigureElements(source).elements if node.tag == 'img']})
json.dump(result, sys.stdout, ensure_ascii=False)
`, archive], { cwd: root, input: JSON.stringify(identities), encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 }));
const articles = new Map(originals.map(item => [item.id, item]));
const origin = 'http://127.0.0.1:8080';
const fontDirectory = path.resolve(root, process.env.REVIEW_FONT_DIR || '.review/fonts');
const resources = new Map([
  ['/verse-review/theme.css', { path: path.resolve(root, process.env.REVIEW_THEME_PATH || '.review/theme.css'), contentType: 'text/css' }],
  ['/verse-review/site.css', { path: path.join(root, 'assets/site.css'), contentType: 'text/css' }],
  ['/verse-review/figures.css', { path: path.join(root, 'assets/article-figures.css'), contentType: 'text/css' }],
  ['/assets/article-figures.js', { path: path.join(root, 'assets/article-figures.js'), contentType: 'text/javascript' }],
]);
for (const name of ['fonts.css', 'Raleway.woff2', 'Montserrat.woff2']) {
  resources.set(`/verse-review/fonts/${name}`, {
    path: path.join(fontDirectory, name), contentType: name.endsWith('.css') ? 'text/css' : 'font/woff2',
  });
}
for (const article of originals) for (const source of article.images) {
  const basename = source.slice('/images/articles/'.length);
  if (!source.startsWith('/images/articles/') || basename !== path.basename(basename) || /[\\?#]/.test(basename)) {
    throw new Error(`Unexpected archive image path: ${source}`);
  }
  const type = path.extname(basename).toLowerCase();
  const contentType = ({ '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml' })[type];
  if (!contentType) throw new Error(`Unrecognized original image type: ${source}`);
  resources.set(source, { path: path.join(archive, 'public/images/articles', basename), contentType });
}
for (const resource of resources.values()) fs.accessSync(resource.path);

// Habit is one of the seven small originals. Also retain one extreme portrait
// and all four BR-derived references/credits as visual evidence.
const screenshotImages = new Set(audit.rows.filter(row =>
  (!row.explicit_verse || (row.width < 240 && row.ratio <= 1.75)) ||
  row.id === '6c25be17-3343-451b-afeb-ed9c56942fd0').map(row => row.image));

async function routeOriginals(page, blocked) {
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin === origin && resources.has(url.pathname)) return route.fulfill(resources.get(url.pathname));
    const match = url.origin === origin && /^\/verse-review\/([0-9a-f-]+)\/$/.exec(url.pathname);
    const article = match && articles.get(match[1]);
    if (!article) {
      if (url.pathname !== '/favicon.ico') blocked.push(url.href);
      return route.abort('blockedbyclient');
    }
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="en" dir="ltr"><head>
      <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Original verse layout review — ${article.id}</title>
      <link rel="stylesheet" href="/verse-review/fonts/fonts.css">
      <link rel="stylesheet" href="/verse-review/theme.css">
      <link rel="stylesheet" href="/verse-review/site.css">
      <link rel="stylesheet" href="/verse-review/figures.css">
      <style>body{margin:16px}.prose{width:min(750px,calc(100vw - 32px));max-width:750px;margin-inline:auto}</style>
      <script type="module" src="/assets/article-figures.js"></script>
      </head><body><main class="prose">${article.arranged}</main></body></html>` });
  });
}

async function ready(page) {
  return page.evaluate(async () => {
    await Promise.all([...document.querySelectorAll('article img')].map(image => image.decode()));
    const faces = await Promise.all(['17px Raleway', '18px Raleway', 'italic 21px Raleway', '600 12px Raleway', '30px Montserrat']
      .map(font => document.fonts.load(font)));
    await document.fonts.ready;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return faces.map(font => font.length);
  });
}

async function measure(page, original) {
  return page.evaluate(({ source, arranged }) => {
    const article = document.querySelector('.prose article');
    const expected = new DOMParser().parseFromString(source, 'text/html').querySelector('article');
    const rendered = new DOMParser().parseFromString(arranged, 'text/html').querySelector('article');
    const rect = element => {
      const { left, right, top, bottom, width, height } = element.getBoundingClientRect();
      return { left, right, top, bottom, width, height };
    };
    const attrs = element => Object.fromEntries([...element.attributes].map(item => [item.name, item.value]));
    const imageAttrs = node => [...node.querySelectorAll('img')].map(attrs);
    const markup = (node, selector) => [...node.querySelectorAll(selector)].map(element => element.outerHTML);
    const wordBoxes = element => {
      const words = [];
      let segment = 0;
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode;
        if (node.nodeType === Node.ELEMENT_NODE) {
          if (['P', 'BR', 'LI', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6'].includes(node.tagName)) segment += 1;
          continue;
        }
        const size = parseFloat(getComputedStyle(node.parentElement).fontSize);
        for (const match of node.textContent.matchAll(/\S+/g)) {
          const range = document.createRange();
          range.setStart(node, match.index);
          range.setEnd(node, match.index + match[0].length);
          for (const box of range.getClientRects()) if (box.width && box.height) words.push({
            text: match[0], segment, fontSize: size,
            left: box.left, right: box.right, top: box.top, bottom: box.bottom,
          });
        }
      }
      return words;
    };
    const figures = [...article.querySelectorAll('figure')].map(figure => ({
      box: rect(figure), images: [...figure.querySelectorAll('img')].map(image => image.getAttribute('src')),
      standalone: figure.classList.contains('article-figure--standalone'),
      verse: Boolean(figure.closest('.article-verse-row')), float: getComputedStyle(figure).float,
    }));
    return {
      viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth,
      reader: rect(article.closest('.prose')), article: rect(article), figures,
      sourcePreserved: {
        text: article.textContent.replace(/\s+/g, ' ').trim() === expected.textContent.replace(/\s+/g, ' ').trim(),
        runtimeText: article.textContent === rendered.textContent,
        paragraphs: JSON.stringify(markup(article, 'p')) === JSON.stringify(markup(expected, 'p')),
        captions: JSON.stringify(markup(article, 'figcaption')) === JSON.stringify(markup(expected, 'figcaption')),
        imageAttributes: JSON.stringify(imageAttrs(article)) === JSON.stringify(imageAttrs(expected)),
        breaks: article.querySelectorAll('br').length === expected.querySelectorAll('br').length,
      },
      imageAttributes: imageAttrs(article), breaks: article.querySelectorAll('br').length,
      paired: [...article.querySelectorAll('.article-gallery--paired')].map(group =>
        [...group.querySelectorAll('img')].map(image => image.getAttribute('src').split('/').at(-1))),
      rows: [...article.querySelectorAll('.article-verse-row')].map(row => {
        const figure = row.querySelector(':scope > figure');
        const image = figure.querySelector('img');
        const text = row.querySelector(':scope > .article-verse-text');
        return {
          image: image.getAttribute('src').split('/').at(-1), naturalWidth: image.naturalWidth, naturalHeight: image.naturalHeight,
          row: rect(row), text: rect(text), figure: rect(figure), imageBox: rect(image), words: wordBoxes(text),
          textScrollWidth: text.scrollWidth, textClientWidth: text.clientWidth,
          aside: row.classList.contains('article-verse-row--aside'), display: getComputedStyle(row).display,
          float: getComputedStyle(figure).float, fontSize: parseFloat(getComputedStyle(row).fontSize),
          native: figure.classList.contains('article-figure--native-verse'),
          explicit: Boolean(text.closest('.poem,.lyrics') || text.querySelector('.poem,.lyrics')),
          sourceImageFirst: row.firstElementChild === figure,
          firstChild: row.firstElementChild.tagName, lastChild: row.lastElementChild.tagName,
        };
      }),
    };
  }, { source: original.source, arranged: original.arranged });
}

function inspect(result, expectedRows, boundary, mode, failures) {
  const check = (condition, message) => { if (!condition) failures.push(`${result.id} ${mode}: ${message}`); };
  const within = (inner, outer) => inner.left >= outer.left - 1 && inner.right <= outer.right + 1;
  const overlap = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 0.75 &&
    Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0.75;
  check(Object.values(result.sourcePreserved).every(Boolean), `source content changed: ${JSON.stringify(result.sourcePreserved)}`);
  check(result.scrollWidth <= result.viewport, `document overflow: ${result.scrollWidth}/${result.viewport}`);
  check(result.rows.length === expectedRows.length, `verse row count ${result.rows.length}/${expectedRows.length}`);
  check(Math.abs(result.reader.width - (mode === 'desktop' ? 750 : 358)) <= 1, 'unexpected reader column width');
  for (const [index, row] of result.rows.entries()) {
    const expected = expectedRows[index];
    if (!expected) continue;
    const label = `${row.image} row ${index + 1}`;
    check(row.image === expected.image && row.naturalWidth === expected.width && row.naturalHeight === expected.height,
      `${label}: original image/dimensions changed`);
    check(row.explicit === expected.explicit_verse && row.sourceImageFirst === expected.source_image_first,
      `${label}: verse classification or source reading order changed`);
    check(row.float === 'none', `${label}: verse illustration floated`);
    check(within(row.imageBox, result.reader) && within(row.figure, row.row), `${label}: image outside its reading column`);
    check(Math.abs(row.imageBox.width / row.imageBox.height - row.naturalWidth / row.naturalHeight) <= 0.01,
      `${label}: image aspect ratio changed`);
    check(row.textScrollWidth <= row.textClientWidth + 1, `${label}: text column overflow`);
    const outside = row.words.filter(word => !within(word, result.reader) || !within(word, row.text));
    check(!outside.length, `${label}: ${outside.length} out-of-column words; ${outside.slice(0, 3).map(word => word.text).join(' ')}`);
    const collisions = row.words.filter(word => result.figures.some(figure => overlap(word, figure.box)));
    check(!collisions.length, `${label}: ${collisions.length} words overlap a figure; ${collisions.slice(0, 3).map(word => word.text).join(' ')}`);
    if (row.aside) {
      const gap = row.figure.left - row.text.right;
      check(mode === 'desktop' && row.display === 'grid', `${label}: unexpected aside on phone/non-grid`);
      check(Math.abs(row.figure.top - row.text.top) <= 1 && Math.abs(row.imageBox.top - row.figure.top) <= 1,
        `${label}: artwork and verse are not top aligned`);
      check(gap >= 23.5 && gap <= 27.5 && Math.abs(gap - Math.max(24, row.fontSize * 1.5)) <= 1,
        `${label}: noncompact grid gap ${gap}`);
      const lastInk = Math.max(...row.words.map(word => word.right));
      check(row.figure.left - lastInk <= gap + row.fontSize + 2, `${label}: unused flexible space separates artwork from verse`);
      const segments = new Map();
      for (const word of row.words) {
        const previous = segments.get(word.segment) || { top: Infinity, bottom: -Infinity, fontSize: 0 };
        segments.set(word.segment, { top: Math.min(previous.top, word.top), bottom: Math.max(previous.bottom, word.bottom),
          fontSize: Math.max(previous.fontSize, word.fontSize) });
      }
      check([...segments.values()].every(line => line.bottom - line.top <= line.fontSize * 1.8),
        `${label}: an original printed line wrapped inside an aside`);
      check(row.imageBox.width <= (row.explicit ? 320 : 180) + 1 &&
        row.imageBox.height <= (row.explicit ? 600 : 300) + 1, `${label}: illustration exceeded its size limits`);
      check(row.imageBox.width <= row.naturalWidth * (row.explicit ? 2 : 1) + 1,
        `${label}: illustration exceeded allowed enlargement`);
      if (row.native) check(Math.abs(row.imageBox.width - row.naturalWidth) <= 1, `${label}: native-size image changed size`);
    } else {
      check(row.display === 'flow-root', `${label}: stacked row lost flow-root fallback`);
      check(row.figure.bottom <= row.text.top + 1 || row.text.bottom <= row.figure.top + 1,
        `${label}: stacked picture and text overlap`);
      check(row.imageBox.width <= row.naturalWidth + 1 && (row.native || row.imageBox.height <= 301),
        `${label}: stacked fallback enlarged the original artwork`);
    }
  }
  if (boundary) for (const name of boundary.rule.standalone || []) {
    const figure = result.figures.find(item => item.images.some(source => source.endsWith(`/${name}`)));
    check(Boolean(figure?.standalone && !figure.verse && figure.float === 'none'), `reviewed standalone boundary changed: ${name}`);
  }
  if (boundary) for (const pair of boundary.rule.paired || []) {
    check(result.paired.some(actual => JSON.stringify(actual) === JSON.stringify(pair)),
      `reviewed paired artwork changed: ${pair.join(', ')}`);
  }
}

async function screenshot(page, testInfo, id, mode, rowIndex, basename) {
  const figure = page.locator('.article-verse-row').nth(rowIndex).locator(':scope > figure');
  await figure.scrollIntoViewIfNeeded();
  const box = await figure.boundingBox();
  const reader = await page.locator('.prose').boundingBox();
  const viewport = page.viewportSize();
  const x = Math.max(0, reader.x - 12);
  const y = Math.max(0, box.y - 24);
  const output = testInfo.outputPath(`${mode}-${basename.replace(/\.[^.]+$/, '')}.png`);
  await page.screenshot({ path: output, animations: 'disabled', clip: {
    x, y, width: Math.min(viewport.width - x, reader.width + 24),
    height: Math.min(viewport.height - y, Math.max(box.height + 80, 650)),
  } });
  await testInfo.attach(`${mode}-${id}-row-${rowIndex + 1}`, { path: output, contentType: 'image/png' });
}

test('original verse corpus preserves lineation and uses bounded compact artwork at desktop and phone widths', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  expect(rowsByArticle.size).toBe(92);
  expect(audit.rows).toHaveLength(102);
  const measurements = [], failures = [], blocked = [], pageErrors = [];
  page.on('pageerror', error => pageErrors.push(`${page.url()}: ${error.message}`));
  await routeOriginals(page, blocked);
  try {
    for (const [mode, width] of [['desktop', 1440], ['phone', 390]]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const id of identities) {
        const original = articles.get(id);
        await page.goto(`${origin}/verse-review/${id}/`, { waitUntil: 'load' });
        const faces = await ready(page);
        if (faces.some(count => count !== 1)) failures.push(`${id} ${mode}: offline fonts did not load: ${faces}`);
        const result = { id, title: rowsByArticle.get(id)?.[0]?.title || boundaries.find(item => item.id === id)?.title,
          mode, ...(await measure(page, original)) };
        measurements.push(result);
        inspect(result, rowsByArticle.get(id) || [], boundaries.find(item => item.id === id), mode, failures);
        for (const [index, row] of result.rows.entries()) if (screenshotImages.has(row.image)) {
          await screenshot(page, testInfo, id, mode, index, row.image);
        }
      }
    }
    const habit = measurements.find(item => item.id === '76009211-1c2a-4f55-a4be-17d515e9cfcd' && item.mode === 'desktop').rows[0];
    expect(habit.aside, 'Habit must actively share the desktop row').toBe(true);
    expect(habit.imageBox.width).toBeCloseTo(240, 0);
    expect(habit.imageBox.height).toBeCloseTo(274, 0);
    expect(habit.figure.left - habit.text.right).toBeCloseTo(27, 0);
    expect(pageErrors, 'No runtime/resize errors').toEqual([]);
    expect(blocked, 'Every requested resource must be an offline original or reader asset').toEqual([]);
    expect(failures.length, failures.slice(0, 20).join('\n')).toBe(0);
  } finally {
    const output = testInfo.outputPath('verse-corpus-measurements.json');
    fs.writeFileSync(output, JSON.stringify({ archiveArticleCount: audit.articles_scanned,
      verseArticleCount: rowsByArticle.size, verseRowCount: audit.rows.length, boundaryArticleCount: boundaries.length,
      expectedScreenshots: screenshotImages.size * 2, blocked, pageErrors, failures, measurements }, null, 2));
    await testInfo.attach('verse-corpus-measurements', { path: output, contentType: 'application/json' });
  }
});
