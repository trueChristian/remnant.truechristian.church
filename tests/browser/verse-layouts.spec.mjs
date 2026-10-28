import { test, expect } from '@playwright/test';
import fs from 'node:fs';

const route = '/en/woman/a-godly-woman/';
const source = fs.readFileSync(`dist${route}index.html`, 'utf8');
const noOverflow = async page => expect(await page.evaluate(() =>
  document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
const unchanged = async page => expect(await page.evaluate(html => {
  const original = new DOMParser().parseFromString(html, 'text/html').querySelector('.prose article');
  const current = document.querySelector('.prose article');
  const images = root => [...root.querySelectorAll('img')].map(img =>
    [img.getAttribute('src'), img.getAttribute('alt')]);
  return { text: current.textContent === original.textContent,
    breaks: current.querySelectorAll('br').length === original.querySelectorAll('br').length,
    images: JSON.stringify(images(current)) === JSON.stringify(images(original)) };
}, source)).toEqual({ text: true, breaks: true, images: true });

test('A Godly Woman keeps complete stanzas beside the illustrations', async ({ page }) => {
  await page.goto(route);
  await expect(page.locator('.article-verse-row')).toHaveCount(5);
  await expect.poll(() => page.locator('.article-verse-row--aside').count()).toBe(5);
  for (const row of await page.locator('.article-verse-row--aside').all()) {
    const boxes = await row.evaluate(element => {
      const text = element.querySelector('.article-verse-text').getBoundingClientRect();
      const figure = element.querySelector('figure').getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(element.querySelector('.article-verse-text'));
      return { gap: figure.left - text.right, imageWidth: figure.width,
        fits: [...range.getClientRects()].every(rect => rect.width === 0 || rect.right <= text.right + 1),
        linesIntact: [...element.querySelectorAll('.article-verse-text p')].every(stanza => {
          range.selectNodeContents(stanza);
          const lines = new Set([...range.getClientRects()].filter(rect => rect.width > 0).map(rect => Math.round(rect.top)));
          return lines.size === stanza.querySelectorAll('br').length + 1;
        }) };
    });
    expect(boxes.gap).toBeGreaterThanOrEqual(24);
    expect(boxes.imageWidth).toBeLessThanOrEqual(180);
    expect(boxes.fits).toBe(true);
    expect(boxes.linesIntact).toBe(true);
  }
  await unchanged(page);
  await noOverflow(page);
  fs.mkdirSync('.test-output/screenshots', { recursive: true });
  await page.locator('.article-verse-row').first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: '.test-output/screenshots/godly-woman-desktop.png' });
});

test('a delayed verse image joins its stanzas after loading', async ({ page }) => {
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  await page.route('**/928398a6-8e23-4cd3-8069-33a9cfd68f23-2.png', async route => {
    await pending;
    await route.continue();
  });
  await page.goto(route, { waitUntil: 'domcontentloaded' });
  const first = page.locator('.article-verse-row').first();
  await expect.poll(() => page.locator('.article-verse-row--aside').count()).toBe(4);
  await expect(first).not.toHaveClass(/article-verse-row--aside/);
  release();
  await expect(first).toHaveClass(/article-verse-row--aside/);
  await unchanged(page);
});

test('phone and narrow desktop columns stack without clipping or changing reading order', async ({ page }) => {
  await page.goto(route);
  for (const width of [390, 320, 768]) {
    await page.setViewportSize({ width, height: 900 });
    if (width === 768) await page.locator('.prose').evaluate(element => { element.style.width = '460px'; });
    await expect(page.locator('.article-verse-row--aside')).toHaveCount(0);
    for (const row of await page.locator('.article-verse-row').all()) {
      const result = await row.evaluate(element => {
        const figure = element.querySelector('figure').getBoundingClientRect();
        const text = element.querySelector('.article-verse-text').getBoundingClientRect();
        const img = element.querySelector('img');
        return { separate: figure.bottom <= text.top || text.bottom <= figure.top,
          imageHeight: img.getBoundingClientRect().height,
          noUpscale: img.getBoundingClientRect().width <= img.naturalWidth };
      });
      expect(result.separate).toBe(true);
      expect(result.imageHeight).toBeLessThanOrEqual(300);
      expect(result.noUpscale).toBe(true);
    }
    await unchanged(page);
    await noOverflow(page);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.prose').evaluate(element => element.style.removeProperty('width'));
  await page.locator('.article-verse-row').first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: '.test-output/screenshots/godly-woman-mobile.png' });
});

test('RTL mirrors the illustration column and larger type falls back to full-width verse', async ({ page }) => {
  await page.route('**/verse-rtl/', request => request.fulfill({ contentType: 'text/html',
    body: source.replace('<html lang="en" dir="ltr"', '<html lang="ar" dir="rtl"') }));
  await page.goto('/verse-rtl/');
  await expect.poll(() => page.locator('.article-verse-row--aside').count()).toBe(5);
  for (const row of await page.locator('.article-verse-row--aside').all()) {
    expect(await row.evaluate(element => element.querySelector('figure').getBoundingClientRect().right <=
      element.querySelector('.article-verse-text').getBoundingClientRect().left - 24)).toBe(true);
  }
  await page.addStyleTag({ content: '.prose .poem { font-size: 28px; }' });
  await page.setViewportSize({ width: 1430, height: 1000 });
  await expect(page.locator('.article-verse-row--aside')).toHaveCount(0);
  await unchanged(page);
  await noOverflow(page);
});

test('no-JavaScript and print preserve all illustrations and stanza breaks', async ({ browser, page }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const plain = await context.newPage();
  await plain.goto(`http://127.0.0.1:8080${route}`);
  await expect(plain.locator('.article-verse-row')).toHaveCount(5);
  await expect(plain.locator('.article-verse-row--aside')).toHaveCount(0);
  await unchanged(plain);
  await noOverflow(plain);
  await context.close();
  await page.goto(route);
  await page.emulateMedia({ media: 'print' });
  for (const row of await page.locator('.article-verse-row').all()) {
    expect(await row.evaluate(element => getComputedStyle(element).display)).toBe('flow-root');
  }
  await unchanged(page);
});
