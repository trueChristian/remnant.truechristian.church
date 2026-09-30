/** Build-only, pinned OpenBible BCV adapter. Never shipped to article readers. */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { bcv_parser } from 'bible-passage-reference-parser/esm/bcv_parser.js';
const languages = {af:'afr', bn:'ben', nb:'no', 'zh-Hans':'zh'};
const supported = new Set('af ar bn de el en es fr he hi id it ko nb nl pt ru sv sw ur zh-Hans'.split(' '));
const parsers = new Map();
async function parser(locale) {
  if (!supported.has(locale)) throw new Error(`Unsupported Scripture locale: ${locale}`);
  if (!parsers.has(locale)) {
    const code = languages[locale] || locale;
    const language = await import(['afr','ben'].includes(code) ? `./vendor/bcv/${code}.js` : `bible-passage-reference-parser/esm/lang/${code}.js`);
    const value = new bcv_parser(language);
    value.set_options({osis_compaction_strategy:'bcvp', invalid_passage_strategy:'include', invalid_sequence_strategy:'include', sequence_combination_strategy:'combine', book_alone_strategy:'ignore', book_sequence_strategy:'ignore', non_latin_digits_strategy:'replace', passage_existence_strategy:'bcv', zero_chapter_strategy:'error', zero_verse_strategy:'error', testaments:'on'});
    parsers.set(locale, value);
  }
  return parsers.get(locale);
}
function invalid(value) {
  if (!value || typeof value !== 'object') return false;
  if (value.valid && typeof value.valid === 'object' && (!value.valid.valid || Object.keys(value.valid.messages || {}).length)) return true;
  if (value.alternates?.length) return true;
  return Object.entries(value).some(([key, child]) => key !== 'alternates' && (Array.isArray(child) ? child.some(invalid) : invalid(child)));
}
export async function detect(locale, text) {
  const bcv = await parser(locale);
  const info = bcv.translation_info();
  const results = [];
  const groups = [];
  const modes = ['de','es','fr','it','pt'].includes(locale) ? ['us','eu'] : ['us'];
  for (const mode of modes) {
  bcv.set_options({punctuation_strategy:mode});
  for (const sequence of bcv.parse(text).parsed_entities()) {
    let group = null;
    for (const entry of sequence.entities || []) {
      const explicit = /^(?:bc|bcv)$/.test(entry.type) || (entry.type === 'range' && /^(?:bc|bcv)$/.test(entry.start?.type));
      if (!entry.osis || invalid(entry)) { group = null; continue; }
      if (explicit) { group = {mode, osis:entry.osis, indices:[...entry.indices], entities:[entry]}; groups.push(group); }
      else if (group) { group.osis += ','+entry.osis; group.indices[1] = entry.indices[1]; group.entities.push(entry); }
    }
  }
  }
  for (const entity of groups) {
    const [start, end] = entity.indices;
    const quote = text.slice(start, end);
    const separator = quote.match(/\p{N}+\s*([,:.])\s*\p{N}+/u)?.[1];
    if (modes.length > 1 && ((entity.mode === 'us' && separator === ',') || (entity.mode === 'eu' && separator !== ','))) continue;
    // Require an explicit book at the beginning, not a free-standing number/time.
    // Reject very short Latin prose aliases ("Is 3", "Am 4") unless punctuated.
    const first = entity.entities?.[0];
    if (!first || !/^(?:bcv?|range)/.test(first.type)) continue;
    const prefix = quote.replace(/^(?:[1-3ⅠⅡⅢ][.\s]*|I{1,3}[.\s]+)/u,'').match(/^[^\p{N}\s:]+/u)?.[0] || '';
    const safeShort = {en:['Jn','Mt','Mk','Lk','Ps','Pr','Ro'],af:['Ps'],de:['Ps'],es:['Jn','Mt','Mc','Lc','Sal'],fr:['Jn','Mt','Mc','Lc','Ps'],it:['Mt','Mc','Lc','Gv','Sal'],nl:['Ps'],pt:['Mt','Mc','Lc','Jo','Sl'],nb:['Mt','Mk','Lk','Joh','Sal'],sv:['Ps']};
    if (/^[A-Za-z]{1,2}$/.test(prefix) && !(safeShort[locale]?.some(alias=>alias.toLowerCase()===prefix.toLowerCase()) && (prefix.toLowerCase()==='ps' || /\p{N}+\s*[:.,]\s*\p{N}+/u.test(quote)))) continue;
    const queries = [];
    let rejected = false;
    for (const part of entity.osis.split(',')) {
      const match = /^(\w+)\.(\d+)\.(\d+)(?:-(\w+)\.(\d+)\.(\d+))?$/.exec(part);
      if (!match) { rejected = true; break; }
      const [, book, cs, vs, endBook = book, ce = cs, ve = vs] = match;
      if (book !== endBook || !info.order[book] || info.order[book] > 66 || Number(ce)-Number(cs) > 10) { rejected = true; break; }
      for (let chapter = Number(cs); chapter <= Number(ce); chapter++) {
        const from = chapter === Number(cs) ? Number(vs) : 1;
        const to = chapter === Number(ce) ? Number(ve) : info.chapters[book][chapter-1];
        if (!Number.isInteger(to) || from < 1 || to < from || to > info.chapters[book][chapter-1]) { rejected = true; break; }
        queries.push(`${info.order[book]} ${chapter}:${from}${to === from ? '' : `-${to}`}`);
      }
    }
    if (rejected || !queries.length || queries.length > 12) continue;
    results.push({start:Array.from(text.slice(0,start)).length, end:Array.from(text.slice(0,end)).length, osis:entity.osis, queries:[...new Set(queries)]});
  }
  return results.sort((a,b)=>a.start-b.start).filter((value,index,all)=>!all.slice(0,index).some(previous=>value.start < previous.end && value.end > previous.start));
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const input = JSON.parse(readFileSync(0, 'utf8'));
  if (!Array.isArray(input) || input.length > 200000) throw new Error('Expected bounded scan batch');
  const output = [];
  for (const item of input) output.push(await detect(item.locale, item.text));
  process.stdout.write(JSON.stringify(output));
}
