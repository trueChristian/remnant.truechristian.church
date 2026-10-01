import { test, expect } from '@playwright/test';
import fs from 'node:fs';

const courtship = '/en/youth/a-christ-centered-courtship-964b2776-41fa-496b-bbda-e3193f780d76/';
const svg = (width, height) => `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="#56866c"/></svg>`;
const image = (width = 240, height = 400) => `data:image/svg+xml,${encodeURIComponent(svg(width, height))}`;
const paragraph = '<p>' + 'Readable article prose stays beside this photograph, with enough room for a comfortable line of text. '.repeat(8) + '</p>';
const figure = (id, width = 240, height = 400, caption = '') => `<figure id="${id}"><img src="${image(width, height)}" alt="Test illustration">${caption ? `<figcaption>${caption}</figcaption>` : ''}</figure>`;
const fixture = async (page, content, { dir = 'ltr', script = true, style = '' } = {}) => {
  await page.route('**/figure-fixture/', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html dir="${dir}"><head>
    <link rel="stylesheet" href="/assets/site.css"><link rel="stylesheet" href="/assets/article-figures.css">
    <style>body{margin:24px}.prose{max-width:750px;margin-inline:auto}img{height:auto}${style}</style>
    ${script ? '<script type="module" src="/assets/article-figures.js"></script>' : ''}
    </head><body><div class="prose"><article data-article-id="fixture">${content}</article><footer id="after">After the article</footer></div></body></html>` }));
  await page.goto('/figure-fixture/', { waitUntil: 'domcontentloaded' });
};
const rect = locator => locator.evaluate(element => {
  const { top, right, bottom, left, width } = element.getBoundingClientRect();
  return { top, right, bottom, left, width };
});
const noOverflow = async page => expect(await page.evaluate(() => document.documentElement.scrollWidth))
  .toBeLessThanOrEqual(await page.evaluate(() => document.documentElement.clientWidth));

// Check text rectangles, not paragraph boxes: paragraph boxes themselves span behind CSS floats.
const firstTextRect = locator => locator.evaluate(element => {
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (node.textContent.trim()) {
      const range = document.createRange(); range.selectNodeContents(node);
      const { top, right, bottom, left } = range.getClientRects()[0];
      return { top, right, bottom, left };
    }
  }
});

test('Courtship portraits alternate around text without changing source content', async ({ page }) => {
  await page.goto(courtship);
  const figures = page.locator('.prose article > figure');
  await expect(figures).toHaveCount(2);
  await expect(figures.nth(0)).toHaveClass(/article-figure--start/);
  await expect(figures.nth(1)).toHaveClass(/article-figure--end/);
  for (let index = 0; index < 2; index++) {
    const box = await rect(figures.nth(index));
    const text = await firstTextRect(figures.nth(index).locator('xpath=following-sibling::p[1]'));
    expect(text.top).toBeLessThan(box.bottom);
    if (!index) expect(text.left).toBeGreaterThanOrEqual(box.right + 20);
    else expect(text.right).toBeLessThanOrEqual(box.left - 20);
    expect(box.width).toBeLessThanOrEqual(320);
  }
  const source = fs.readFileSync(`dist${courtship}index.html`, 'utf8');
  const unchanged = await page.evaluate(html => {
    const original = new DOMParser().parseFromString(html, 'text/html').querySelector('.prose article');
    const current = document.querySelector('.prose article');
    const attrs = root => [...root.querySelectorAll('figure img')].map(img => [img.getAttribute('src'), img.getAttribute('alt')]);
    return { text: original.textContent === current.textContent,
      images: JSON.stringify(attrs(original)) === JSON.stringify(attrs(current)),
      order: [...original.children].map(node => node.tagName).join() === [...current.children].map(node => node.tagName).join() };
  }, source);
  expect(unchanged).toEqual({ text: true, images: true, order: true });
  await noOverflow(page);
  fs.mkdirSync('.test-output/screenshots', { recursive: true });
  await figures.first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: '.test-output/screenshots/courtship-wrapped-desktop.png' });
});

test('mobile stacks, desktop restores, and narrow desktop columns stay readable', async ({ page }) => {
  await page.goto(courtship);
  const figures = page.locator('.prose article > figure');
  await expect(figures.first()).toHaveClass(/article-figure--wrap/);
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(figures.first()).not.toHaveClass(/article-figure--wrap/);
    for (const fig of await figures.all()) {
      expect(await fig.evaluate(element => getComputedStyle(element).float)).toBe('none');
      const box = await rect(fig);
      const text = await firstTextRect(fig.locator('xpath=following-sibling::p[1]'));
      expect(text.top).toBeGreaterThanOrEqual(box.bottom);
    }
    await noOverflow(page);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(figures.first()).toHaveClass(/article-figure--start/);
  await page.locator('.prose').evaluate(element => { element.style.width = '500px'; });
  await expect(figures.first()).not.toHaveClass(/article-figure--wrap/);
  await page.locator('.prose').evaluate(element => { element.style.removeProperty('width'); });
  await expect(figures.first()).toHaveClass(/article-figure--start/);
});

test('wide and multi-image figures stack; captions, headings, and article boundaries clear floats', async ({ page }) => {
  await fixture(page, figure('portrait', 240, 400, 'Original caption kept with its photograph') + paragraph +
    '<h2 id="section">A fresh section</h2>' + figure('wide', 1000, 500) + paragraph +
    '<figure id="pair"><img src="' + image() + '" alt="One"><img src="' + image() + '" alt="Two"><figcaption>A paired composition</figcaption></figure>' +
    '<p>A final illustrated section.</p>' + figure('last', 240, 500, 'The final caption'));
  await expect(page.locator('#portrait')).toHaveClass(/article-figure--wrap/);
  await expect(page.locator('#wide')).not.toHaveClass(/article-figure--wrap/);
  await expect(page.locator('#pair')).not.toHaveClass(/article-figure--wrap/);
  await expect(page.locator('#last')).toHaveClass(/article-figure--wrap/);
  const portrait = await rect(page.locator('#portrait'));
  const caption = await rect(page.locator('#portrait figcaption'));
  expect(caption.left).toBeGreaterThanOrEqual(portrait.left);
  expect(caption.right).toBeLessThanOrEqual(portrait.right + 1);
  expect(caption.bottom).toBeLessThanOrEqual(portrait.bottom + 1);
  expect((await rect(page.locator('#section'))).top).toBeGreaterThanOrEqual(portrait.bottom);
  expect((await rect(page.locator('#after'))).top).toBeGreaterThanOrEqual((await rect(page.locator('#last'))).bottom);
  await page.emulateMedia({ media: 'print' });
  expect(await page.locator('#portrait').evaluate(element => getComputedStyle(element).float)).toBe('none');
  await noOverflow(page);
});

test('adjacent figures stay stacked; separated wraps mirror logical sides in RTL', async ({ page }) => {
  for (const dir of ['ltr', 'rtl']) {
    await fixture(page, figure('one') + figure('two') + paragraph, { dir });
    await expect(page.locator('article')).toHaveClass(/article-figures/);
    for (const id of ['one', 'two']) {
      await expect(page.locator(`#${id}`)).not.toHaveClass(/article-figure--wrap/);
      expect(await page.locator(`#${id}`).evaluate(element => getComputedStyle(element).float)).toBe('none');
    }
    expect((await rect(page.locator('#two'))).top).toBeGreaterThanOrEqual((await rect(page.locator('#one'))).bottom);
    expect((await firstTextRect(page.locator('article > p'))).top).toBeGreaterThanOrEqual((await rect(page.locator('#two'))).bottom);
    await noOverflow(page);

    await fixture(page, figure('one') + paragraph + figure('two') + paragraph, { dir });
    await expect(page.locator('#one')).toHaveClass(/article-figure--start/);
    await expect(page.locator('#two')).toHaveClass(/article-figure--end/);
    const boxes = [await rect(page.locator('#one')), await rect(page.locator('#two'))];
    expect(boxes[1].top).toBeGreaterThanOrEqual(boxes[0].bottom);
    if (dir === 'ltr') expect(boxes[0].left).toBeLessThan(boxes[1].left);
    else expect(boxes[0].left).toBeGreaterThan(boxes[1].left);
    const lines = await page.locator('article').evaluate(article => [...article.querySelectorAll('p')].flatMap(p => {
      const range = document.createRange(); range.selectNodeContents(p);
      return [...range.getClientRects()].map(({ top, right, bottom, left }) => ({ top, right, bottom, left }));
    }));
    for (const [index, box] of boxes.entries()) {
      const overlapping = lines.filter(line => line.bottom > box.top + 1 && line.top < box.bottom - 1);
      expect(overlapping.length).toBeGreaterThan(0);
      const onLeft = (index === 0) === (dir === 'ltr');
      for (const line of overlapping) {
        if (onLeft) expect(line.left).toBeGreaterThanOrEqual(box.right + 20);
        else expect(line.right).toBeLessThanOrEqual(box.left - 20);
      }
      const column = await rect(page.locator('article'));
      // Available measure, rather than short final-line text, must stay comfortably readable.
      expect(onLeft ? column.right - box.right - 27 : box.left - column.left - 27).toBeGreaterThanOrEqual(18 * 18);
    }
    await noOverflow(page);
  }
});

