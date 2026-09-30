import test, { beforeEach, after } from 'node:test';
import assert from 'node:assert/strict';
import { parseReference, parseSelection, validateScripture, ScriptureClient, bibleReaderUrl } from '../assets/scripture-popovers.js';
import { Memory } from '../assets/vendor/getbible/3.1.0/Memory.js';

const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
const storage = new Map();
const good = (text = 'For God so loved the world.') => ({ kjv_43_3: {
  translation: 'King James Version', abbreviation: 'kjv', lang: 'en', language: 'English',
  direction: 'LTR', encoding: 'UTF-8', book_nr: 43, book_name: 'John', chapter: 3,
  name: 'John 3', ref: ['43 3:16'], verses: [{ chapter: 3, verse: 16, text }]
} });
beforeEach(() => {
  Memory.clearMemory(); storage.clear();
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)
  } });
});
after(() => {
  if (originalStorage) Object.defineProperty(globalThis, 'localStorage', originalStorage);
  else delete globalThis.localStorage;
});

test('strict canonical selections support ranges, lists, chapters and multiple versions', () => {
  assert.deepEqual([...parseReference('62 3:16-19,22').verses], [16,17,18,19,22]);
  assert.deepEqual(parseSelection('43 3:16;43 4:1-2', 'kjv;aov'), { refs:['43 3:16','43 4:1-2'], versions:['kjv','aov'] });
  assert.equal(parseReference('19 119:1-176').verses.size, 176);
});
test('malformed, oversized or noncanonical queries cannot reach the API', () => {
  for (const bad of ['John 3:16','43 3','43 3:16–19','43 3:19-16','43 3:0','43 3:1-999','85 1:1','43 3:16<script>','43 3:１６']) {
    assert.throws(() => parseReference(bad), bad);
  }
  assert.throws(() => parseSelection('43 3:16', '../kjv'));
  assert.throws(() => parseSelection(Array.from({length:13},(_,i)=>`43 ${i+1}:1`).join(';'), 'kjv'));
});
test('real upstream Scripture and Reference classes preserve API text as data', () => {
  const scripture = validateScripture(good('<img src=x onerror=alert(1)>'), '43 3:16', 'kjv');
  scripture.forEachReference(ref => {
    assert.equal(ref.reference, 'John 3:16'); assert.equal(ref.verseReference, '16');
    assert.equal(ref.verses[0].text, '<img src=x onerror=alert(1)>');
    assert.equal(bibleReaderUrl(ref), 'https://getbible.life/kjv/John/3/16');
    assert.equal(bibleReaderUrl(ref, 'javascript:alert(1)'), 'https://getbible.life/kjv/John/3/16');
    assert.equal(bibleReaderUrl(ref, 'https://unapproved-reader.example/'), 'https://getbible.life/kjv/John/3/16');
  });
});
test('reader path metadata is encoded and never changes the reader origin', () => {
  const value = good(); value.kjv_43_3.book_name = '//attacker.test/<script>';
  validateScripture(value,'43 3:16','kjv').forEachReference(ref => {
    const url = bibleReaderUrl(ref);
    assert.equal(new URL(url).origin, 'https://getbible.life'); assert.ok(url.includes('%2F%2Fattacker.test%2F%3Cscript%3E'));
  });
});
test('response coordinates, translation and completeness are checked', () => {
  for (const mutate of [
    data => data.kjv_43_3.chapter = 4,
    data => data.kjv_43_3.abbreviation = 'aov',
    data => data.kjv_43_3.verses[0].verse = 17,
    data => data.kjv_43_3.verses.push(data.kjv_43_3.verses[0]),
    data => data.kjv_43_3.verses[0].text = {},
    data => data.other = data.kjv_43_3,
    data => data.kjv_43_3.verses = []
  ]) { const data = good(); mutate(data); assert.throws(() => validateScripture(data, '43 3:16', 'kjv')); }
  assert.throws(() => validateScripture(good(), '43 3:16-17', 'kjv'));
});
test('absent optional metadata remains usable without inventing language or encoding', () => {
  const data = good(); delete data.kjv_43_3.encoding; delete data.kjv_43_3.lang;
  validateScripture(data, '43 3:16','kjv').forEachReference(ref => assert.equal(ref.encoding, ''));
});
test('simultaneous and subsequent requests deduplicate and use the real upstream URL', async () => {
  let calls = 0;
  const client = new ScriptureClient({ fetchImpl: async (url, options) => {
    calls++; assert.equal(url, 'https://query.getbible.net/v2/kjv/43%203%3A16');
    assert.equal(options.credentials, 'omit'); assert.equal(options.referrerPolicy, 'no-referrer');
    return { ok:true, json:async () => good() };
  } });
  const first = client.get('43 3:16','kjv');
  assert.equal(first, client.get('43 3:16','kjv')); await first;
  await client.get('43 3:16','kjv'); assert.equal(calls, 1);
});
test('blocked storage does not prevent retrieval or page-local caching', async () => {
  Object.defineProperty(globalThis, 'localStorage', { configurable:true, get() { throw new Error('Denied'); } });
  let calls=0; const client = new ScriptureClient({fetchImpl:async()=>{calls++; return {ok:true,json:async()=>good()};}});
  await client.get('43 3:16','kjv'); await client.get('43 3:16','kjv'); assert.equal(calls,1);
});
test('injected native-style fetch retains its required global receiver', async () => {
  let called = false;
  const client = new ScriptureClient({ fetchImpl: async function () {
    assert.equal(this, globalThis, 'Browser fetch must not receive the Api instance as this');
    called = true;
    return {ok:true,json:async()=>good()};
  } });
  await client.get('43 3:16','kjv');
  assert.equal(called,true);
});
test('corrupt, expired and future-dated persisted cache records are misses', async () => {
  for (const value of ['{', JSON.stringify({timestamp:0,data:good()}), JSON.stringify({timestamp:Date.now()+86400000,data:good()})]) {
    Memory.clearMemory(); storage.set('getBible-kjv-43 3:16',value);
    assert.equal(await Memory.get('43 3:16','kjv'),null);
  }
});
test('invalid cached response is removed and the next attempt can recover', async () => {
  const invalid = good(); invalid.kjv_43_3.book_nr = 1;
  Memory.set('43 3:16','kjv',invalid);
  let calls=0; const client = new ScriptureClient({fetchImpl:async()=>{calls++;return {ok:true,json:async()=>good()};}});
  await assert.rejects(client.get('43 3:16','kjv'));
  await client.get('43 3:16','kjv'); assert.equal(calls,1);
});
test('API network errors can retry rather than caching failure', async () => {
  let calls=0; const client=new ScriptureClient({fetchImpl:async()=>{
    if (++calls===1) throw new Error('Offline'); return {ok:true,json:async()=>good()};
  }});
  await assert.rejects(client.get('43 3:16','kjv')); await client.get('43 3:16','kjv'); assert.equal(calls,2);
});
test('upstream request has a bounded abort timeout', async () => {
  const client = new ScriptureClient({ timeoutMs:10, fetchImpl:async (url,{signal}) => new Promise((resolve,reject)=>{
    signal.addEventListener('abort',()=>reject(new Error('Aborted')), {once:true});
  }) });
  await assert.rejects(client.get('43 3:16','kjv'),/Aborted/);
});
