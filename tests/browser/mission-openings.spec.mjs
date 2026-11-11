import { test, expect } from '@playwright/test';
import fs from 'node:fs';

const registry = JSON.parse(fs.readFileSync('dist/routes.json', 'utf8'));
const ids = {
  kids: '498f95c3-9cf2-4b3d-97c6-9d4d15b08972',
  foolish: '5a6259c0-5450-4502-b504-8db7b37e4cc1',
  year: '1fb1624e-5fee-4f45-9bb9-73728210ff1f',
  holy: '635b775e-3815-4c17-9c75-bdab9ea88661',
  gospel: '54d5a0ed-09dc-4e75-8447-b9e3ad2db302',
  painful: 'e2717533-f2de-48a9-94a8-feee73a69a6f',
  letters: 'ff756543-8b73-4182-a901-596bfa199152',
  vessel: '65cde85d-5f09-47af-ac75-0a3ea061d639',
};
const route = id => `/en/${registry.articles.en[id].category_slug}/${registry.articles.en[id].alias}/`;
const article = page => page.locator('.prose article');
const image = (page, id, number) => article(page).locator(`img[src*="${id}-${number}."]`);
const box = locator => locator.evaluate(node => {
  const { top, bottom, left, right, width, height } = node.getBoundingClientRect();
  return { top, bottom, left, right, width, height };
});
async function ready(page, id, { animations = true } = {}) {
  await page.goto(route(id));
  await page.evaluate(async animations => {
    await Promise.all([...document.querySelectorAll('.prose img')].map(async image => {
      const loading = image.getAttribute('loading');
      image.loading = 'eager';
      try { await image.decode(); } finally {
        if (loading === null) image.removeAttribute('loading');
        else image.setAttribute('loading', loading);
      }
    }));
    await document.fonts.ready;
    // Chromium suppresses animation callbacks when page JavaScript is disabled.
    // Image decoding and font readiness are sufficient for that static fallback.
    if (animations) await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }, animations);
}
async function safe(page, id) {
  const html = fs.readFileSync(`dist${route(id)}index.html`, 'utf8');
  const state = await article(page).evaluate((current, html) => {
    const original = new DOMParser().parseFromString(html, 'text/html').querySelector('.prose article');
    const tags = node => [...node.querySelectorAll('p, figcaption, img, li')].map(node => {
      const copy = node.cloneNode(true);
      // Scripture popovers add interaction attributes, not source content.
      for (const marker of copy.querySelectorAll('[data-scripture-id]')) {
        for (const name of ['data-scripture-ready', 'role', 'tabindex', 'aria-haspopup',
          'aria-controls', 'aria-expanded', 'aria-label']) marker.removeAttribute(name);
      }
      return copy.outerHTML;
    });
    const pictures = [...current.querySelectorAll('img')].map(image => image.getBoundingClientRect());
    const overlaps = [];
    for (const paragraph of current.querySelectorAll('p, li')) {
      const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const range = document.createRange(); range.selectNodeContents(walker.currentNode);
        for (const line of range.getClientRects()) if (line.width && line.height && pictures.some(image =>
          line.left < image.right - 1 && line.right > image.left + 1 &&
          line.top < image.bottom - 1 && line.bottom > image.top + 1)) overlaps.push(walker.currentNode.textContent);
      }
    }
    return { tags: tags(current), original: tags(original),
      breaks: current.querySelectorAll('br').length, originalBreaks: original.querySelectorAll('br').length,
      overflow: document.documentElement.scrollWidth > innerWidth, overlaps };
  }, html);
  expect(state.tags).toEqual(state.original);
  expect(state.breaks).toBe(state.originalBreaks);
  expect(state.overflow).toBe(false);
  expect(state.overlaps).toEqual([]);
}
async function centered(picture, root) {
  const a = await box(picture), b = await box(root);
  expect(Math.abs(a.left + a.right - b.left - b.right)).toBeLessThan(2);
}
async function nativeWrapped(picture, paragraph) {
  await expect(picture.locator('..')).toHaveClass(/article-figure--wrap/);
  const dimensions = await picture.evaluate(node => ({ ...node.getBoundingClientRect().toJSON(),
    naturalWidth: node.naturalWidth, naturalHeight: node.naturalHeight }));
  expect(dimensions.width).toBeCloseTo(dimensions.naturalWidth, 0);
  expect(dimensions.height).toBeCloseTo(dimensions.naturalHeight, 0);
  const text = await box(paragraph);
  expect(text.top).toBeLessThan(dimensions.bottom);
  expect(text.bottom).toBeGreaterThan(dimensions.top);
}
async function screenshot(page, info, name) {
  const path = info.outputPath(`${name}.png`);
  await article(page).screenshot({ path });
  await info.attach(name, { path, contentType: 'image/png' });
}

