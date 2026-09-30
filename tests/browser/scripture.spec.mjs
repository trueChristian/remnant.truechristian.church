import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const assets = path.resolve('assets');
const defaultBody = `Before <span class="scripture-reference" data-reference="43 3:16" data-scripture-id="john" data-translation="kjv">John 3:16</span> after.
<p>Another <span class="scripture-reference" data-reference="45 8:1" data-scripture-id="romans" data-translation="kjv">Romans 8:1</span>.</p>
<p><em><span class="scripture-reference" data-reference="43 3:16" data-scripture-id="split" data-translation="kjv">John</span></em><span class="scripture-reference" data-reference="43 3:16" data-scripture-id="split" data-translation="kjv"> 3:16</span> across emphasis.</p>`;
const response = (reference = '43 3:16', abbreviation='kjv', text='For God so loved the world.', overrides={}) => {
  const [book, tail] = reference.split(' '), [chapter, verse] = tail.split(':');
  const bookName = book === '43' ? 'John' : 'Romans';
  return { chapter: { abbreviation, translation: 'King James Version', lang:'en', language:'English',
    direction:'LTR', encoding:'UTF-8', book_nr:Number(book), book_name:bookName, chapter:Number(chapter),
    name:`${bookName} ${chapter}`, ref:reference, verses:[{chapter:Number(chapter),verse:Number(verse),text}], ...overrides } };
};
async function fixture(page, {body=defaultBody, dir='ltr', theme='light', ui={}} = {}) {
  await page.route('**/assets/**', async route => {
    const url = new URL(route.request().url());
    const file = path.resolve(assets, url.pathname.slice('/assets/'.length));
    if (!file.startsWith(assets + path.sep) || !fs.existsSync(file)) return route.abort();
    await route.fulfill({path:file,contentType:file.endsWith('.css')?'text/css':'text/javascript'});
  });
  await page.route('**/__scripture-fixture', route => route.fulfill({contentType:'text/html; charset=utf-8',body:`<!doctype html>
  <html lang="en" dir="${dir}" data-theme="${theme}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <link rel="stylesheet" href="/assets/site.css"><link rel="stylesheet" href="/assets/scripture-popovers.css">
  <style>body{margin:24px;font-family:Arial,sans-serif}main{max-width:650px;font-size:20px;line-height:1.8}</style>
  <script type="module" src="/assets/scripture-popovers.js"></script></head><body>
  <a href="#before" id="before">Before</a><main class="prose" id="original">${body}</main>
  <button id="after">After article</button><script type="application/json" id="page-config">${JSON.stringify({scriptureUi:ui}).replaceAll('<','\\u003c')}</script></body></html>`}));
  await page.goto('/__scripture-fixture');
  await expect(page.locator('.scripture-reference').first()).toHaveAttribute('data-scripture-ready','true');
}
async function mockApi(page, handler) {
  await page.route('https://query.getbible.net/v2/**', async route => {
    const parts = new URL(route.request().url()).pathname.split('/');
    const version = decodeURIComponent(parts[2]), ref = decodeURIComponent(parts[3]);
    // The provider is cross-origin. Mock its public CORS contract explicitly.
    const fulfill = options => route.fulfill({...options,headers:{'access-control-allow-origin':'*',...options.headers}});
    if (handler) return handler({fulfill,abort:(...args)=>route.abort(...args)}, ref, version);
    await fulfill({json:response(ref,version)});
  });
}
async function sourceMarkup(page, selector = '#original') {
  return page.locator(selector).evaluate(original => {
    const copy = original.cloneNode(true);
    for (const marker of copy.querySelectorAll('.scripture-reference')) marker.replaceWith(...marker.childNodes);
    return copy.innerHTML;
  });
}
async function capture(page, filename) {
  fs.mkdirSync('.test-output/screenshots', {recursive:true});
  await page.screenshot({path:`.test-output/screenshots/${filename}.png`,fullPage:false});
}

