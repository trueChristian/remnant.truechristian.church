import { test, expect } from '@playwright/test';
import fs from 'node:fs';

const registry = JSON.parse(fs.readFileSync('dist/routes.json', 'utf8'));
const route = id => {
  const entry = registry.articles.en[id];
  return `/en/${entry.category_slug}/${entry.alias}/`;
};
const circuit = route('6f61a1ae-d1cc-4748-abea-a8e44a891dc4');
const bondage = route('90100e26-9fe9-40a7-bfed-8a44154b0d27');
const africa = route('bd0b23ac-be3e-45b5-8782-83679a911aba');
const box = locator => locator.evaluate(element => {
  const { x, y, width, height, bottom, right } = element.getBoundingClientRect();
  return { x, y, width, height, bottom, right };
});
const noOverflow = async page => expect(await page.evaluate(() => document.documentElement.scrollWidth))
  .toBeLessThanOrEqual(await page.evaluate(() => document.documentElement.clientWidth));
const loaded = async page => {
  await page.locator('.prose img').evaluateAll(images => images.forEach(image => { image.loading = 'eager'; }));
  await expect.poll(() => page.locator('.prose img').evaluateAll(images =>
    images.every(image => image.complete && image.naturalWidth > 0))).toBe(true);
};

test('reviewed paired artwork stays beside its companion at desktop and phone widths', async ({ page }) => {
  for (const path of [circuit, bondage]) {
    await page.goto(path);
    await loaded(page);
    const pair = page.locator('.prose .article-gallery--paired').first();
    const images = pair.locator('img');
    await expect(images).toHaveCount(2);
    for (const width of [1440, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      const first = await box(images.nth(0)), second = await box(images.nth(1));
      expect(first.right).toBeLessThanOrEqual(second.x);
      expect(Math.min(first.bottom, second.bottom)).toBeGreaterThan(Math.max(first.y, second.y));
      await noOverflow(page);
    }
  }
});

test('existing wide photographs retain their full reading-column presentation', async ({ page }) => {
  for (const id of ['3f679973-e351-4fe3-8930-e08d9fba23a5',
    'c1a59f10-6bd7-43e4-b686-9be8b6cb3145', 'a235bdfc-afca-43a9-b095-abc11aaf5a70']) {
    await page.goto(route(id));
    await loaded(page);
    const image = page.locator('.prose img').first();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      expect(await image.evaluate(img => Boolean(img.closest('.article-gallery,.article-figure--wrap')))).toBe(false);
      expect((await box(image)).width).toBeCloseTo((await box(page.locator('.prose article'))).width, 0);
      const size = await image.evaluate(img => ({ natural: img.naturalWidth / img.naturalHeight,
        displayed: img.getBoundingClientRect().width / img.getBoundingClientRect().height }));
      expect(size.displayed).toBeCloseTo(size.natural, 2);
      await noOverflow(page);
    }
  }
});

test('From Africa has photo rows with captions attached and small-screen reflow', async ({ page }) => {
  await page.goto(africa);
  await loaded(page);
  const groups = page.locator('.prose .article-gallery');
  await expect(groups).toHaveCount(3);
  for (const [index, count] of [2, 3, 3].entries()) {
    const figures = groups.nth(index).locator(':scope > figure');
    await expect(figures).toHaveCount(count);
    const first = await box(figures.first());
    for (const figure of (await figures.all()).slice(1)) expect((await box(figure)).y).toBeCloseTo(first.y, 0);
    for (const caption of await groups.nth(index).locator('figcaption').all()) {
      const image = caption.locator('xpath=../img');
      expect((await box(caption)).y).toBeGreaterThanOrEqual((await box(image)).bottom);
    }
  }
  await page.setViewportSize({ width: 320, height: 900 });
  const figures = groups.first().locator(':scope > figure');
  expect((await box(figures.nth(1))).y).toBeGreaterThanOrEqual((await box(figures.nth(0))).bottom);
  await noOverflow(page);
});

test('unequal panels share a scale and tiny compositions retain their natural size', async ({ page }) => {
  await page.goto(route('77cd4a24-14db-4ba2-905f-4f3ecb1d3ea5'));
  await loaded(page);
  const images = page.locator('.prose .article-gallery--paired img');
  for (const width of [1440, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    const left = await box(images.first()), right = await box(images.last());
    expect(left.height).toBeCloseTo(right.height, 0);
    expect(left.width / right.width).toBeCloseTo(1959 / 668, 2);
    expect(right.x - left.right).toBeLessThanOrEqual(25);
    await noOverflow(page);
  }
  await page.goto(route('64555f1c-017c-4ac5-a941-3b577cf58ff3'));
  await loaded(page);
  expect((await box(page.locator('.prose .article-gallery--paired'))).width).toBeLessThan(290);
});

test('paired compositions survive no JavaScript, RTL, dark mode and print', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 900 } });
  const page = await context.newPage();
  try {
    await page.goto(bondage);
    const images = page.locator('.prose .article-gallery--paired img');
    await expect(images).toHaveCount(2);
    await page.locator('html').evaluate(element => { element.dir = 'rtl'; element.dataset.theme = 'dark'; });
    for (const media of ['screen', 'print']) {
      await page.emulateMedia({ media });
      expect((await box(images.first())).right).toBeLessThanOrEqual((await box(images.last())).x);
      expect(await images.first().evaluate(image => getComputedStyle(image).objectFit)).toBe('contain');
      await noOverflow(page);
    }
  } finally { await context.close(); }
});

test('paragraph drop caps keep body text readable and standalone scores keep their full height', async ({ page }) => {
  await page.goto(bondage);
  const lead = page.locator('.prose p.drop-cap').first();
  expect(await lead.evaluate(element => getComputedStyle(element).float)).toBe('none');
  expect(await lead.evaluate(element => getComputedStyle(element).fontSize)).toBe('18px');
  expect(await lead.evaluate(element => getComputedStyle(element, '::first-letter').fontSize)).toBe('64px');
  await page.locator('html').evaluate(element => { element.lang = 'ar'; });
  expect(await lead.evaluate(element => getComputedStyle(element, '::first-letter').float)).toBe('none');
  // A real reviewed sheet-music image must never become a float or shrink to the photo height cap.
  await page.goto(route('01e1bd6f-f251-4835-8729-2a052e4d514d'));
  await loaded(page);
  const score = page.locator('.prose .article-figure--standalone').first();
  await expect(score).not.toHaveClass(/article-figure--wrap/);
  expect(await score.locator('img').evaluate(image => getComputedStyle(image).maxHeight)).toBe('none');
  await noOverflow(page);
});
