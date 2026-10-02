import { test, expect } from '@playwright/test';
import fs from 'node:fs';

const registry = JSON.parse(fs.readFileSync('dist/routes.json', 'utf8'));
const indexes = Object.fromEntries(Object.keys(registry.articles).map(tag => [tag,
  JSON.parse(fs.readFileSync(`dist/${tag}/search-index.json`, 'utf8'))]));
const identity = (indexes.af[0] || indexes.en[0]).id;
const articlePath = tag => {
  const record = registry.articles[tag][identity];
  return `/${tag}/${record.category_slug}/${record.alias}/`;
};
const prefix = (path, tag) => path.replace(/^\/[^/]+\//u, `/${tag}/`);
const uuid = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/iu;

test('manual article language changes redirect to one localized canonical page', async ({ page }) => {
  for (const tag of ['af', 'de', 'nl']) {
    const expected = articlePath(tag);
    expect(expected).not.toMatch(uuid);
    await page.goto(prefix(articlePath('en'), tag));
    await expect(page).toHaveURL(new URL(expected, page.url()).href);
    await expect(page.locator('link[rel=canonical]')).toHaveAttribute('href', `https://remnant.truechristian.church${expected}`);
    await expect(page.locator('html')).toHaveAttribute('lang', tag);
    if (indexes[tag].some(record => record.id === identity)) {
      await expect(page.locator('.prose article')).toHaveCount(1);
      await expect(page.locator('.prose article')).toHaveAttribute('data-article-id', identity);
    } else {
      await expect(page.locator('.prose article')).toHaveCount(0);
      await expect(page.locator('.empty-state')).toBeVisible();
      await expect(page.locator('meta[name=robots]')).toHaveAttribute('content', 'noindex,follow');
    }
  }
  await page.goto(prefix(articlePath('af'), 'en'));
  await expect(page).toHaveURL(new URL(articlePath('en'), page.url()).href);
  await expect(page.locator('.prose article')).toHaveAttribute('data-article-id', identity);
});

test('manual category language changes redirect to localized category aliases', async ({ page }) => {
  const categoryId = registry.articles.en[identity].category_id;
  const english = `/en/${registry.categories.en[categoryId].slug}/`;
  for (const tag of ['af', 'de', 'nl']) {
    const expected = `/${tag}/${registry.categories[tag][categoryId].slug}/`;
    await page.goto(prefix(english, tag));
    await expect(page).toHaveURL(new URL(expected, page.url()).href);
    await expect(page.locator('link[rel=canonical]')).toHaveAttribute('href', `https://remnant.truechristian.church${expected}`);
    await expect(page.locator('html')).toHaveAttribute('lang', tag);
  }
});

test('article and category prefix redirects work with JavaScript disabled', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const page = await context.newPage();
    await page.goto(prefix(articlePath('en'), 'af'));
    await expect(page).toHaveURL(new URL(articlePath('af'), page.url()).href);
    const categoryId = registry.articles.en[identity].category_id;
    await page.goto(`/af/${registry.categories.en[categoryId].slug}/`);
    await expect(page).toHaveURL(new URL(`/af/${registry.categories.af[categoryId].slug}/`, page.url()).href);
  } finally {
    await context.close();
  }
});

test('reader links, downloads, and category filter URLs use readable aliases', async ({ page }) => {
  await page.goto(articlePath('en'));
  const links = await page.locator('main a[href]').evaluateAll(nodes => nodes.map(node => node.getAttribute('href')));
  expect(links.filter(link => link.startsWith('/'))).not.toEqual(expect.arrayContaining([expect.stringMatching(uuid)]));
  const download = page.locator('.reader-tools a[download]');
  await expect(download).toHaveAttribute('href', `${articlePath('en').replace(/\/$/u, '')}.md`);
  await page.goto('/en/search/');
  const categoryId = registry.articles.en[identity].category_id;
  await page.locator('select[name=category]').selectOption(registry.categories.en[categoryId].slug);
  await expect.poll(() => new URL(page.url()).searchParams.get('category')).toBe(registry.categories.en[categoryId].slug);
  expect(page.url()).not.toMatch(uuid);
  await page.goto(`/en/search/?category=${categoryId}`);
  await expect.poll(() => new URL(page.url()).searchParams.get('category')).toBe(registry.categories.en[categoryId].slug);
  expect(page.url()).not.toMatch(uuid);
});
