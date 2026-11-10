// Temporary offline corpus audit; original content/assets come from a pristine archive checkout.
import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const archive = path.resolve(root, process.env.REVIEW_ARCHIVE_PATH || '../review-archive-main');
const originals = JSON.parse(execFileSync('python3', ['-c', `
import json, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from article_figures import arrange_article_figures, load_figure_rules, FigureElements
archive = Path(sys.argv[1])
rules = load_figure_rules('data/article-image-layouts.json')
result = []
for record in json.loads((archive / 'index.json').read_text(encoding='utf-8'))['articles']:
    if not record['images']:
        continue
    source = (archive / record['html']['repository_path']).read_text(encoding='utf-8')
    result.append({'id': record['id'], 'title': record['title'], 'source': source,
                   'arranged': arrange_article_figures(source, rules),
                   'images': [node.attrs['src'] for node in FigureElements(source).elements if node.tag == 'img']})
json.dump(result, sys.stdout, ensure_ascii=False)
`, archive], { cwd: root, encoding: 'utf8', maxBuffer: 96 * 1024 * 1024 }));
const articles = new Map(originals.map(item => [item.id, item]));
const origin = 'http://127.0.0.1:8080';
const fontDirectory = path.resolve(root, process.env.REVIEW_FONT_DIR || '.review/fonts');
const resources = new Map([
  ['/prose-review/theme.css', { path: path.resolve(root, process.env.REVIEW_THEME_PATH || '.review/theme.css'), contentType: 'text/css' }],
  ['/prose-review/site.css', { path: path.join(root, 'assets/site.css'), contentType: 'text/css' }],
  ['/prose-review/figures.css', { path: path.join(root, 'assets/article-figures.css'), contentType: 'text/css' }],
  ['/assets/article-figures.js', { path: path.join(root, 'assets/article-figures.js'), contentType: 'text/javascript' }],
]);
for (const name of ['fonts.css', 'Raleway.woff2', 'Montserrat.woff2']) {
  resources.set(`/prose-review/fonts/${name}`, {
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

async function routeOriginals(page, blocked) {
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin === origin && resources.has(url.pathname)) return route.fulfill(resources.get(url.pathname));
    const match = url.origin === origin && /^\/prose-review\/([0-9a-f-]+)\/$/.exec(url.pathname);
    const article = match && articles.get(match[1]);
    if (!article) {
      if (url.pathname !== '/favicon.ico') blocked.push(url.href);
      return route.abort('blockedbyclient');
    }
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="en" dir="ltr"><head>
      <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Original prose layout review — ${article.id}</title>
      <link rel="stylesheet" href="/prose-review/fonts/fonts.css">
      <link rel="stylesheet" href="/prose-review/theme.css">
      <link rel="stylesheet" href="/prose-review/site.css">
      <link rel="stylesheet" href="/prose-review/figures.css">
      <style>body{margin:16px}.prose{width:min(750px,calc(100vw - 32px));max-width:750px;margin-inline:auto}</style>
      <script type="module" src="/assets/article-figures.js"></script>
      </head><body><main class="prose">${article.arranged}</main></body></html>` });
  });
}

async function ready(page) {
  return page.evaluate(async () => {
    const bounded = (promise, label, details) => {
      let timer;
      return Promise.race([promise, new Promise((resolve, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out after 10s: ${JSON.stringify(details())}`)), 10_000);
      })]).finally(() => clearTimeout(timer));
    };
    const fontState = () => ({ status: document.fonts.status,
      faces: [...document.fonts].map(font => ({ family: font.family, style: font.style, status: font.status })) });
    const faces = await bounded(Promise.all(['18px Raleway', 'italic 21px Raleway', '600 12px Raleway', '30px Montserrat']
      .map(font => document.fonts.load(font))), 'Offline font loading', fontState);
    await bounded(document.fonts.ready, 'Font-set readiness', fontState);
    const originalScroll = { left: scrollX, top: scrollY };
    for (const image of document.querySelectorAll('article img')) {
      const state = () => ({ src: image.getAttribute('src'), currentSrc: image.currentSrc, loading: image.loading,
        complete: image.complete, naturalWidth: image.naturalWidth, naturalHeight: image.naturalHeight,
        imageTop: image.getBoundingClientRect().top, scrollY, viewportHeight: innerHeight });
      // Native lazy loading is part of the original source. Visit each pending
      // image instead of changing its attributes or waiting forever on decode().
      if (!image.complete && image.loading === 'lazy') {
        image.scrollIntoView({ block: 'center', behavior: 'instant' });
        await bounded(new Promise(resolve => requestAnimationFrame(resolve)), 'Lazy-image viewport update', state);
      }
      try {
        await bounded(image.decode(), 'Original image decode', state);
      } catch (error) {
        throw new Error(`${error.message}; image state: ${JSON.stringify(state())}`);
      }
    }
    scrollTo({ ...originalScroll, behavior: 'instant' });
    await bounded(new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))),
      'Final layout frames', () => ({ url: location.href, scrollY }));
    return faces.map(font => font.length);
  });
}

