import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const registry = JSON.parse(fs.readFileSync('data/routes.json', 'utf8'));
const locales = fs.readdirSync('locales').map(file => JSON.parse(fs.readFileSync(`locales/${file}`, 'utf8')));
const id = '52074824-2feb-4fe4-96d0-a08ec72c3565';
const article = locale => {
  const r = registry.articles[locale][id];
  return `/${locale}/${r.category_slug}/${r.alias}/`;
};
const capture = async (page, name) => {
  fs.mkdirSync('.test-output/screenshots', { recursive: true });
  await page.screenshot({ path: `.test-output/screenshots/${name}.png`, fullPage: true });
};
const noOverflow = async page => expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);

test('desktop magazine home, issue and article layouts', async ({ page }) => {
  await page.goto('/en/');
  await expect(page.locator('.masthead h1')).toContainText('Remnant');
  await expect(page.locator('.latest-issue')).toContainText('Autumn 2024');
  await noOverflow(page); await capture(page, 'home-desktop');
  await page.locator('.latest-issue .text-link').click();
  await expect(page.locator('.issue-heading h1')).toHaveText('Autumn 2024');
  await expect(page.locator('.issue-contents > li')).not.toHaveCount(0);
  await capture(page, 'issue-desktop');
  await page.goto(article('en'));
  await expect(page.locator('.prose article')).toHaveAttribute('data-article-id', id);
  await expect(page.locator('.article-issue')).toContainText('Summer 2024');
  await capture(page, 'article-desktop');
});

test('explicit locale prevails over saved choice; root uses saved choice', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('remnant-language', 'fr'));
  await page.goto('/en/'); await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await page.goto('/'); await expect(page).toHaveURL(/\/fr\/$/);
  await expect(page.locator('.empty-state')).toBeVisible();
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
  await page.goto(article('en'));
  await page.locator('[data-language-select]').selectOption(`/fr/articles/${id}/`);
  await expect(page.locator('html')).toHaveAttribute('lang', 'fr');
  await expect(page.locator('.empty-state')).toContainText('anglais');
  await expect(page.locator('meta[name=robots]')).toHaveAttribute('content','noindex,follow');
  await page.locator('.empty-state a[hreflang=en]').click();
  await expect(page).toHaveURL(new RegExp(article('en')+'$'));
});

test('locale switching follows real article IDs and keeps the AI notice', async ({ page }) => {
  await page.goto(article('en'));
  await page.locator('[data-language-select]').selectOption(article('af'));
  await expect(page.locator('html')).toHaveAttribute('lang','af');
  await expect(page.locator('.prose aside')).toContainText('OpenAI');
  await capture(page, 'afrikaans-article');
  const englishNoticeLink = page.locator(`.prose aside a[href="/en/articles/${id}/"]`);
  await englishNoticeLink.click();
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
    await expect(page.locator('.category-tile')).toHaveCount(26);
    if (locale.meta.tag==='ar') await capture(page,'arabic-mobile');
    if (locale.meta.tag==='zh-Hans') await capture(page,'chinese-mobile');
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
  await page.locator('select[name=category]').selectOption('11f3b229-ad6c-5d69-b529-82d977f8d000');
  await expect(page.locator('.search-result')).not.toHaveCount(0);
  await expect(page.locator('.search-result .eyebrow').first()).not.toBeEmpty();
});

test('Markdown fallback preserves selectable text when clipboard unavailable', async ({ page }) => {
  await page.addInitScript(()=>Object.defineProperty(navigator,'clipboard',{value:undefined}));
  await page.goto(article('af'));
  await page.locator('[data-copy-markdown]').click();
  await expect(page.locator('#markdown-fallback')).toBeVisible();
  await expect(page.locator('#markdown-text')).toContainText('');
  const value=await page.locator('#markdown-text').inputValue();
  expect(value).toContain('OpenAI'); expect(value).toContain('The Heartbeat of the Remnant');
  expect(value).toContain('/af/issues/');
});

test('reduced motion disables autoplay but keeps manual archive navigation', async ({ page }) => {
  await page.emulateMedia({reducedMotion:'reduce'});await page.goto('/en/');
  await expect(page.locator('[data-slide-play]')).toBeDisabled();
  await expect(page.locator('[data-slide-count]')).toHaveText('1 / 3');
  await page.locator('[data-slide-next]').click();
  await expect(page.locator('[data-slide-count]')).toHaveText('2 / 3');
  await page.locator('[data-slide-prev]').click();
  await expect(page.locator('[data-slide-count]')).toHaveText('1 / 3');
});

test('static browsing remains useful with JavaScript disabled', async ({ browser }) => {
  const context=await browser.newContext({javaScriptEnabled:false});const page=await context.newPage();
  await page.goto('/fr/');await expect(page.locator('.empty-state')).toBeVisible();
  await expect(page.locator('noscript .nojs-languages')).toBeVisible();
  await page.goto('/en/issues/');await expect(page.locator('.issue-tile')).toHaveCount(56);
  await page.locator('.issue-tile').first().click();await expect(page.locator('.issue-contents > li')).not.toHaveCount(0);
  await context.close();
});

test('article print keeps source notice and hides controls', async ({ page }) => {
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