for (const [name, id] of Object.entries(ids).filter(([name]) => name !== 'vessel')) {
  test(`${name}: reviewed opening placement keeps native body artwork and complete content`, async ({ page }, info) => {
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await ready(page, id);
    const root = article(page), first = root.locator(':scope > p').first();
    if (name === 'kids') {
      const goats = root.locator(':scope > .article-gallery--paired');
      await expect(goats.locator('img')).toHaveCount(2);
      await centered(goats, root);
      expect((await box(goats)).bottom).toBeLessThan((await box(first)).top);
      const left = await box(image(page, id, 1)), right = await box(image(page, id, 2));
      expect(left.right).toBeLessThan(right.left);
      await nativeWrapped(image(page, id, 3), first);
    } else if (name === 'gospel') {
      await centered(image(page, id, 2), root);
      const gallery = root.locator(':scope > .article-gallery--native');
      await expect(gallery.locator('img')).toHaveCount(2);
      expect((await box(root.locator(':scope > p').nth(1))).bottom).toBeLessThan((await box(gallery)).top);
      expect((await box(gallery)).bottom).toBeLessThan((await box(root.locator(':scope > p').nth(2))).top);
      const a = await box(image(page, id, 1)), b = await box(image(page, id, 3));
      expect(a.width).toBeCloseTo(202, 0); expect(b.width).toBeCloseTo(427, 0);
      expect(a.right).toBeLessThan(b.left); expect(Math.abs(a.top - b.top)).toBeLessThan(1);
      await expect(gallery.locator('figcaption')).toHaveCount(1);
      expect((await box(image(page, id, 2))).bottom).toBeLessThan((await box(root.locator(':scope > blockquote'))).top);
    } else if (name === 'letters') {
      expect(registry.articles.en[id].alias).toBe('precious-letters-from-our-readers-24');
      await nativeWrapped(image(page, id, 1), first);
      const flower = image(page, id, 2), listing = root.locator(':scope > ul').first();
      await nativeWrapped(flower, listing);
      await expect(listing.locator('li')).toHaveCount(5);
      expect(await listing.evaluate(node => getComputedStyle(node).display)).toBe('block');
      expect((await box(first)).bottom).toBeLessThan((await box(flower)).top);
    } else {
      const globeNumber = name === 'holy' ? 2 : 1;
      const bodyNumber = name === 'holy' ? 1 : 2;
      const globe = image(page, id, globeNumber);
      await centered(globe, root);
      await expect(globe.locator('..')).toHaveClass(/article-figure--standalone/);
      await nativeWrapped(image(page, id, bodyNumber), first);
      expect((await box(globe)).bottom).toBeLessThan((await box(first)).top);
      if (name === 'painful') expect((await box(globe)).width).toBeCloseTo(150, 0);
      if (name === 'holy') expect((await box(root.locator(':scope > blockquote'))).bottom)
        .toBeLessThan((await box(image(page, id, 1))).top);
    }
    await safe(page, id); expect(errors).toEqual([]);
    await screenshot(page, info, `${name}-desktop`);
  });
}

for (const [name, id] of Object.entries(ids)) {
  test(`${name}: phone widths retain readable source content without overflow`, async ({ page }, info) => {
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 900 }); await ready(page, id);
      await expect(article(page).locator('.article-figure--wrap')).toHaveCount(0);
      await expect(article(page)).not.toHaveClass(/article-verse-continuous--active/);
      await safe(page, id);
    }
    await screenshot(page, info, `${name}-320`);
  });
}