async function inspect(page, original, mode) {
  return page.evaluate(({ source, arranged, mode }) => {
    const article = document.querySelector('.prose article');
    const expected = new DOMParser().parseFromString(source, 'text/html').querySelector('article');
    const rendered = new DOMParser().parseFromString(arranged, 'text/html').querySelector('article');
    const issues = [];
    const check = (condition, code, detail) => { if (!condition) issues.push({ code, ...detail }); };
    const rect = element => {
      const { left, right, top, bottom, width, height } = element.getBoundingClientRect();
      return { left, right, top, bottom, width, height };
    };
    const overlaps = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 0.75 &&
      Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0.75;
    const within = (inner, outer) => inner.left >= outer.left - 1 && inner.right <= outer.right + 1;
    const attrs = image => Object.fromEntries([...image.attributes].map(item => [item.name, item.value]));
    const imageAttrs = element => [...element.querySelectorAll('img')].map(attrs);
    const markup = (element, selector) => [...element.querySelectorAll(selector)].map(node => node.outerHTML);
    const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);
    const sameMembers = (left, right) => same(left.map(item => JSON.stringify(item)).sort(), right.map(item => JSON.stringify(item)).sort());
    const bodyText = element => {
      const copy = element.cloneNode(true);
      for (const figure of copy.querySelectorAll('figure')) figure.remove();
      return copy.textContent.replace(/\s+/g, ' ').trim();
    };
    check(article.textContent === rendered.textContent && bodyText(article) === bodyText(expected), 'content-text', {});
    check(same(markup(article, 'p'), markup(expected, 'p')), 'content-paragraphs', {});
    check(sameMembers(markup(article, 'figcaption'), markup(expected, 'figcaption')), 'content-captions', {});
    check(same(imageAttrs(article), imageAttrs(rendered)) && sameMembers(imageAttrs(article), imageAttrs(expected)), 'content-image-attributes', {});
    check(article.querySelectorAll('br').length === expected.querySelectorAll('br').length, 'content-linebreaks', {});
    const reader = rect(article.closest('.prose'));
    check(document.documentElement.scrollWidth <= innerWidth, 'horizontal-overflow',
      { scrollWidth: document.documentElement.scrollWidth, viewport: innerWidth });
    check(Math.abs(reader.width - (mode === 'desktop' ? 750 : 358)) <= 1, 'reader-width', { width: reader.width });

    // Verse has its own full corpus audit, and the reviewed PNG contour has an
    // alpha-aware test. Their intentional text/image geometry is not prose flow.
    const separateLayout = '.article-verse-row, .article-contour-opening, .article-verse-measure';
    const figures = [...article.querySelectorAll('figure')].filter(figure => !figure.closest(separateLayout));
    const obstacles = figures.map(figure => ({ element: figure, box: rect(figure),
      image: figure.querySelector('img')?.getAttribute('src') }));
    for (const image of article.querySelectorAll('img')) if (!image.closest(`figure, ${separateLayout}`)) {
      obstacles.push({ element: image, box: rect(image), image: image.getAttribute('src') });
    }
    const floats = [];
    let captionWords = 0;
    for (const figure of figures) {
      const image = figure.querySelector('img');
      if (!image) continue;
      const imageBox = rect(image), figureBox = rect(figure), caption = figure.querySelector('figcaption');
      const active = figure.classList.contains('article-figure--wrap');
      if (active) {
        const record = { image: image.getAttribute('src'), naturalWidth: image.naturalWidth, naturalHeight: image.naturalHeight,
          width: imageBox.width, height: imageBox.height, figureWidth: figureBox.width,
          side: getComputedStyle(figure).float, quote: figure.classList.contains('article-figure--quotation') };
        floats.push(record);
        check(mode === 'desktop' && record.side !== 'none', 'float-activation', record);
        check(Math.abs(record.width - record.naturalWidth) <= 1 && Math.abs(record.height - record.naturalHeight) <= 1,
          'float-native-size', record);
        check(within(figureBox, reader) && within(imageBox, figureBox), 'float-column-bounds', record);
      }
      if (caption && !figure.closest('.article-gallery--paired')) {
        const captionBox = rect(caption);
        check(captionBox.top >= figureBox.top - 1 && captionBox.bottom <= figureBox.bottom + 1 && within(captionBox, figureBox),
          'caption-detached', { image: image.getAttribute('src'), figure: figureBox, caption: captionBox });
        check(!overlaps(captionBox, imageBox), 'caption-image-overlap', { image: image.getAttribute('src') });
        const walker = document.createTreeWalker(caption, NodeFilter.SHOW_TEXT);
        let outOfBounds = 0;
        while (walker.nextNode()) for (const match of walker.currentNode.textContent.matchAll(/\S+/g)) {
          const range = document.createRange();
          range.setStart(walker.currentNode, match.index);
          range.setEnd(walker.currentNode, match.index + match[0].length);
          for (const box of range.getClientRects()) if (box.width && box.height) {
            captionWords += 1;
            if (!within(box, figureBox) || box.bottom > figureBox.bottom + 1) outOfBounds += 1;
          }
        }
        check(!outOfBounds, 'caption-text-overflow', { image: image.getAttribute('src'), count: outOfBounds });
      }
    }
    if (mode === 'phone') check(!floats.length, 'phone-floats', { count: floats.length });

    let wordsChecked = 0, collisionCount = 0, outsideCount = 0;
    const collisions = [], outside = [];
    const walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!node.textContent.trim() || node.parentElement.closest(`figure, figcaption, script, style, [hidden], ${separateLayout}`)) continue;
      const style = getComputedStyle(node.parentElement);
      if (style.visibility === 'hidden' || style.display === 'none') continue;
      for (const match of node.textContent.matchAll(/\S+/g)) {
        const range = document.createRange();
        range.setStart(node, match.index);
        range.setEnd(node, match.index + match[0].length);
        for (const box of range.getClientRects()) if (box.width && box.height) {
          wordsChecked += 1;
          const obstacle = obstacles.find(item => overlaps(box, item.box));
          if (obstacle) {
            collisionCount += 1;
            if (collisions.length < 5) collisions.push({ text: match[0], image: obstacle.image,
              word: { left: box.left, right: box.right, top: box.top, bottom: box.bottom }, figure: obstacle.box });
          }
          // A table's own scroll container is an intentional local overflow boundary.
          if (!within(box, reader) && !node.parentElement.closest('table')) {
            outsideCount += 1;
            if (outside.length < 5) outside.push({ text: match[0], left: box.left, right: box.right });
          }
        }
      }
    }
    check(!collisionCount, 'prose-figure-overlap', { count: collisionCount, examples: collisions });
    check(!outsideCount, 'prose-column-overflow', { count: outsideCount, examples: outside });
    return { imageCount: article.querySelectorAll('img').length, proseFigureCount: figures.length,
      excludedVerseRows: article.querySelectorAll('.article-verse-row').length,
      excludedContours: article.querySelectorAll('.article-contour-opening').length,
      wordsChecked, captionWords, activeFloats: floats, issues };
  }, { source: original.source, arranged: original.arranged, mode });
}

