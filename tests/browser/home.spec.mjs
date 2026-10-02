import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import { HOME_SLOT_MS, selectHome } from '../../assets/home-selection.js';

const NOW = Date.parse('2026-10-01T12:35:00Z');
const homeDataPattern = /\/home-data\.[^/]+\.json(?:\.gz)?$/;
const routes = JSON.parse(fs.readFileSync('dist/routes.json', 'utf8'));
const articlesByLocale = new Map();
function articleMetadata(locale) {
  if (!articlesByLocale.has(locale)) {
    articlesByLocale.set(locale, JSON.parse(fs.readFileSync(`dist/${locale}/search-index.json`, 'utf8')));
  }
  return articlesByLocale.get(locale);
}
const issuePath = (locale, id) => `/${locale}/issues/${routes.issues[locale][id].slug}/`;

async function readHomeData(page) {
  const config = JSON.parse(await page.locator('#page-config').textContent());
  expect(config.homeData).toMatch(homeDataPattern);
  const response = await page.request.get(new URL(config.homeData, page.url()).href);
  expect(response.ok()).toBe(true);
  const data = await response.json();
  expect(data.schema).toBe(1);
  return data;
}

async function archiveIds(page) {
  return page.locator('[data-home-archive] > [data-home-article-id]').evaluateAll(elements =>
    elements.map(element => element.dataset.homeArticleId));
}

async function latestLinks(page) {
  return page.locator('[data-home-latest] .article-card h3 a').evaluateAll(elements =>
    elements.map(element => element.getAttribute('href')));
}

async function snapshot(page) {
  return {
    featureId: await page.locator('[data-home-feature]').getAttribute('data-feature-id'),
    issueId: await page.locator('.featured-issue').getAttribute('data-issue-id'),
    archiveIds: await archiveIds(page),
    categoryIds: await page.locator('[data-home-categories]').getAttribute('data-selection'),
    latestLinks: await latestLinks(page),
  };
}

async function expectSelection(page, data, now) {
  const selected = selectHome(data, now);
  await expect(page.locator('html')).toHaveAttribute('data-home-slot', String(selected.slot));
  if (selected.featureId !== null) {
    const feature = data.features.find(row => row.id === selected.featureId);
    await expect(page.locator('[data-home-feature]')).toHaveAttribute('data-feature-id', feature.id);
    await expect(page.locator('.featured-issue')).toHaveAttribute('data-issue-id', feature.id);
    await expect(page.locator('.featured-issue .text-link')).toHaveAttribute('href', issuePath(data.locale, feature.id));
    if (feature.articleId) {
      const article = articleMetadata(data.locale).find(row => row.id === feature.articleId);
      expect(article, `Missing metadata for editor ${feature.articleId}`).toBeTruthy();
      expect(article.issue_id).toBe(feature.id);
      await expect(page.locator('.home-lead__article article h2 a')).toHaveAttribute('href', article.url);
      await expect(page.locator('.home-lead__article article h2 a')).toHaveText(article.title);
      await expect(page.locator('.home-lead__article .empty-state')).toHaveCount(0);
    } else {
      await expect(page.locator('.home-lead__article article')).toHaveCount(0);
      await expect(page.locator('.home-lead__article .empty-state')).toBeVisible();
    }
  }
  await expect.poll(() => archiveIds(page)).toEqual(selected.archiveIds);
  for (const id of selected.archiveIds) {
    const article = articleMetadata(data.locale).find(row => row.id === id);
    expect(article, `Missing metadata for archive article ${id}`).toBeTruthy();
    const title = page.locator(`[data-home-article-id="${id}"] h3 a`);
    await expect(title).toHaveAttribute('href', article.url);
    await expect(title).toHaveText(article.title);
  }
  await expect(page.locator('[data-home-categories]')).toHaveAttribute('data-selection', selected.categoryIds.join(','));
  await expect(page.locator('[data-home-categories] .category-tile')).toHaveCount(selected.categoryIds.length);
  return selected;
}