test('continuous verse removes stanza gaps without changing the previous displayed cup sizes', async ({ page }, info) => {
  const id = ids.vessel;
  const original = fs.readFileSync(`dist${route(id)}index.html`, 'utf8');
  const baseline = await page.context().newPage();
  try {
    await baseline.route(`**${route(id)}`, route => route.fulfill({ contentType: 'text/html',
      body: original.replace(' data-reader-continuous-verse=""', '') }));
    for (const width of [1440, 768]) {
      await page.setViewportSize({ width, height: 1000 }); await baseline.setViewportSize({ width, height: 1000 });
      await ready(baseline, id); await ready(page, id);
      await expect(article(page)).toHaveClass(/article-verse-continuous--active/);
      for (const number of [1, 2, 3]) {
        const old = await box(image(baseline, id, number)), current = await box(image(page, id, number));
        expect(current.width).toBeCloseTo(old.width, 1); expect(current.height).toBeCloseTo(old.height, 1);
        expect(current.right).toBeCloseTo((await box(article(page))).right, 0);
      }
      const spacing = await article(page).evaluate(article => {
        const stanzas = [...article.querySelectorAll('p.poem')];
        return { count: stanzas.length, expected: parseFloat(getComputedStyle(stanzas[0]).marginBottom),
          gaps: stanzas.slice(1).map((stanza, index) => stanza.getBoundingClientRect().top - stanzas[index].getBoundingClientRect().bottom) };
      });
      expect(spacing.count).toBe(9);
      for (const gap of spacing.gaps) expect(gap).toBeCloseTo(spacing.expected, 0);
      await safe(page, id); await screenshot(page, info, `vessel-${width}`);
    }
  } finally { await baseline.close(); }
});

test('large text, RTL, print, and failed artwork restore safe verse and logo fallbacks', async ({ page }) => {
  await ready(page, ids.vessel);
  await expect(article(page)).toHaveClass(/article-verse-continuous--active/);
  await page.locator('.prose').evaluate(node => node.style.fontSize = '28px');
  await expect(article(page)).not.toHaveClass(/article-verse-continuous--active/);
  await safe(page, ids.vessel);
  // Restoration must work on the same page, without a resize or reload.
  await page.locator('.prose').evaluate(node => node.style.removeProperty('font-size'));
  await expect(article(page)).toHaveClass(/article-verse-continuous--active/);
  await safe(page, ids.vessel);
  await page.locator('html').evaluate(node => node.dir = 'rtl');
  await expect(article(page)).not.toHaveClass(/article-verse-continuous--active/);
  await safe(page, ids.vessel);
  await page.locator('html').evaluate(node => node.dir = 'ltr');
  await expect(article(page)).toHaveClass(/article-verse-continuous--active/);
  await safe(page, ids.vessel);
  await ready(page, ids.vessel); await page.emulateMedia({ media: 'print' });
  for (const figure of await article(page).locator('figure').all()) {
    expect(await figure.evaluate(node => getComputedStyle(node).position)).toBe('static');
  }
  await safe(page, ids.vessel); await page.emulateMedia({ media: 'screen' });
  await ready(page, ids.painful);
  const logo = image(page, ids.painful, 1);
  await expect(logo.locator('..')).toHaveClass(/article-standalone--enlarged/);
  await logo.evaluate(node => node.src = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"></svg>'));
  await expect(logo.locator('..')).not.toHaveClass(/article-standalone--enlarged/);
});

test.describe('without JavaScript', () => {
  test.use({ javaScriptEnabled: false });
  for (const [name, id] of Object.entries(ids)) {
    test(`${name}: retains full source content and visible artwork`, async ({ page }) => {
      await ready(page, id, { animations: false });
      await expect(article(page)).not.toHaveClass(/article-verse-continuous--active/);
      await safe(page, id);
    });
  }
});
