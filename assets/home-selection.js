/**
 * Shared, deterministic homepage schedule. There is no visitor state, local
 * time zone, daily reset, or call to Math.random() in this module.
 *
 * Each section traverses a locale-seeded shuffled circle forever. Keeping its
 * permutation across cycle boundaries is deliberate: reshuffling each cycle
 * could repeat the last item of one cycle at the start of the next.
 */
export const HOME_SLOT_MS = 10 * 60 * 1000;

const ARCHIVE_COUNT = 3;
const CATEGORY_COUNT = 8;

function validId(id) {
  return typeof id === 'string' && id.length > 0;
}

function canonicalIds(records) {
  // Default sort compares UTF-16 code units, consistently across runtimes.
  return [...new Set(records.map(record => record?.id).filter(validId))].sort();
}

function hashSeed(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash = Math.imul(hash ^ value.charCodeAt(index), 16777619);
  }
  return hash >>> 0;
}

function shuffledIds(ids, locale, section) {
  const result = [...ids];
  // Include the canonical pool as well as the section, so reordering source
  // records changes nothing and independent sections have independent orders.
  let state = hashSeed(JSON.stringify(['home-selection-v1', locale, section, ids]));
  function random() {
    state = (state + 0x6d2b79f5) >>> 0;
    let value = Math.imul(state ^ (state >>> 15), state | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  }
  for (let index = result.length - 1; index > 0; index -= 1) {
    const other = Math.floor(random() * (index + 1));
    [result[index], result[other]] = [result[other], result[index]];
  }
  return result;
}

function takeSlot(ids, requestedCount, slot, locale, section) {
  const count = Math.min(requestedCount, ids.length);
  if (count === 0) return [];
  const ordered = shuffledIds(ids, locale, section);
  // Reduce before multiplication so every safe integer slot stays exact.
  // Normalize modulo for dates before the Unix epoch too.
  const offset = (((slot % ordered.length) + ordered.length) % ordered.length * count) % ordered.length;
  return Array.from({ length: count }, (_, index) => ordered[(offset + index) % ordered.length]);
}

/**
 * @param {object} data One locale's available homepage content.
 * @param {string} data.locale Locale identifier; never the visitor's locale.
 * @param {{id: string, issueId?: string}[]} [data.articles] Article candidates.
 * @param {{id: string, articleId: string|null}[]} [data.features] One row per
 *   issue, with that issue's editor remark. The returned featureId selects this
 *   pair. An explicit null enables a cover-only missing-translation fallback.
 * @param {{id: string}[]} [data.categories] Available categories.
 * @param {string[]} [data.latestIds] Permanently shown latest articles, excluded
 *   from the archive pool along with ALL feature/editor-remark article IDs.
 * @param {number} nowMs Explicit UTC epoch milliseconds, normally Date.now().
 * @returns {{featureId: string|null, archiveIds: string[], categoryIds: string[], slot: number}}
 *
 * With N eligible archive articles, each article appears exactly once per N
 * positions in the continuous sequence. Three positions are consumed per slot,
 * so repeat display starts are at least floor(N / 3) slots apart. N >= 435
 * therefore leaves a full 144 slots (24 hours) AFTER the previous display ends.
 * N = 432 only gives 24 hours between display starts, or 23h50m of absence.
 * Smaller pools still use every item before the continuous sequence repeats;
 * fewer than three eligible articles are all displayed without duplicates.
 * These guarantees require an unchanged locale/pool and synchronized clocks.
 * Changing the content inventory intentionally establishes a new schedule.
 */
export function selectHome(data, nowMs) {
  const slot = Math.floor(nowMs / HOME_SLOT_MS);
  if (typeof nowMs !== 'number' || !Number.isFinite(nowMs) || !Number.isSafeInteger(slot)) {
    throw new RangeError('nowMs must be finite epoch milliseconds with a safe integer slot');
  }
  const { locale = '', articles = [], features = [], categories = [], latestIds = [] } = data;
  const eligibleFeatures = features.filter(feature => validId(feature?.id)
    && (validId(feature?.articleId) || feature?.articleId === null));
  const excluded = new Set([
    ...latestIds.filter(validId),
    ...features.map(feature => feature?.articleId).filter(validId),
  ]);
  const archivePool = canonicalIds(articles).filter(id => !excluded.has(id));
  return {
    featureId: takeSlot(canonicalIds(eligibleFeatures), 1, slot, locale, 'features')[0] ?? null,
    archiveIds: takeSlot(archivePool, ARCHIVE_COUNT, slot, locale, 'archive'),
    categoryIds: takeSlot(canonicalIds(categories), CATEGORY_COUNT, slot, locale, 'categories'),
    slot,
  };
}