async function openHome(page, locale = 'en', now = NOW) {
  await page.clock.setFixedTime(now);
  await page.goto(`/${locale}/`);
  const data = await readHomeData(page);
  await expectSelection(page, data, now);
  return data;
}

async function noOverflow(page) {
  const size = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(size.content, JSON.stringify(size)).toBeLessThanOrEqual(size.viewport + 1);
}

test('one global selection survives different browser locales, time zones, and denied storage', async ({ browser }) => {
  const contexts = [
    await browser.newContext({ locale: 'en-US', timezoneId: 'America/Los_Angeles' }),
    await browser.newContext({ locale: 'ar-SA', timezoneId: 'Asia/Dubai' }),
  ];
  try {
    await contexts[0].addInitScript(() => {
      localStorage.setItem('remnant-language', 'fr');
      localStorage.setItem('remnant-theme', 'dark');
      localStorage.setItem('remnant-home-history', 'different visitor');
    });
    await contexts[1].addInitScript(() => {
      for (const name of ['localStorage', 'sessionStorage']) {
        Object.defineProperty(window, name, { get() { throw new Error('Storage denied'); } });
      }
    });
    const pages = await Promise.all(contexts.map(context => context.newPage()));
    await Promise.all(pages.map(page => openHome(page)));
    expect(await snapshot(pages[0])).toEqual(await snapshot(pages[1]));
    await expect(pages[0].locator('html')).toHaveAttribute('lang', 'en');
    await expect(pages[1].locator('html')).toHaveAttribute('lang', 'en');
  } finally {
    await Promise.all(contexts.map(context => context.close()));
  }
});

test('same-slot reloads preserve the chosen issue, editorial, archive, categories, and latest six', async ({ page }) => {
  const data = await openHome(page);
  const first = await snapshot(page);
  for (let reload = 0; reload < 2; reload += 1) {
    await page.reload();
    await expectSelection(page, data, NOW);
    expect(await snapshot(page)).toEqual(first);
  }
  expect(first.latestLinks).toHaveLength(6);
  expect(first.latestLinks).toEqual(articleMetadata('en').slice(0, 6).map(article => article.url));
});

test('the UTC boundary timer rotates all islands, keeps editorial paired, and preserves latest six', async ({ page }) => {
  const boundary = Date.parse('2026-10-02T00:00:00Z');
  await page.clock.install({ time: boundary - 60_000 });
  await page.goto('/en/');
  const data = await readHomeData(page);
  await page.clock.pauseAt(boundary - 1_000);
  const before = await expectSelection(page, data, boundary - 1_000);
  const latest = await latestLinks(page);
  await page.clock.runFor(999);
  await expectSelection(page, data, boundary - 1);
  // Enhancement gives timers a 20ms boundary grace to avoid fractional clocks.
  await page.clock.runFor(22);
  const after = await expectSelection(page, data, boundary + 21);
  expect(after.featureId).not.toBe(before.featureId);
  expect(after.archiveIds).not.toEqual(before.archiveIds);
  expect(after.archiveIds.every(id => !before.archiveIds.includes(id))).toBe(true);
  expect(after.categoryIds).not.toEqual(before.categoryIds);
  expect(await latestLinks(page)).toEqual(latest);
});