test('GetBible is on demand, hoverable, escaped, linked and source-faithful', async ({page}) => {
  const calls=[]; const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  await mockApi(page,async(route,ref,version)=>{calls.push(ref);await route.fulfill({json:response(ref,version,'<img src=x onerror="window.pwned=1"> & literal text')});});
  await fixture(page); const original=await sourceMarkup(page);
  expect(calls).toEqual([]);
  await page.locator('[data-scripture-id="john"]').hover();
  const popup=page.getByRole('dialog'); await expect(popup).toBeVisible();
  await expect(popup).toContainText('<img src=x onerror="window.pwned=1"> & literal text');
  expect(calls).toEqual(['43 3:16']);
  await expect(popup.locator('img,script')).toHaveCount(0);
  await expect(popup.getByRole('link')).toHaveAttribute('href','https://getbible.life/kjv/John/3/16');
  await popup.hover(); await page.waitForTimeout(250); await expect(popup).toBeVisible();
  expect(await sourceMarkup(page)).toBe(original);
  expect(await page.evaluate(()=>window.pwned)).toBeUndefined(); expect(errors).toEqual([]);
});

test('keyboard opens and dismisses, restores focus, and permits forward/back navigation', async ({page}) => {
  await mockApi(page); await fixture(page);
  const trigger=page.locator('[data-scripture-id="john"]');
  await trigger.focus(); await page.keyboard.press('Enter');
  const popup=page.getByRole('dialog'); await expect(popup.getByRole('button',{name:'Close'})).toBeFocused();
  await expect(popup).toContainText('For God so loved the world.');
  await expect(popup.getByRole('link')).toBeVisible();
  await page.keyboard.press('Tab'); await expect(popup.getByRole('link')).toBeFocused();
  await page.keyboard.press('Escape'); await expect(popup).toBeHidden(); await expect(trigger).toBeFocused();
  await page.keyboard.press(' '); await expect(popup).toBeVisible();
  await page.keyboard.press('Shift+Tab'); await expect(popup).toBeHidden(); await expect(trigger).toBeFocused();
  await page.keyboard.press('ArrowDown'); await expect(popup).toBeVisible();
  await expect(popup.getByRole('link')).toBeVisible(); await page.keyboard.press('Tab'); await page.keyboard.press('Tab');
  await expect(page.locator('[data-scripture-id="romans"]')).toBeFocused();
});

test('split emphasis shares one interaction and cache without changing source elements', async ({page}) => {
  let calls=0; await mockApi(page,async(route,ref,version)=>{calls++; await route.fulfill({json:response(ref,version)});});
  await fixture(page);
  const pieces=page.locator('[data-scripture-id="split"]');
  await expect(pieces.first()).toHaveAttribute('tabindex','0'); await expect(pieces.last()).toHaveAttribute('tabindex','-1');
  await pieces.last().click(); await expect(page.getByRole('dialog')).toContainText('For God');
  await expect(page.getByRole('dialog').locator('h2')).toHaveText('John 3:16');
  await expect(pieces.first()).toHaveAttribute('aria-expanded','true');
  await expect(page.locator('#original em')).toHaveText('John');
  await page.keyboard.press('Escape'); await expect(pieces.first()).toBeFocused();
  await page.locator('[data-scripture-id="john"]').click(); await expect(page.getByRole('dialog')).toContainText('For God');
  expect(calls).toBe(1);
});

test('touch-sized RTL dark popover fits viewport, localizes controls and closes outside', async ({browser}) => {
  const context=await browser.newContext({viewport:{width:320,height:640},hasTouch:true,isMobile:true});
  const page=await context.newPage();
  await mockApi(page,async(route,ref,version)=>route.fulfill({json:response(ref,version,'نص الآية في اتجاه صحيح',{direction:'RTL',lang:'ar',language:'Arabic'})}));
  await fixture(page,{dir:'rtl',theme:'dark',ui:{close:'إغلاق',readBible:'اقرأ في الكتاب'}});
  await page.locator('[data-scripture-id="john"]').tap();
  const popup=page.getByRole('dialog'); await expect(popup).toContainText('نص الآية');
  await expect(popup.getByRole('button',{name:'إغلاق'})).toBeVisible();
  await expect(popup.locator('.scripture-popover__passage')).toHaveAttribute('dir','rtl');
  const box=await popup.boundingBox(); expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(320);
  expect(await popup.evaluate(el=>getComputedStyle(el).backgroundColor)).toBe('rgb(24, 28, 30)');
  await capture(page,'scripture-popover-rtl-dark-mobile');
  await page.locator('#before').tap(); await expect(popup).toBeHidden();
  await context.close();
});

