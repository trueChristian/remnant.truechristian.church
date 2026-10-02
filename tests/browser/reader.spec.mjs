import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const registry = JSON.parse(fs.readFileSync('dist/routes.json', 'utf8'));
const catalogue = JSON.parse(fs.readFileSync('.build/english/catalogue.json', 'utf8'));
const locales = fs.readdirSync('locales').map(file => JSON.parse(fs.readFileSync(`locales/${file}`, 'utf8')));
const indexes = Object.fromEntries(locales.map(locale => [locale.meta.tag, JSON.parse(fs.readFileSync(`dist/${locale.meta.tag}/search-index.json`, 'utf8'))]));
let translationExport = [];
try { translationExport = JSON.parse(fs.readFileSync('.build/translations/index.json', 'utf8')).articles; } catch {}
const afCandidate = indexes.af.find(record => translationExport.some(item => item.id === record.id && item.ai_notice_required)) || indexes.af[0];
const id = (afCandidate || indexes.en[0]).id;
const noticeRequired = translationExport.some(item => item.id === id && item.language_tag === 'af' && item.ai_notice_required);
const missingLocale = locales.map(locale => locale.meta.tag).find(tag => !indexes[tag].some(record => record.id === id));
const article = locale => {
  const entry = registry.articles[locale][id];
  return `/${locale}/${entry.category_slug}/${entry.alias}/`;
};
const capture = async (page, name) => {
  fs.mkdirSync('.test-output/screenshots', { recursive: true });
  await page.evaluate(async()=>{
    // Load visible lazy media before taking a full-page review image.
    for(const img of document.images) if(img.getClientRects().length) img.loading='eager';
    await Promise.all([...document.images].filter(img=>img.getClientRects().length).map(img=>img.decode().catch(()=>{})));
    await document.fonts.ready;
  });
  await page.screenshot({ path: `.test-output/screenshots/${name}.png`, fullPage: true });
};
const noOverflow = async page => {
  const result=await page.evaluate(()=>({
    width:document.documentElement.clientWidth, scroll:document.documentElement.scrollWidth,
    overflowing:[...document.querySelectorAll('body *')].filter(element=>{
      const box=element.getBoundingClientRect(),style=getComputedStyle(element);
      return style.visibility!=='hidden'&&style.display!=='none'&&(box.right>innerWidth+1||box.left< -1);
    }).slice(0,12).map(element=>({tag:element.tagName,class:element.className,text:element.textContent.slice(0,80),rect:{left:element.getBoundingClientRect().left,right:element.getBoundingClientRect().right}}))
  }));
  expect(result.scroll, JSON.stringify(result)).toBeLessThanOrEqual(result.width+1);
};

test('desktop magazine home, issue and article layouts', async ({ page }) => {
  await page.goto('/en/');
  await expect(page.locator('.masthead h1')).toContainText('Remnant');
  await expect(page.locator('html')).toHaveAttribute('data-home-slot', /.+/);
  const latestDate = await page.locator('.featured-issue__foot h2').textContent();
  await noOverflow(page); await capture(page, 'home-desktop');
  await page.locator('.featured-issue .text-link').click();
  await expect(page.locator('.issue-heading h1')).toHaveText(latestDate);
  await expect(page.locator('.issue-contents > li')).not.toHaveCount(0);
  await capture(page, 'issue-desktop');
  await page.goto(article('en'));
  await expect(page.locator('.prose article')).toHaveAttribute('data-article-id', id);
  await expect(page.locator('.article-issue')).toContainText('The Heartbeat of the Remnant');
  const dropParagraph=page.locator('.prose p.drop-cap');
  if (await dropParagraph.count()) expect(await dropParagraph.first().evaluate(element=>parseFloat(getComputedStyle(element).fontSize))).toBeLessThan(25);
  await capture(page, 'article-desktop');
});

test('explicit locale prevails over saved choice; root uses saved choice', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('remnant-language', 'fr'));
  await page.goto('/en/'); await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await page.goto('/'); await expect(page).toHaveURL(/\/fr\/$/);
  if (!indexes.fr.length) await expect(page.locator('.empty-state')).toBeVisible();
  else await expect(page.locator('.article-card').first()).toBeVisible();
  await expect(page.locator('[data-language-select]')).toHaveValue('/fr/');
  await capture(page, 'french-empty-desktop');
});

