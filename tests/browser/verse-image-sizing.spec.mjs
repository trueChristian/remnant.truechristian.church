import { test, expect } from '@playwright/test';
import { fixtureAsset } from './fixture-assets.mjs';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

const css = ['assets/site.css', 'assets/article-figures.css'].map(file => fs.readFileSync(file, 'utf8')).join('\n');
const poem = '<p>Each line retains its place<br>The picture stays nearby<br>These words remain unchanged</p>';
const arrange = source => execFileSync('python3', ['-c', `
import sys
sys.path.insert(0, 'scripts')
from article_figures import arrange_article_figures
print(arrange_article_figures(sys.stdin.read()))
`], { input: source, encoding: 'utf8' });

async function mount(page, { width = 120, height = 137, verse = true, inherited = false, dir = 'ltr' } = {}) {
  const figure = '<figure><img src="/picture.svg" alt="Original illustration"></figure>';
  const content = inherited ? `<div class="poem">${figure}${poem}</div>` :
    figure + (verse ? `<div class="poem">${poem}</div>` : poem);
  const source = `<article data-article-id="fixture">${content}</article>`;
  const rendered = arrange(source);
  await page.route('**/*', route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/picture.svg') return route.fulfill({ contentType: 'image/svg+xml',
      body: `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="#789582"/></svg>` });
    const asset = fixtureAsset(pathname);
    if (asset) return route.fulfill(asset);
    if (pathname !== '/verse-size-fixture/') return route.abort();
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html dir="${dir}"><head>
      <meta name="viewport" content="width=device-width, initial-scale=1"><style>
      *{box-sizing:border-box}img{display:block;max-width:100%;height:auto}${css}
      body{margin:16px}.prose{max-width:750px;margin:auto;font-family:Arial,sans-serif}
      </style><script type="module" src="/assets/article-figures.js"></script></head><body><main class="prose">${rendered}</main></body></html>` });
  });
  await page.goto('http://127.0.0.1:8080/verse-size-fixture/');
  await expect.poll(() => page.locator('article img').evaluate(image => image.naturalWidth)).toBe(width);
  return source;
}

async function geometry(page) {
  return page.evaluate(() => {
    const group = document.querySelector('.article-verse-row');
    const image = group.querySelector('img');
    const text = group.querySelector('.article-verse-text');
    const rectangle = element => {
      const { left, right, top, bottom, width, height } = element.getBoundingClientRect();
      return { left, right, top, bottom, width, height };
    };
    return { image: rectangle(image), text: rectangle(text),
      aside: group.classList.contains('article-verse-row--aside'),
      breaks: text.querySelectorAll('br').length, content: text.textContent,
      overflow: document.documentElement.scrollWidth > innerWidth };
  });
}

test('small poem artwork grows beside the actual verse measure, including inherited verse and RTL', async ({ page }) => {
  for (const options of [{}, { inherited: true }, { dir: 'rtl' }]) {
    await page.unrouteAll({ behavior: 'wait' });
    await mount(page, options);
    await expect(page.locator('.article-verse-row')).toHaveClass(/article-verse-row--aside/);
    const result = await geometry(page);
    expect(result.image.width).toBeCloseTo(240, 1);
    expect(result.image.height).toBeCloseTo(274, 1);
    expect(Math.abs(result.image.top - result.text.top)).toBeLessThanOrEqual(1);
    const gap = options.dir === 'rtl' ? result.text.left - result.image.right : result.image.left - result.text.right;
    // A row inside .poem inherits its 17px type; other rows inherit 18px.
    expect(gap).toBeCloseTo(options.inherited ? 25.5 : 27, 1);
    expect(result.breaks).toBe(2);
    expect(result.overflow).toBe(false);
  }
});

test('tall illustrations stay proportionate and line-broken credits do not acquire enlargement', async ({ page }) => {
  await mount(page, { width: 495, height: 2049 });
  await expect(page.locator('.article-verse-row')).toHaveClass(/article-verse-row--aside/);
  const tall = await geometry(page);
  expect(tall.image.height).toBeCloseTo(600, 1);
  expect(tall.image.width / tall.image.height).toBeCloseTo(495 / 2049, 3);
  await page.unrouteAll({ behavior: 'wait' });
  await mount(page, { verse: false });
  await expect(page.locator('.article-verse-row')).toHaveClass(/article-verse-row--aside/);
  const credit = await geometry(page);
  expect(credit.image.width).toBeCloseTo(120, 1);
  expect(credit.image.height).toBeCloseTo(137, 1);
});

test('narrow screens, enlarged type, print and no JavaScript keep complete source-order stanzas', async ({ page, browser }) => {
  await mount(page);
  await expect(page.locator('.article-verse-row')).toHaveClass(/article-verse-row--aside/);
  const original = (await geometry(page)).content;
  await page.setViewportSize({ width: 390, height: 900 });
  await expect(page.locator('.article-verse-row')).not.toHaveClass(/article-verse-row--aside/);
  let result = await geometry(page);
  expect(result.image.bottom).toBeLessThanOrEqual(result.text.top);
  expect(result.content).toBe(original);
  expect(result.breaks).toBe(2);
  expect(result.overflow).toBe(false);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addStyleTag({ content: '.prose .poem{font-size:48px}' });
  await expect(page.locator('.article-verse-row')).not.toHaveClass(/article-verse-row--aside/);
  await page.emulateMedia({ media: 'print' });
  expect(await page.locator('.article-verse-row').evaluate(element => getComputedStyle(element).display)).toBe('flow-root');
  const context = await browser.newContext({ javaScriptEnabled: false });
  const plain = await context.newPage();
  await mount(plain);
  result = await geometry(plain);
  expect(result.aside).toBe(false);
  expect(result.image.bottom).toBeLessThanOrEqual(result.text.top);
  expect(result.content).toBe(original);
  expect(result.breaks).toBe(2);
  await context.close();
});