test('late and broken images are safe and do not change previously assigned sides', async ({ page }) => {
  let release;
  const waitForImage = new Promise(resolve => { release = resolve; });
  await page.route('**/late-portrait.svg', async route => {
    await waitForImage;
    await route.fulfill({ contentType: 'image/svg+xml', body: svg(240, 400) });
  });
  await page.route('**/broken-portrait.svg', route => route.abort());
  try {
    await fixture(page, '<figure id="late"><img src="/late-portrait.svg" alt="Delayed photograph"></figure>' + paragraph +
      figure('ready') + paragraph + '<figure id="broken"><img src="/broken-portrait.svg" alt="Unavailable photograph"></figure>');
    await expect(page.locator('#ready')).toHaveClass(/article-figure--end/);
    await expect(page.locator('#late')).not.toHaveClass(/article-figure--wrap/);
    release();
    await expect(page.locator('#late')).toHaveClass(/article-figure--start/);
    await expect(page.locator('#ready')).toHaveClass(/article-figure--end/);
    await expect(page.locator('#broken')).not.toHaveClass(/article-figure--wrap/);
    await page.locator('#ready img').evaluate(img => { img.src = '/broken-portrait.svg'; });
    await expect(page.locator('#ready')).not.toHaveClass(/article-figure--wrap/);
  } finally { release(); }
});

test('already decoded images initialize immediately, initialization is idempotent, and no-JS stays stacked', async ({ page }) => {
  await fixture(page, figure('cached') + paragraph, { script: false });
  expect(await page.locator('#cached').evaluate(element => getComputedStyle(element).float)).toBe('none');
  const result = await page.evaluate(async () => {
    await document.querySelector('#cached img').decode();
    const { initArticleFigures } = await import('/assets/article-figures.js');
    const first = initArticleFigures(document);
    return { same: first === initArticleFigures(document), wrapped: document.querySelector('#cached').classList.contains('article-figure--wrap') };
  });
  expect(result).toEqual({ same: true, wrapped: true });
});