test('three archive cards are visible together before unchanged latest six and category tiles', async ({ page }) => {
  const data = await openHome(page);
  await expect(page.locator('[data-home-archive] .article-card')).toHaveCount(3);
  for (const card of await page.locator('[data-home-archive] .article-card').all()) await expect(card).toBeVisible();
  await expect(page.locator('[data-home-latest] .article-card')).toHaveCount(6);
  await expect(page.locator('[data-slide-next], [data-slide-prev], [data-slide-play]')).toHaveCount(0);
  expect(await page.evaluate(() => {
    const feature = document.querySelector('[data-home-feature]');
    const archive = document.querySelector('[data-home-archive]');
    const latest = document.querySelector('[data-home-latest]');
    const categories = document.querySelector('[data-home-categories]');
    const before = (first, second) => !!(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
    return before(feature, archive) && before(archive, latest) && before(latest, categories);
  })).toBe(true);
  expect((await archiveIds(page)).every(id => !data.latestIds.includes(id))).toBe(true);
  await noOverflow(page);
});

test('navigation arrows use consistent decorative SVG icons rather than font glyphs', async ({ page }) => {
  await openHome(page);
  const arrows = page.locator('.text-link, .card-arrow, .tile-arrow, .quick-search button');
  expect(await arrows.count()).toBeGreaterThan(10);
  for (const arrow of await arrows.all()) {
    await expect(arrow.locator('svg.nav-icon')).toHaveCount(1);
    await expect(arrow.locator('svg.nav-icon')).toHaveAttribute('aria-hidden', 'true');
    await expect(arrow.locator('svg.nav-icon')).toHaveAttribute('focusable', 'false');
    expect(await arrow.textContent()).not.toContain('↗');
  }
});

for (const island of [
  { name: 'editorial and issue', selector: '[data-home-feature]', target: '.home-lead__article h2 a' },
  { name: 'archive cards', selector: '[data-home-archive]', target: '[data-home-archive] h3 a' },
  { name: 'category tiles', selector: '[data-home-categories]', target: '[data-home-categories] a' },
]) {
  test(`focused ${island.name} stay intact at rotation and catch up after focus leaves`, async ({ page }) => {
    const data = await openHome(page);
    const oldSelection = await page.locator(island.selector).getAttribute('data-selection');
    const focused = page.locator(island.target).first();
    await focused.focus();
    const href = await focused.getAttribute('href');
    await page.clock.setFixedTime(NOW + HOME_SLOT_MS);
    await page.evaluate(() => window.dispatchEvent(new Event('pageshow')));
    await expect(page.locator('html')).toHaveAttribute('data-home-slot', String(Math.floor((NOW + HOME_SLOT_MS) / HOME_SLOT_MS)));
    await expect(page.locator(island.selector)).toHaveAttribute('data-selection', oldSelection);
    expect(await page.evaluate(() => document.activeElement.getAttribute('href'))).toBe(href);
    await page.locator('#home-q').focus();
    await expectSelection(page, data, NOW + HOME_SLOT_MS);
    await expect(page.locator(island.selector)).not.toHaveAttribute('data-selection', oldSelection);
  });
}

test('restored and backgrounded pages catch up to the current slot after long sleep', async ({ page }) => {
  const data = await openHome(page);
  const latest = await latestLinks(page);
  await page.clock.setFixedTime(NOW + 37 * HOME_SLOT_MS);
  await page.evaluate(() => window.dispatchEvent(new Event('pageshow')));
  await expectSelection(page, data, NOW + 37 * HOME_SLOT_MS);

  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  const oldSlot = await page.locator('html').getAttribute('data-home-slot');
  await page.clock.setFixedTime(NOW + 103 * HOME_SLOT_MS);
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await expect(page.locator('html')).toHaveAttribute('data-home-slot', oldSlot);
  await page.evaluate(() => {
    delete document.hidden;
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expectSelection(page, data, NOW + 103 * HOME_SLOT_MS);
  expect(await latestLinks(page)).toEqual(latest);
});

test('pause preserves all content through time and lifecycle changes; resume rejoins the shared slot', async ({ page }) => {
  const data = await openHome(page);
  const labels = JSON.parse(await page.locator('#page-config').textContent()).homeUi;
  const controls = page.locator('[data-home-controls]');
  const button = page.locator('[data-home-pause]');
  const initial = await snapshot(page);
  await expect(controls).toBeVisible();
  await expect(button).toHaveText(labels.pause);
  await expect(button).toHaveAttribute('aria-pressed', 'false');
  await button.click();
  await expect(button).toHaveText(labels.resume);
  await expect(button).toHaveAttribute('aria-pressed', 'true');
  await expect(button).toBeFocused();

  const later = NOW + 47 * HOME_SLOT_MS;
  await page.clock.setFixedTime(later);
  await page.evaluate(() => {
    window.dispatchEvent(new Event('pagehide'));
    window.dispatchEvent(new Event('pageshow'));
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.locator('#home-q').focus();
  await expect(page.locator('html')).toHaveAttribute('data-home-slot', String(Math.floor(NOW / HOME_SLOT_MS)));
  expect(await snapshot(page)).toEqual(initial);

  await button.click();
  await expect(button).toHaveText(labels.pause);
  await expect(button).toHaveAttribute('aria-pressed', 'false');
  await expect(button).toBeFocused();
  await expectSelection(page, data, later);
  expect(await latestLinks(page)).toEqual(initial.latestLinks);
});

test('pause cancels the boundary timer until explicitly resumed', async ({ page }) => {
  const boundary = Date.parse('2026-10-02T00:00:00Z');
  await page.clock.install({ time: boundary - 60_000 });
  await page.goto('/en/');
  const data = await readHomeData(page);
  await expectSelection(page, data, boundary - 60_000);
  await page.locator('[data-home-pause]').click();
  const initial = await snapshot(page);
  await page.clock.pauseAt(boundary - 1_000);
  await page.clock.runFor(HOME_SLOT_MS * 3 + 1_021);
  expect(await snapshot(page)).toEqual(initial);
  await expect(page.locator('html')).toHaveAttribute('data-home-slot', String(Math.floor((boundary - 60_000) / HOME_SLOT_MS)));
  await page.clock.resume();
  await page.locator('[data-home-pause]').click();
  await expectSelection(page, data, boundary + HOME_SLOT_MS * 3 + 21);
});

test('compressed-data failure falls back to the plain digest JSON', async ({ page }) => {
  const requests = [];
  page.on('request', request => { if (homeDataPattern.test(request.url())) requests.push(request.url()); });
  await page.route(/\/home-data\.[^/]+\.json\.gz$/, route => route.abort('failed'));
  await openHome(page);
  expect(requests.some(url => url.endsWith('.json.gz'))).toBe(true);
  expect(requests.some(url => url.endsWith('.json'))).toBe(true);
});

test('failed preview fetch preserves a useful static homepage with working issue navigation', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route(homeDataPattern, route => route.abort('failed'));
  await page.goto('/en/');
  await page.waitForLoadState('networkidle');
  await expect(page.locator('html')).not.toHaveAttribute('data-home-slot', /.+/);
  await expect(page.locator('[data-home-controls]')).toBeHidden();
  await expect(page.locator('.home-lead__article article')).toBeVisible();
  await expect(page.locator('[data-home-archive] .article-card')).toHaveCount(3);
  await expect(page.locator('[data-home-latest] .article-card')).toHaveCount(6);
  await expect(page.locator('[data-home-categories] .category-tile')).toHaveCount(8);
  const issueId = await page.locator('.featured-issue').getAttribute('data-issue-id');
  const issueUrl = new URL(issuePath('en', issueId), page.url()).href;
  await page.locator('.featured-issue .text-link').click();
  await expect(page).toHaveURL(issueUrl);
  await expect(page.locator('.issue-contents > li')).not.toHaveCount(0);
  expect(errors).toEqual([]);
});

test('homepage browsing remains useful with JavaScript disabled', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const page = await context.newPage();
    await page.goto('/en/');
    await expect(page.locator('.home-lead__article article')).toBeVisible();
    await expect(page.locator('[data-home-archive] .article-card')).toHaveCount(3);
    await expect(page.locator('[data-home-latest] .article-card')).toHaveCount(6);
    await expect(page.locator('[data-home-categories] .category-tile')).toHaveCount(8);
    await expect(page.locator('noscript .nojs-languages')).toBeVisible();
    await expect(page.locator('[data-home-controls]')).toBeHidden();
    const firstArticle = page.locator('[data-home-archive] h3 a').first();
    const destination = await firstArticle.getAttribute('href');
    await firstArticle.click();
    await expect(page).toHaveURL(new RegExp(`${destination}$`));
    await expect(page.locator('.prose article')).toBeVisible();
    await page.goto('/ar/');
    await expect(page.locator('.featured-issue')).toBeVisible();
    // Translations arrive independently. Validate the static selected issue's
    // actual publication data instead of assuming Arabic is permanently empty.
    const data = await readHomeData(page);
    const featureId = await page.locator('.featured-issue').getAttribute('data-issue-id');
    const feature = data.features.find(row => row.id === featureId);
    expect(feature, `Missing static featured issue ${featureId}`).toBeTruthy();
    if (feature.articleId) {
      const article = articleMetadata('ar').find(row => row.id === feature.articleId);
      expect(article, `Missing Arabic editor ${feature.articleId}`).toBeTruthy();
      expect(article.issue_id).toBe(featureId);
      await expect(page.locator('.home-lead__article article h2 a')).toHaveAttribute('href', article.url);
      await expect(page.locator('.home-lead__article article h2 a')).toHaveText(article.title);
      await expect(page.locator('.home-lead__article .empty-state')).toHaveCount(0);
      const articleUrl = new URL(article.url, page.url()).href;
      await page.locator('.home-lead__article article h2 a').click();
      await expect(page).toHaveURL(articleUrl);
      await expect(page.locator('.prose article')).toBeVisible();
    } else {
      await expect(page.locator('.home-lead__article article')).toHaveCount(0);
      await expect(page.locator('.home-lead__article .empty-state')).toBeVisible();
    }
  } finally {
    await context.close();
  }
});

for (const locale of [
  { tag: 'en', dir: 'ltr' },
  { tag: 'af', dir: 'ltr' },
  { tag: 'ar', dir: 'rtl' },
]) {
  test(`320px ${locale.tag} homepage handles its archive pool without horizontal overflow`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 740 });
    const data = await openHome(page, locale.tag);
    await expect(page.locator('html')).toHaveAttribute('dir', locale.dir);
    const labels = JSON.parse(await page.locator('#page-config').textContent()).homeUi;
    await expect(page.locator('[data-home-pause]')).toHaveText(labels.pause);
    const expectedCount = Math.min(3, data.articles.length);
    await expect(page.locator('[data-home-archive] .article-card')).toHaveCount(expectedCount);
    for (const card of await page.locator('[data-home-archive] .article-card').all()) await expect(card).toBeVisible();
    await noOverflow(page);
    const oldIds = await archiveIds(page);
    const latest = await latestLinks(page);
    await page.clock.setFixedTime(NOW + HOME_SLOT_MS);
    await page.evaluate(() => window.dispatchEvent(new Event('pageshow')));
    await expectSelection(page, data, NOW + HOME_SLOT_MS);
    await noOverflow(page);
    expect(await latestLinks(page)).toEqual(latest);
    if (data.articles.length > 3 && data.articles.length <= 6) {
      expect(new Set([...oldIds, ...await archiveIds(page)]).size).toBe(data.articles.length);
    }
    if (!data.articles.length) {
      await expect(page.locator('[data-home-latest]')).toHaveCount(0);
      await expect(page.locator('.home-lead__article .empty-state')).toBeVisible();
    }
  });
}

for (const locale of ['en', 'id', 'sv', 'ar']) {
  test(`every available issue date fits the narrow featured sidebar: ${locale}`, async ({ page }) => {
    const data = await openHome(page, locale);
    await page.locator('[data-home-pause]').click();
    for (const width of [320, 390]) {
      await page.setViewportSize({ width, height: 844 });
      const overflow = await page.evaluate(features => {
        const target = document.querySelector('[data-home-feature]');
        const problems = [];
        for (const feature of features) {
          target.innerHTML = feature.html;
          const foot = target.querySelector('.featured-issue__foot');
          const box = foot.getBoundingClientRect();
          if (box.left < -1 || box.right > innerWidth + 1 || foot.scrollWidth > foot.clientWidth + 1) problems.push(feature.id);
        }
        return problems;
      }, data.features);
      expect(overflow, `${locale} at ${width}px`).toEqual([]);
    }
  });
}
