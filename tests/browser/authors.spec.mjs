import { test, expect } from '@playwright/test';
import fs from 'node:fs';

const registry = JSON.parse(fs.readFileSync('dist/routes.json', 'utf8'));
const source = JSON.parse(fs.readFileSync('.build/english/index.json', 'utf8')).articles;
const locales = Object.fromEntries(fs.readdirSync('locales').filter(file => file.endsWith('.json')).map(file => {
  const locale = JSON.parse(fs.readFileSync(`locales/${file}`, 'utf8'));
  return [locale.meta.tag, locale];
}));
const indexes = Object.fromEntries(Object.keys(locales).map(tag => [tag,
  JSON.parse(fs.readFileSync(`dist/${tag}/search-index.json`, 'utf8'))]));
const curated = JSON.parse(fs.readFileSync('data/author-aliases.json', 'utf8')).authors;
const canonicalNames = new Map(Object.entries(curated).flatMap(([name, aliases]) =>
  [name, ...aliases].map(alias => [alias, name])));
const canonicalName = name => canonicalNames.get(name) || name;
const authors = new Map();
const sourceNames = new Map();
const namedCredits = article => (article.byline?.authors || []).filter(author => author.name != null);
for (const article of source) {
  for (const author of namedCredits(article)) {
    const name = canonicalName(author.name);
    if (!authors.has(name)) authors.set(name, new Set());
    if (!sourceNames.has(name)) sourceNames.set(name, new Set());
    authors.get(name).add(article.id);
    sourceNames.get(name).add(author.name);
  }
}
const authorPath = (tag, name) => `/${tag}/authors/${registry.authors[tag][name].slug}/`;
const articlesFor = (tag, name) => indexes[tag].filter(article => authors.get(name).has(article.id));
const primary = [...authors.keys()].sort((a, b) => authors.get(b).size - authors.get(a).size)[0];
const translatedTag = Object.keys(locales).find(tag => tag !== 'en' && articlesFor(tag, primary).length);
const emptyTag = Object.keys(locales).find(tag => tag !== 'en' && !articlesFor(tag, primary).length);
const shared = source.find(article => new Set(namedCredits(article).map(author => canonicalName(author.name))).size > 1);
const uuid = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/iu;
const text = (tag, key, count) => locales[tag].ui[key].replace('{count}', String(count));
const headingLinks = page => page.locator('.author-articles h2 a');

test('Authors directory exposes each canonical author with distinct source article counts', async ({ page }) => {
  await page.goto('/en/authors/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.authors-page h1')).toHaveText(locales.en.ui.authors);
  await expect(page.locator('.author-card')).toHaveCount(authors.size);
  const names = await page.locator('.author-card h2').allTextContents();
  expect(new Set(names)).toEqual(new Set(authors.keys()));
  const card = page.locator('.author-card').filter({ has: page.getByRole('heading', { name: primary, exact: true }) });
  await expect(card).toContainText(text('en', 'author_total_articles', authors.get(primary).size));
  await expect(card).toContainText(text('en', 'author_available_articles', authors.get(primary).size));
  await expect(card.locator('img')).toHaveCount(0);
  const links = await page.locator('.author-card h2 a').evaluateAll(nodes => nodes.map(node => node.getAttribute('href')));
  expect(new Set(links)).toEqual(new Set([...authors.keys()].map(name => authorPath('en', name))));
  expect(links.every(link => !uuid.test(link))).toBe(true);
});

test('directory and author articles open the existing category canonical reader', async ({ page }) => {
  await page.goto('/en/', { waitUntil: 'domcontentloaded' });
  await page.locator('.tcc-header__menu').getByRole('link', { name: locales.en.ui.authors, exact: true }).click();
  await expect(page).toHaveURL(new URL('/en/authors/', page.url()).href);
  await page.locator('.author-card').getByRole('link', { name: primary, exact: true }).click();
  await expect(page).toHaveURL(new URL(authorPath('en', primary), page.url()).href);
  await expect(page.locator('.author-profile h1')).toHaveText(primary);
  const expected = articlesFor('en', primary).slice(0, 24);
  const links = await headingLinks(page).evaluateAll(nodes => nodes.map(node => node.getAttribute('href')));
  expect(links).toEqual(expected.map(article => article.url));
  expect(links.every(link => !link.includes('/authors/') && !uuid.test(link))).toBe(true);
  await headingLinks(page).first().click();
  await expect(page).toHaveURL(new URL(expected[0].url, page.url()).href);
  await expect(page.locator('.prose article')).toHaveAttribute('data-article-id', expected[0].id);
  await expect(page.locator('link[rel=canonical]')).toHaveAttribute('href', `https://remnant.truechristian.church${expected[0].url}`);
  await page.locator(`.article-byline a[href="${authorPath('en', primary)}"]`).click();
  await expect(page).toHaveURL(new URL(authorPath('en', primary), page.url()).href);
});