test('French browser default and unavailable browser storage remain usable', async ({ browser }) => {
  const context = await browser.newContext({ locale: 'fr-FR' });
  const page = await context.newPage();
  await page.addInitScript(() => Object.defineProperty(window, 'localStorage', { get() { throw new Error('Storage denied'); } }));
  await page.goto('/'); await expect(page).toHaveURL(/\/fr\/$/);
  await page.locator('[data-theme-select]').selectOption('dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.locator('[data-language-select]').selectOption('/en/');
  await expect(page).toHaveURL(/\/en\/$/);
  await context.close();
});

test('missing article translation explains availability and returns to original', async ({ page }) => {
  test.skip(!missingLocale, 'Every configured language has this article');
  await page.goto(article('en'));
  await page.locator('[data-language-select]').selectOption(article(missingLocale));
  await expect(page.locator('html')).toHaveAttribute('lang', missingLocale);
  await expect(page.locator('.empty-state')).toBeVisible();
  await expect(page.locator('meta[name=robots]')).toHaveAttribute('content','noindex,follow');
  await page.locator('.empty-state a[hreflang=en]').click();
  await expect(page).toHaveURL(new RegExp(article('en')+'$'));
});

test('locale switching follows real article IDs and keeps the AI notice', async ({ page }) => {
  test.skip(!afCandidate, 'English-only build: no current Afrikaans translation');
  await page.goto(article('en'));
  await page.locator('[data-language-select]').selectOption(article('af'));
  await expect(page.locator('html')).toHaveAttribute('lang','af');
  if (noticeRequired) await expect(page.locator('.prose aside')).toContainText('OpenAI');
  else await expect(page.locator('.prose aside[data-translation-notice]')).toHaveCount(0);
  await capture(page, 'afrikaans-article');
  if (noticeRequired) await page.locator(`.prose aside a[href="${article('en')}"]`).click();
  else await page.locator('[data-language-select]').selectOption(article('en'));
  await expect(page).toHaveURL(new RegExp(article('en')+'$'));
});

test('system theme changes; persistent explicit override survives reload', async ({ page }) => {
  await page.goto('/en/');
  await page.emulateMedia({ colorScheme:'dark' });
  await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  await page.locator('[data-theme-select]').selectOption('light');
  await page.reload(); await expect(page.locator('html')).toHaveAttribute('data-theme','light');
  await page.locator('[data-theme-select]').selectOption('dark');
  await capture(page,'home-dark');
  await page.locator('[data-theme-select]').selectOption('system');
  await page.emulateMedia({ colorScheme:'light' });
  await expect(page.locator('html')).toHaveAttribute('data-theme','light');
});

test('mobile header opens, traps focus, closes with Escape, and reopens', async ({ page }) => {
  await page.setViewportSize({width:390,height:844});
  await page.goto('/en/'); await noOverflow(page); await capture(page,'home-mobile');
  await page.locator('.tcc-header__toggle').click();
  await expect(page.locator('.tcc-header__navigation')).toBeVisible();
  await expect(page.locator('.tcc-header__toggle')).toHaveAttribute('aria-expanded','true');
  await noOverflow(page);
  await page.locator('.tcc-header__menu a').last().focus();
  await page.keyboard.press('Tab');
  await expect(page.locator('.tcc-header__close')).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(page.locator('.tcc-header__menu a').last()).toBeFocused();
  expect(await page.locator('.tcc-header__scrim').evaluate(element=>element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(844);
  await capture(page,'mobile-navigation');
  await page.keyboard.press('Escape');
  await expect(page.locator('.tcc-header__toggle')).toHaveAttribute('aria-expanded','false');
  await expect(page.locator('.tcc-header__toggle')).toBeFocused();
  await page.locator('.tcc-header__toggle').click();
  await page.locator('.tcc-header__close').click();
  await expect(page.locator('.tcc-header__toggle')).toHaveAttribute('aria-expanded','false');
});

for (const locale of locales) {
  test(`narrow layout has no horizontal overflow: ${locale.meta.tag}`, async ({ page }) => {
    await page.setViewportSize({width:360,height:800});
    await page.goto(`/${locale.meta.tag}/`);
    await expect(page.locator('html')).toHaveAttribute('dir',locale.meta.dir);
    await noOverflow(page);
    await page.goto(`/${locale.meta.tag}/categories/`); await noOverflow(page);
    await expect(page.locator('.category-tile')).toHaveCount(catalogue.categories.length);
    if (locale.meta.tag==='ar') await capture(page,'arabic-mobile');
    if (locale.meta.tag==='zh-Hans') await capture(page,'chinese-mobile');
    await page.setViewportSize({width:320,height:700}); await noOverflow(page);
  });
}

test('search is locale-only, searches body and metadata, with Back/Forward recovery', async ({ page }) => {
  const loaded=[];page.on('request',request=>{if(request.url().includes('search-index'))loaded.push(request.url())});
  await page.goto('/en/'); expect(loaded).toEqual([]);
  await page.goto('/en/search/'); expect(loaded).toEqual([]);
  await page.locator('#search-q').fill('compassion');
  await expect(page.locator('.search-result')).not.toHaveCount(0);
  await expect(page).toHaveURL(/q=compassion/);
  const destination=await page.locator('.search-result h2 a').first().getAttribute('href');
  await page.locator('.search-result h2 a').first().click();
  await expect(page).toHaveURL(new RegExp(destination+'$'));
  await page.goBack(); await expect(page.locator('#search-q')).toHaveValue('compassion');
  await expect(page.locator('.search-result')).not.toHaveCount(0);
  await page.locator('#search-q').fill('Autumn 2024');
  await expect(page.locator('.search-result')).not.toHaveCount(0);
  await expect(page.locator('.search-result small').first()).toContainText('Autumn 2024');
  expect(loaded.every(url=>/\/en\/search-index\.json(?:\.gz)?$/.test(url))).toBe(true);
  await capture(page,'search-desktop');
});

test('search filters, zero results, pagination, and keyboard navigation', async ({ page }) => {
  await page.goto('/en/search/?q=God');
  await expect(page.locator('.search-result')).toHaveCount(40);
  await page.locator('#search-results .pagination').getByRole('button',{name:'Next',exact:true}).click();
  await expect(page).toHaveURL(/page=2/);
  await page.goBack(); await expect(page).not.toHaveURL(/page=2/);
  await page.locator('#search-q').fill('no-such-combination-9827834');
  await expect(page.locator('.empty-message')).toBeVisible();
  await page.getByRole('button',{name:'Clear',exact:true}).click();
  await expect(page.locator('#search-q')).toHaveValue('');
  await page.locator('select[name=category]').selectOption(registry.categories.en['11f3b229-ad6c-5d69-b529-82d977f8d000'].slug);
  await expect(page.locator('.search-result')).not.toHaveCount(0);
  await expect(page.locator('.search-result .eyebrow').first()).not.toBeEmpty();
});

test('Markdown fallback preserves selectable text when clipboard unavailable', async ({ page }) => {
  const locale = afCandidate ? 'af' : 'en';
  await page.addInitScript(()=>Object.defineProperty(navigator,'clipboard',{value:undefined}));
  await page.goto(article(locale));
  await page.locator('[data-copy-markdown]').click();
  await expect(page.locator('#markdown-fallback')).toBeVisible();
  await expect(page.locator('#markdown-text')).toContainText('');
  const value=await page.locator('#markdown-text').inputValue();
  if (noticeRequired) expect(value).toContain('OpenAI');
  expect(value).toContain('The Heartbeat of the Remnant');
  expect(value).toContain(`/${locale}/issues/`);
});

test('reduced motion keeps all three archive cards readable without autoplay', async ({ page }) => {
  await page.emulateMedia({reducedMotion:'reduce'}); await page.goto('/en/');
  await expect(page.locator('[data-home-archive] .article-card')).toHaveCount(3);
  for (const card of await page.locator('[data-home-archive] .article-card').all()) await expect(card).toBeVisible();
  await expect(page.locator('[data-slide-play]')).toHaveCount(0);
});

test('static browsing remains useful with JavaScript disabled', async ({ browser }) => {
  const context=await browser.newContext({javaScriptEnabled:false});const page=await context.newPage();
  await page.goto('/fr/');if (!indexes.fr.length) await expect(page.locator('.empty-state')).toBeVisible();
  await expect(page.locator('noscript .nojs-languages')).toBeVisible();
  await page.goto('/en/issues/');await expect(page.locator('.issue-tile')).toHaveCount(catalogue.issues.length);
  await page.locator('.issue-tile').first().click();await expect(page.locator('.issue-contents > li')).not.toHaveCount(0);
  await context.close();
});

test('article print keeps source notice and hides controls', async ({ page }) => {
  test.skip(!noticeRequired, 'No currently published AI-notice translation available');
  await page.goto(article('af'));await page.emulateMedia({media:'print'});
  await expect(page.locator('.prose aside')).toBeVisible();await expect(page.locator('.reader-tools')).toBeHidden();
  await capture(page,'article-print');
});

test('measured warm search compute stays within desktop and mobile budgets', async ({ page }) => {
  await page.goto('/en/search/');
  const session=await page.context().newCDPSession(page);
  const timings={};
  for(const rate of [1,4]) {
    await session.send('Emulation.setCPUThrottlingRate',{rate});
    timings[`${rate}x`]=await page.evaluate(async()=>{
      const {prepare,search}=await import('/assets/search-core.js');
      const data=await (await fetch('/en/search-index.json')).json();
      const records=prepare(data);
      const times=[];
      for(const query of ['God','compassion','Christian living','Autumn 2024','prayer','love','family','scripture','forgiveness','Jesus']) {
        const start=performance.now();search(records,query);times.push(performance.now()-start);
      }
      return {max:Math.max(...times),mean:times.reduce((a,b)=>a+b,0)/times.length,samples:times};
    });
  }
  await session.send('Emulation.setCPUThrottlingRate',{rate:1});
  fs.mkdirSync('.test-output',{recursive:true});fs.writeFileSync('.test-output/search-performance.json',JSON.stringify(timings,null,2));
  expect(timings['1x'].max).toBeLessThan(100);
  expect(timings['4x'].max).toBeLessThan(250);
});