test('network failure preserves article and retry works with all browser storage denied', async ({page}) => {
  await page.addInitScript(()=>Object.defineProperty(window,'localStorage',{get(){throw new Error('Storage denied');}}));
  let calls=0; await mockApi(page,async(route,ref,version)=>{
    if (++calls===1) return route.abort('failed'); await route.fulfill({json:response(ref,version)});
  });
  await fixture(page);const text=await page.locator('#original').textContent();
  const trigger=page.locator('[data-scripture-id="john"]'); await trigger.click();
  await expect(page.getByRole('dialog')).toContainText('could not be loaded');
  await expect(page.getByRole('dialog').getByRole('link',{name:'Read in the Bible'})).toHaveAttribute('href','https://getbible.life/');
  expect(await page.locator('#original').textContent()).toBe(text);
  await page.keyboard.press('Escape'); await trigger.click();
  await expect(page.getByRole('dialog')).toContainText('For God');
  await page.keyboard.press('Escape'); await trigger.click();
  await expect(page.getByRole('dialog')).toContainText('For God'); expect(calls).toBe(2);
});

test('dismissal and newer reference prevent late requests from reopening or overwriting', async ({page}) => {
  let release; const pending=new Promise(resolve=>{release=resolve;});
  await mockApi(page,async(route,ref,version)=>{
    if(ref==='43 3:16') await pending;
    await route.fulfill({json:response(ref,version,ref==='43 3:16'?'Older John result':'Current Romans result')});
  });
  await fixture(page); await page.locator('[data-scripture-id="john"]').click();
  await expect(page.getByRole('dialog')).toContainText('Loading'); await page.keyboard.press('Escape');
  await page.locator('[data-scripture-id="romans"]').click();await expect(page.getByRole('dialog')).toContainText('Current Romans');
  release(); await page.waitForTimeout(200);
  await expect(page.getByRole('dialog')).not.toContainText('Older John');
  await page.keyboard.press('Escape'); await page.waitForTimeout(200);await expect(page.getByRole('dialog')).toBeHidden();
});

test('initialization is idempotent and print keeps source without popup decoration', async ({page}) => {
  await mockApi(page);await fixture(page);
  await page.evaluate(async()=>{const mod=await import('/assets/scripture-popovers.js');mod.initScripturePopovers(document);mod.initScripturePopovers(document);});
  await expect(page.getByRole('dialog',{includeHidden:true})).toHaveCount(1);
  await page.locator('[data-scripture-id="john"]').click();await expect(page.getByRole('dialog')).toContainText('For God');
  await page.emulateMedia({media:'print'}); await expect(page.getByRole('dialog')).toBeHidden();
  await expect(page.locator('#original')).toContainText('John 3:16');
  expect(await page.locator('[data-scripture-id="john"]').evaluate(el=>getComputedStyle(el).textDecorationLine)).toBe('none');
});

test('generated article loads real assets, preserves prose and displays desktop/mobile popovers', async ({page}) => {
  const manifest=JSON.parse(fs.readFileSync('dist/scripture/manifest.json','utf8'));
  const index=JSON.parse(fs.readFileSync('dist/en/search-index.json','utf8'));
  let selected;
  for (const record of Object.values(manifest.records)) {
    if (record.locale !== 'en') continue;
    const marker=record.markers.find(item=>item.queries.length===1 && item.queries[0]==='43 3:16');
    const article=index.find(item=>item.id===record.article_id);
    if (marker && article) {selected={marker,article};break;}
  }
  expect(selected,'The current generated English archive must contain a John 3:16 marker').toBeTruthy();
  await mockApi(page);
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(selected.article.url);
  const trigger=page.locator(`[data-scripture-id="${selected.marker.id}"]`).first();
  await expect(trigger).toHaveAttribute('data-scripture-ready','true');
  const original=await sourceMarkup(page,'.prose');
  await trigger.click();
  const popup=page.getByRole('dialog');
  await expect(popup).toContainText('For God so loved the world.');
  await expect(popup.getByRole('link')).toHaveAttribute('href','https://getbible.life/kjv/John/3/16');
  expect(await sourceMarkup(page,'.prose')).toBe(original);
  await capture(page,'scripture-generated-article-desktop');
  await page.keyboard.press('Escape');
  await page.setViewportSize({width:390,height:844});
  await trigger.click();await expect(popup).toContainText('For God so loved the world.');
  const bounds=await popup.boundingBox();expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x+bounds.width).toBeLessThanOrEqual(390);
  expect(await sourceMarkup(page,'.prose')).toBe(original);
  await capture(page,'scripture-generated-article-mobile');
  expect(errors).toEqual([]);
});
