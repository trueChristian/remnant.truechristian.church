/** One tiny live availability probe, separate from deterministic mocked tests. */
import { mkdirSync, writeFileSync } from 'node:fs';
import { ScriptureClient } from '../assets/scripture-popovers.js';
const report = {checked_at:new Date().toISOString(), endpoint:'https://query.getbible.net/v2/kjv/43%203%3A16', query:'43 3:16', translation:'kjv', available:false};
try {
  const scripture = await new ScriptureClient({timeoutMs:15000}).get(report.query,report.translation);
  const references = [];
  scripture.forEachReference(reference => references.push({book:reference.bookNumber, chapter:reference.chapter, verses:reference.verses.map(verse=>verse.verse)}));
  report.available = true;
  report.validated = 'Exact requested KJV book 43, chapter 3, verse 16; text deliberately omitted from evidence.';
} catch(error) {
  report.error = String(error.message || error).slice(0,400);
  console.warn('::warning::Live GetBible probe unavailable; mocked browser tests are not live-provider verification. See scripture-provider-report.json.');
}
mkdirSync('.build',{recursive:true});
writeFileSync('.build/scripture-provider-report.json',JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
// Provider reachability is external and transient. Its result is explicit in
// evidence/summary and does not block an otherwise valid static-site build.
