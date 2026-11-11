import { test, expect } from '@playwright/test';
import fs from 'node:fs';

const registry = JSON.parse(fs.readFileSync('dist/routes.json', 'utf8'));
const ids = {
  soul: 'bbeefd6c-2894-4a32-88a8-1d6e889e3159', heart: 'bb70a7bb-68b1-4cdd-b85a-f732afefeaa2',
  konkomba: 'd5e65bbb-a0fd-4996-894a-dc47d8af844b', law: 'a0845312-06a2-4d8b-82ed-076c7305fcc1',
  report: 'e287ea36-8b9d-4d08-aa35-d9a6b7113981', amy: '691f67b8-a430-4420-8b25-499101aec0c3',
  sisters: 'a5232cdc-2e95-42b0-85f1-b2bfd9ad160c', crucified: '7a66963a-8f7e-4083-bed3-227b354fae1b',
  seeds: 'ea463a08-df2c-4fdf-96c4-5833e4100265', sacrifices: 'e38dca23-911a-42b6-96a2-de9ff0c4bb87',
};
const route = id => `/en/${registry.articles.en[id].category_slug}/${registry.articles.en[id].alias}/`;
const root = page => page.locator('.prose article');
const picture = (page, id, number) => root(page).locator(`img[src*="${id}-${number}."]`);
const rect = locator => locator.evaluate(node => {
  const { top, left, right, bottom, width, height } = node.getBoundingClientRect();
  return { top, left, right, bottom, width, height };
});
async function ready(page, id) {
  await page.goto(route(id));
  await page.evaluate(async () => {
    await Promise.all([...document.querySelectorAll('.prose img')].map(async image => {
      image.loading = 'eager';
      await image.decode();
    }));
    await document.fonts.ready;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}
async function intact(page, id) {
  const original = fs.readFileSync(`dist${route(id)}index.html`, 'utf8');
  const comparison = await root(page).evaluate((current, html) => {
    const source = new DOMParser().parseFromString(html, 'text/html').querySelector('.prose article');
    const images = node => [...node.querySelectorAll('img')].map(image => [image.getAttribute('src'), image.getAttribute('alt')]);
    return { text: current.textContent === source.textContent,
      breaks: current.querySelectorAll('br').length === source.querySelectorAll('br').length,
      images: JSON.stringify(images(current)) === JSON.stringify(images(source)),
      overflow: document.documentElement.scrollWidth > innerWidth };
  }, original);
  expect(comparison).toEqual({ text: true, breaks: true, images: true, overflow: false });
}
async function native(image) {
  const dimensions = await image.evaluate(node => ({ width: node.getBoundingClientRect().width, natural: node.naturalWidth }));
  expect(dimensions.width).toBeCloseTo(dimensions.natural, 0);
}
async function centered(image, article) {
  const box = await rect(image), column = await rect(article);
  expect(Math.abs(box.left + box.right - column.left - column.right)).toBeLessThan(2);
}

for (const [name, id] of Object.entries(ids)) {
  test(`reviewed ${name} layout keeps its content and requested desktop placement`, async ({ page }, info) => {
    await ready(page, id);
    const article = root(page), column = await rect(article), first = picture(page, id, 1);
    if (name === 'soul') {
      const note = article.locator(':scope > aside.article-source-note');
      await expect(note.locator('p')).toHaveCount(2);
      expect((await rect(note)).bottom).toBeLessThan((await rect(first)).top);
      await expect(first.locator('..')).toHaveClass(/article-figure--wrap/);
      await native(first);
    } else if (name === 'heart' || name === 'amy') {
      const row = article.locator('.article-editorial-verse');
      await expect(row).toHaveClass(/article-editorial--active/);
      const text = await rect(row.locator(':scope > .article-editorial-text'));
      expect((await rect(first)).left).toBeGreaterThan(text.right + 20);
      if (name === 'amy') {
        await native(first);
        const intro = await rect(article.locator(':scope > p').first());
        expect(intro.width).toBeCloseTo(column.width, 0);
        expect(intro.bottom).toBeLessThanOrEqual((await rect(row)).top);
        await expect(row.locator('figcaption')).toHaveCount(1);
      }
    } else if (name === 'law') {
      const row = article.locator('.article-quote-frame');
      await expect(row).toHaveClass(/article-editorial--active/);
      const box = await rect(row), top = await rect(first), bottom = await rect(picture(page, id, 2));
      expect(top.left).toBeCloseTo(box.left, 0); expect(top.top).toBeCloseTo(box.top, 0);
      expect(bottom.right).toBeCloseTo(box.right, 0); expect(bottom.bottom).toBeCloseTo(box.bottom, 0);
      expect(box.bottom - (await rect(row.locator('blockquote'))).bottom).toBeLessThan(45);
      await native(first); await native(picture(page, id, 2));
      const overlap = await row.evaluate(row => {
        const pictures = [...row.querySelectorAll('img')].map(image => image.getBoundingClientRect());
        const walker = document.createTreeWalker(row.querySelector('blockquote'), NodeFilter.SHOW_TEXT);
        let node, count = 0;
        while ((node = walker.nextNode())) for (const word of node.textContent.matchAll(/\S+/g)) {
          const range = document.createRange(); range.setStart(node, word.index); range.setEnd(node, word.index + word[0].length);
          for (const line of range.getClientRects()) if (pictures.some(box => line.left < box.right - 1 && line.right > box.left + 1 && line.top < box.bottom - 1 && line.bottom > box.top + 1)) count++;
        }
        return count;
      });
      expect(overlap).toBe(0);
    } else if (name === 'konkomba' || name === 'seeds') {
      const row = article.locator('.article-editorial-prose');
      await expect(row).toHaveClass(/article-editorial--active/);
      await centered(first, article);
      if (name === 'konkomba') {
        expect((await rect(picture(page, id, 2))).width).toBeCloseTo(400, 0);
        expect((await rect(article.locator(':scope > blockquote').first())).bottom).toBeLessThan((await rect(row)).top);
      } else {
        await native(picture(page, id, 2)); await native(picture(page, id, 3));
        await expect(row.locator('.article-editorial-art > figure')).toHaveCount(2);
      }
    } else if (name === 'report') {
      await expect(first.locator('..')).toHaveClass(/article-figure--wrap/);
      await native(first);
      const family = picture(page, id, 3), list = article.locator('[data-reader-list-flow]').last();
      await expect(family.locator('..')).toHaveClass(/article-figure--wrap/);
      await native(family);
      expect(await list.evaluate(node => getComputedStyle(node).display)).toBe('block');
      expect((await rect(list.locator('li').last())).top).toBeGreaterThan((await rect(family)).bottom);
    } else if (name === 'crucified') {
      expect((await rect(first)).right).toBeCloseTo(column.right, 0);
      expect((await rect(first)).bottom).toBeLessThan((await rect(article.locator('.poem'))).top);
      await native(first);
    } else if (name === 'sacrifices') {
      await expect(first.locator('..')).toHaveClass(/article-figure--wrap/);
      await native(first); await centered(picture(page, id, 2), article);
      await expect(picture(page, id, 2).locator('..')).toHaveClass(/article-figure--standalone/);
    } else if (name === 'sisters') {
      const authors = page.locator('.article-byline > span').first();
      await expect(authors.locator('a.author-link')).toHaveCount(23);
      expect(await authors.evaluate(node => getComputedStyle(node).columnCount)).toBe('3');
    }
    await intact(page, id);
    await article.scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(`${name}-desktop.png`) });
  });

  test(`reviewed ${name} layout remains readable at phone widths`, async ({ page }, info) => {
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await ready(page, id);
      await expect(root(page).locator('.article-editorial--active')).toHaveCount(0);
      await intact(page, id);
    }
    await page.screenshot({ path: info.outputPath(`${name}-320.png`) });
  });
}

