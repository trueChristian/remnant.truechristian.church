/** Unicode substring + multi-term search. No language-specific stemming assumptions. */
export function normalize(value) {
  return String(value).normalize('NFKD').replace(/([\p{Script=Latin}])\p{M}+/gu, '$1').normalize('NFC').toLocaleLowerCase().replace(/[’‘]/g, "'");
}
export function tokenize(query) {
  return [...new Set(normalize(query).trim().split(/\s+/u).filter(Boolean))];
}
export function prepare(records) {
  return records.map((record, order) => ({ ...record, order,
    normalizedTitle: normalize(record.title),
    normalizedMeta: normalize([...(record.categories || []), ...(record.topics || []), record.issue, record.author].join(' ')),
    normalizedBody: normalize(record.body)
  }));
}
export function search(records, query, filters = {}, offset = 0) {
  const terms = tokenize(query);
  const hits = [];
  for (const record of records) {
    if (filters.category && !record.category_ids.includes(filters.category)) continue;
    if (filters.issue && record.issue_id !== filters.issue) continue;
    let score = 0;
    let bodyMatch = -1;
    const matched = terms.every(term => {
      const title = record.normalizedTitle.includes(term);
      const meta = record.normalizedMeta.includes(term);
      const body = record.normalizedBody.indexOf(term);
      if (bodyMatch < 0 && body >= 0) bodyMatch = body;
      score += title ? 30 : meta ? 10 : body >= 0 ? 1 : 0;
      return title || meta || body >= 0;
    });
    if (!matched) continue;
    // NFKD changes offsets; snippets find a close original-text window. Highlighting
    // uses original characters separately, so decomposed scripts are never damaged.
    const start = Math.max(0, (bodyMatch < 0 ? 0 : bodyMatch) - 70);
    const snippet = `${start ? '…' : ''}${record.body.slice(start, start + 240)}${start + 240 < record.body.length ? '…' : ''}`;
    hits.push({ id: record.id, title: record.title, url: record.url, issue: record.issue,
      categories: record.categories, author: record.author, snippet, score, order: record.order });
  }
  hits.sort((a, b) => b.score - a.score || a.order - b.order);
  return { total: hits.length, offset, hasMore: offset + 40 < hits.length, results: hits.slice(offset, offset + 40) };
}
export function preferredLocale(saved, browserLanguages, supported) {
  if (supported.includes(saved)) return saved;
  for (const language of browserLanguages) {
    const exact = supported.find(x => x.toLowerCase() === language.toLowerCase());
    if (exact) return exact;
    const base = language.split('-')[0].toLowerCase();
    const match = supported.find(x => x.split('-')[0].toLowerCase() === base);
    if (match) return match;
  }
  return 'en';
}