test('one coauthored article is reachable under every credited name without duplicate readers', async ({ page }) => {
  expect(shared, 'The source fixture must exercise a real shared credit').toBeTruthy();
  const names = [...new Set(namedCredits(shared).map(author => canonicalName(author.name)))];
  const canonical = indexes.en.find(article => article.id === shared.id).url;
  for (const name of names) {
    const position = articlesFor('en', name).findIndex(article => article.id === shared.id);
    const number = Math.floor(position / 24) + 1;
    const base = authorPath('en', name);
    await page.goto(number === 1 ? base : `${base}page/${number}/`, { waitUntil: 'domcontentloaded' });
    const links = await headingLinks(page).evaluateAll(nodes => nodes.map(node => node.getAttribute('href')));
    expect(links.filter(link => link === canonical)).toHaveLength(1);
  }
  await page.goto(canonical, { waitUntil: 'domcontentloaded' });
  for (const name of names) {
    const credit = page.locator(`.article-byline a[href="${authorPath('en', name)}"]`);
    await expect(credit).toHaveCount(1);
    expect([name, ...sourceNames.get(name)]).toContain(await credit.textContent());
  }
});

test('role-only editorial credits keep readers, issue links, and downloads without invented authors', async ({ page }) => {
  const unnamed = source.filter(article => article.byline?.authors?.some(author => author.name == null)
    && !namedCredits(article).length && article.byline.raw);
  test.skip(!unnamed.length, 'This source fixture has no role-only editorial credits');
  for (const article of unnamed) {
    const result = indexes.en.find(record => record.id === article.id);
    expect(result, 'An unnamed author must not remove an article from search').toBeTruthy();
    expect(result.author).toBe(article.byline.raw);
    expect(result.authors).toEqual([]);
    await page.goto(result.url, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.prose article')).toHaveAttribute('data-article-id', article.id);
    await expect(page.locator('.article-byline')).toContainText(article.byline.raw);
    await expect(page.locator('.article-byline .author-link')).toHaveCount(0);
    const markdownURL = await page.locator('.reader-tools a[download]').getAttribute('href');
    const markdown = await page.request.get(markdownURL);
    expect(markdown.ok()).toBe(true);
    expect((await markdown.text()).replace(/\\([\\`*{}\[\]()#+\-.!_>])/gu, '$1')).toContain(article.byline.raw);
    await page.locator('.article-issue').click();
    await expect(page.locator(`.issue-contents h2 a[href="${result.url}"]`)).toHaveCount(1);
  }
});

test('reviewed aliases share one profile with the union of articles and preserved printed credits', async ({ page }) => {
  const merged = [...sourceNames].filter(([, names]) => names.size > 1);
  test.skip(!merged.length, 'This source fixture has no reviewed spelling variants');
  await page.goto('/en/authors/', { waitUntil: 'domcontentloaded' });
  for (const [name, variants] of merged) {
    const card = page.locator('.author-card').filter({ has: page.getByRole('heading', { name, exact: true }) });
    await expect(card).toHaveCount(1);
    await expect(card).toContainText(text('en', 'author_total_articles', authors.get(name).size));
    for (const variant of variants) {
      if (variant !== name) await expect(page.locator('.author-card h2').getByText(variant, { exact: true })).toHaveCount(0);
    }
  }
  const aliasedArticle = source.find(article => article.byline?.authors?.some(author =>
    canonicalName(author.name) !== author.name && article.byline.raw?.includes(author.name)));
  expect(aliasedArticle, 'A printed variant must exercise linking to its canonical identity').toBeTruthy();
  const person = aliasedArticle.byline.authors.find(author =>
    canonicalName(author.name) !== author.name && aliasedArticle.byline.raw?.includes(author.name));
  const name = canonicalName(person.name);
  const articleURL = indexes.en.find(article => article.id === aliasedArticle.id).url;
  await page.goto(articleURL, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.article-byline')).toContainText(aliasedArticle.byline.raw);
  const credit = page.locator(`.article-byline a[href="${authorPath('en', name)}"]`);
  await expect(credit).toHaveCount(1);
  expect([name, ...sourceNames.get(name)]).toContain(await credit.textContent());
  await credit.click();
  await expect(page.locator('.author-profile h1')).toHaveText(name);
  const actual = [];
  for (let number = 1; number <= Math.ceil(articlesFor('en', name).length / 24); number += 1) {
    if (number > 1) await page.locator('.author-profile a[rel=next]').click();
    actual.push(...await headingLinks(page).evaluateAll(nodes => nodes.map(node => node.getAttribute('href'))));
  }
  expect(actual).toEqual(articlesFor('en', name).map(article => article.url));
  expect(new Set(actual).size).toBe(actual.length);
});

test('retired author aliases redirect to the same canonical identity in every language', async ({ page }) => {
  const candidate = [...sourceNames].find(([name, names]) => names.size > 1
    && registry.authors.en[name].history.length > 0);
  test.skip(!candidate, 'No previously published reviewed alias is present in this fixture');
  const [name] = candidate;
  const old = registry.authors.en[name].history[0];
  for (const tag of Object.keys(locales)) {
    await page.goto(old.replace(/^\/en\//u, `/${tag}/`), { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(new URL(authorPath(tag, name), page.url()).href);
    await expect(page.locator('.author-profile h1')).toHaveText(name);
    await expect(page.locator('link[rel=canonical]')).toHaveAttribute('href', `https://remnant.truechristian.church${authorPath(tag, name)}`);
  }
});

test('language selection keeps author identity and displays only available translations', async ({ page }) => {
  test.skip(!translatedTag, 'No current translations for the selected source author');
  await page.goto(authorPath('en', primary), { waitUntil: 'domcontentloaded' });
  await page.locator('[data-language-select]').selectOption(authorPath(translatedTag, primary));
  await expect(page).toHaveURL(new URL(authorPath(translatedTag, primary), page.url()).href);
  await expect(page.locator('html')).toHaveAttribute('lang', translatedTag);
  await expect(page.locator('.author-profile h1')).toHaveText(primary);
  await expect(page.locator('.author-profile .author-counts')).toContainText(text(translatedTag, 'author_available_articles', articlesFor(translatedTag, primary).length));
  const links = await headingLinks(page).evaluateAll(nodes => nodes.map(node => node.getAttribute('href')));
  expect(links).toEqual(articlesFor(translatedTag, primary).slice(0, 24).map(article => article.url));
});

test('unavailable author language explicitly links the same author in English', async ({ page }) => {
  test.skip(!emptyTag, 'Every configured language has a publication by this author');
  await page.goto(authorPath(emptyTag, primary), { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.author-profile h1')).toHaveText(primary);
  await expect(page.locator('.author-profile .empty-state')).toContainText(locales[emptyTag].ui.author_no_articles);
  await expect(headingLinks(page)).toHaveCount(0);
  await page.locator('.author-profile .empty-state').getByRole('link', { name: locales[emptyTag].ui.author_read_english, exact: true }).click();
  await expect(page).toHaveURL(new URL(authorPath('en', primary), page.url()).href);
});

test('author pagination keeps all articles and language changes return to the same author', async ({ page }) => {
  expect(articlesFor('en', primary).length).toBeGreaterThan(24);
  const base = authorPath('en', primary);
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.locator('.author-profile a[rel=next]').click();
  await expect(page).toHaveURL(new URL(`${base}page/2/`, page.url()).href);
  await expect(page.locator('meta[name=robots]')).toHaveAttribute('content', 'noindex,follow');
  await expect(page.locator('link[hreflang]')).toHaveCount(0);
  const links = await headingLinks(page).evaluateAll(nodes => nodes.map(node => node.getAttribute('href')));
  expect(links).toEqual(articlesFor('en', primary).slice(24, 48).map(article => article.url));
  const targetTag = emptyTag || translatedTag || 'af';
  await page.locator('[data-language-select]').selectOption(authorPath(targetTag, primary));
  await expect(page).toHaveURL(new URL(authorPath(targetTag, primary), page.url()).href);
  await expect(page.locator('.author-profile h1')).toHaveText(primary);
  const requested = `${base}page/2/`.replace(/^\/en\//u, `/${targetTag}/`);
  const destination = articlesFor(targetTag, primary).length > 24 ? `${authorPath(targetTag, primary)}page/2/` : authorPath(targetTag, primary);
  await page.goto(requested, { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveURL(new URL(destination, page.url()).href);
});

for (const tag of ['en', 'af', 'ar', 'he', 'zh-Hans']) {
  test(`author navigation and metadata fit a narrow ${tag} interface`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 750 });
    for (const path of [`/${tag}/authors/`, authorPath(tag, primary)]) {
      await page.goto(path, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('html')).toHaveAttribute('lang', tag);
      await expect(page.locator('html')).toHaveAttribute('dir', locales[tag].meta.dir);
      const dimensions = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
      expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.width + 1);
    }
    await page.locator('.tcc-header__toggle').click();
    await page.locator('.tcc-header__menu').getByRole('link', { name: locales[tag].ui.authors, exact: true }).click();
    await expect(page).toHaveURL(new URL(`/${tag}/authors/`, page.url()).href);
    await expect(page.locator('.authors-page h1')).toHaveText(locales[tag].ui.authors);
  });
}

test.describe('Authors without JavaScript', () => {
  // Let the runner retain the original failure and own context teardown.
  test.use({ javaScriptEnabled: false });

  for (const width of [1440, 390]) {
    test(`Authors browsing and canonical reader links work without JavaScript at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      const clickVisibleLink = async link => {
        // The pinned browser cannot run Playwright's in-page retry timer with
        // JS disabled. Settle font layout, scroll explicitly, then require a
        // real visible click without entering fallback smooth-scroll retries.
        await page.waitForLoadState('load');
        await expect.poll(() => page.evaluate(() => document.fonts.status)).toBe('loaded');
        await link.scrollIntoViewIfNeeded();
        await expect(link).toBeInViewport();
        await link.click({ scroll: 'none' });
      };
      await page.goto('/en/authors/', { waitUntil: 'domcontentloaded' });
      await expect(page.locator('html')).not.toHaveClass(/\benhanced\b/u);
      await clickVisibleLink(page.locator('.author-card').getByRole('link', { name: primary, exact: true }));
      await expect(page).toHaveURL(new URL(authorPath('en', primary), page.url()).href);
      await expect(page.locator('.author-profile h1')).toHaveText(primary);
      await clickVisibleLink(headingLinks(page).first());
      await expect(page).toHaveURL(new URL(articlesFor('en', primary)[0].url, page.url()).href);
      await expect(page.locator('.prose article')).toHaveAttribute('data-article-id', articlesFor('en', primary)[0].id);
      await page.goBack({ waitUntil: 'domcontentloaded' });
      await expect(page.locator('.author-profile h1')).toHaveText(primary);
      await page.goBack({ waitUntil: 'domcontentloaded' });
      await expect(page.locator('.authors-page h1')).toHaveText(locales.en.ui.authors);
    });
  }
});

for (const worker of [true, false]) {
  test(`search credits link each original contributor using ${worker ? 'the worker' : 'the browser fallback'}`, async ({ page }) => {
    if (!worker) await page.addInitScript(() => {
      window.Worker = class { constructor() { throw new Error('Exercise the ordinary search fallback'); } };
    });
    for (const tag of ['en', ...(translatedTag ? [translatedTag] : [])]) {
      await page.goto(`/${tag}/search/?q=${encodeURIComponent(primary)}`, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('.search-result').first()).toBeVisible();
      const first = page.locator('.search-result').filter({ has: page.locator(`small a[href="${authorPath(tag, primary)}"]`) }).first();
      await expect(first).toBeVisible();
      const articleURL = await first.locator('h2 a').getAttribute('href');
      const record = indexes[tag].find(article => article.url === articleURL);
      const original = source.find(article => article.id === record.id);
      const names = [...new Set(original.byline.authors.map(author => canonicalName(author.name)))];
      const credits = await first.locator('small .author-link').evaluateAll(nodes => nodes.map(node => ({ name: node.textContent, url: node.getAttribute('href') })));
      expect(new Set(credits.map(credit => credit.url))).toEqual(new Set(names.map(name => authorPath(tag, name))));
      expect(credits).toHaveLength(names.length);
      for (const credit of credits) expect(credit.url).toBe(authorPath(tag, canonicalName(credit.name)));
      expect(await first.locator('small').textContent()).toContain(record.author);
      await first.locator(`small a[href="${authorPath(tag, primary)}"]`).click();
      await expect(page).toHaveURL(new URL(authorPath(tag, primary), page.url()).href);
      await expect(page.locator('.author-profile h1')).toHaveText(primary);
    }
  });
}