test('all original illustrated articles keep native prose floats, attached captions, and unobstructed reading columns', async ({ page }, testInfo) => {
  test.setTimeout(720_000);
  expect(originals.length, 'The complete illustrated archive must be available').toBeGreaterThan(500);
  const results = [], failures = [], blocked = [], pageErrors = [];
  let screenshots = 0;
  page.on('pageerror', error => pageErrors.push({ url: page.url(), message: error.message }));
  await routeOriginals(page, blocked);
  try {
    for (const [mode, width] of [['desktop', 1440], ['phone', 390]]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const original of originals) {
        await page.goto(`${origin}/prose-review/${original.id}/`, { waitUntil: 'load' });
        let faces;
        try {
          faces = await ready(page);
        } catch (error) {
          failures.push({ id: original.id, title: original.title, mode,
            issues: [{ code: 'resource-readiness', message: error.message }] });
          throw error;
        }
        const result = { id: original.id, title: original.title, mode, ...(await inspect(page, original, mode)) };
        if (faces.some(count => count !== 1)) result.issues.push({ code: 'offline-fonts', faces });
        results.push(result);
        if (result.issues.length) {
          failures.push({ id: original.id, title: original.title, mode, issues: result.issues });
          if (screenshots < 6) {
            screenshots += 1;
            const target = result.issues.find(issue => issue.image || issue.examples?.[0]?.image);
            const source = target?.image || target?.examples?.[0]?.image;
            if (source) await page.locator('article img').evaluateAll((images, value) => {
              images.find(image => image.getAttribute('src') === value)?.scrollIntoView({ block: 'center' });
            }, source);
            const output = testInfo.outputPath(`failure-${mode}-${original.id}.png`);
            await page.screenshot({ path: output, animations: 'disabled' });
            await testInfo.attach(`failure-${mode}-${original.id}`, { path: output, contentType: 'image/png' });
          }
        }
        if (results.length % 100 === 0) console.log(
          `[prose corpus] ${results.length}/${originals.length * 2} pages; ${failures.length} findings; last ${mode}/${original.id}`);
      }
    }
    expect(results).toHaveLength(originals.length * 2);
    expect(results.some(result => result.activeFloats.length > 0), 'The native float enhancement must activate').toBe(true);
    expect(pageErrors, 'No runtime/resize errors').toEqual([]);
    expect(blocked, 'Every resource must be an offline original or reader asset').toEqual([]);
    expect(failures.length, JSON.stringify(failures.slice(0, 10), null, 2)).toBe(0);
  } finally {
    const output = testInfo.outputPath('prose-corpus-measurements.json');
    const summary = { illustratedArticles: originals.length, completedPages: results.length,
      checkedWords: results.reduce((sum, result) => sum + result.wordsChecked, 0),
      checkedCaptionWords: results.reduce((sum, result) => sum + result.captionWords, 0),
      activeFloats: results.reduce((sum, result) => sum + result.activeFloats.length, 0),
      articleModesWithFailures: failures.length, failureScreenshots: screenshots };
    fs.writeFileSync(output, JSON.stringify({ summary, blocked, pageErrors, failures, results }, null, 2));
    await testInfo.attach('prose-corpus-measurements', { path: output, contentType: 'application/json' });
  }
});