test('long contributor credits use columns in cards without dropping names or links', async ({ page }, info) => {
  await ready(page, ids.sisters);
  const expected = await page.locator('.article-byline a.author-link').evaluateAll(nodes => nodes.map(node => [node.textContent, node.getAttribute('href')]));
  await page.evaluate(() => {
    const credits = document.querySelector('.article-byline > span').cloneNode(true);
    const card = document.createElement('article'); card.className = 'article-card'; card.id = 'review-card';
    card.style.cssText = 'width:350px;max-width:100%;margin:16px auto';
    const bottom = document.createElement('div'); bottom.className = 'card-bottom'; bottom.append(credits);
    const arrow = document.createElement('a'); arrow.className = 'card-arrow'; arrow.href = '#'; arrow.textContent = '↗'; bottom.append(arrow);
    card.append(bottom); document.body.replaceChildren(card);
  });
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const credits = page.locator('#review-card .card-bottom > span');
    expect(await credits.evaluate(node => getComputedStyle(node).columnCount)).toBe('2');
    expect(await credits.locator('a').evaluateAll(nodes => nodes.map(node => [node.textContent,node.getAttribute('href')]))).toEqual(expected);
    expect((await rect(credits)).height).toBeLessThan(310);
  }
  await page.screenshot({ path: info.outputPath('contributors-card-320.png') });
});

test('reviewed compositions support RTL, large reading text and print', async ({ page }) => {
  for (const name of ['heart', 'law', 'amy', 'konkomba', 'seeds']) {
    const id = ids[name]; await ready(page, id);
    await page.locator('html').evaluate(node => node.dir = 'rtl');
    await intact(page, id);
    await page.locator('.prose').evaluate(node => {
      node.style.fontSize = '28px';
      for (const text of node.querySelectorAll('.poem, blockquote')) text.style.fontSize = '28px';
    });
    await expect(root(page).locator('.article-editorial--active')).toHaveCount(0);
    await page.emulateMedia({ media: 'print' });
    const art = root(page).locator('.article-editorial-art').first();
    if (await art.count()) expect(await art.evaluate(node => getComputedStyle(node).float)).toBe('none');
    await intact(page, id);
    await page.emulateMedia({ media: 'screen' });
  }
});

test.describe('without JavaScript', () => {
  test.use({ javaScriptEnabled: false });
  test('reviewed source note, poem columns and images remain complete without enhancement', async ({ page }) => {
    for (const name of ['soul','heart','law','amy','konkomba','seeds','crucified']) {
      await page.goto(route(ids[name]));
      await expect(root(page).locator('.article-editorial--active')).toHaveCount(0);
      await intact(page, ids[name]);
    }
  });
});


test('broken or changed artwork disables the reviewed enhanced composition', async ({ page }) => {
  await page.route('**/editorial-missing.png', route => route.abort());
  for (const name of ['heart','law','amy','konkomba','seeds']) {
    await ready(page, ids[name]);
    const row = root(page).locator('.article-editorial--active');
    await expect(row).toHaveCount(1);
    await row.locator('img').first().evaluate(image => image.src = '/editorial-missing.png');
    await expect(root(page).locator('.article-editorial--active')).toHaveCount(0);
  }
  await ready(page, ids.konkomba);
  await picture(page, ids.konkomba, 2).evaluate(image => {
    image.src = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"></svg>');
  });
  await expect(root(page).locator('.article-editorial--active')).toHaveCount(0);
});
