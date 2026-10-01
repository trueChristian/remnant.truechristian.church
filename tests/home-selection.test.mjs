import test from 'node:test';
import assert from 'node:assert/strict';
import { HOME_SLOT_MS, selectHome } from '../assets/home-selection.js';

const records = (count, prefix = 'article') => Array.from({ length: count }, (_, index) => ({ id: `${prefix}-${index}` }));
const atSlot = (data, slot) => selectHome(data, slot * HOME_SLOT_MS);
const fixture = (count = 450) => ({
  locale: 'en',
  articles: [...records(count), ...records(6, 'latest'), ...records(11, 'editor')],
  features: records(11, 'issue').map((record, index) => ({ ...record, articleId: `editor-${index}` })),
  categories: records(19, 'category'),
  latestIds: records(6, 'latest').map(record => record.id),
});

test('all visitors and repeated loads receive identical content throughout a UTC slot', () => {
  const data = fixture();
  const start = Date.parse('2026-10-01T12:30:00Z');
  const expected = selectHome(data, start);
  assert.equal(expected.slot, Math.floor(start / HOME_SLOT_MS));
  for (const offset of [0, 1, 237000, HOME_SLOT_MS - 1]) {
    assert.deepEqual(selectHome(structuredClone(data), start + offset), expected);
  }
  assert.deepEqual(selectHome(data, Date.parse('2026-10-01T05:30:00-07:00')), expected);
});

test('selection changes at the exact ten-minute boundary', () => {
  const data = fixture();
  const boundary = Date.parse('2026-10-01T12:40:00Z');
  const before = selectHome(data, boundary - 1);
  const after = selectHome(data, boundary);
  assert.equal(after.slot, before.slot + 1);
  assert.notDeepEqual(after.archiveIds, before.archiveIds);
  assert.notEqual(after.featureId, before.featureId);
  assert.notDeepEqual(after.categoryIds, before.categoryIds);
});

test('reordering input and duplicating records cannot change selections', () => {
  const data = fixture();
  const reordered = {
    ...data,
    articles: [...data.articles].reverse().concat(data.articles[0]),
    features: [...data.features].reverse().concat(data.features[0]),
    categories: [...data.categories].reverse().concat(data.categories[0]),
    latestIds: [...data.latestIds].reverse().concat(data.latestIds[0]),
  };
  assert.deepEqual(atSlot(data, 2984937), atSlot(reordered, 2984937));
});

test('input arrays and records are never mutated', () => {
  const data = fixture();
  for (const key of ['articles', 'features', 'categories', 'latestIds']) {
    data[key].forEach(record => Object.freeze(record));
    Object.freeze(data[key]);
  }
  Object.freeze(data);
  assert.equal(atSlot(data, 0).archiveIds.length, 3);
});

test('latest six and every editor remark stay outside the archive at every slot', () => {
  const data = fixture(25);
  for (let slot = 0; slot < 100; slot += 1) {
    const selected = atSlot(data, slot);
    assert.equal(selected.archiveIds.length, 3);
    assert.equal(new Set(selected.archiveIds).size, 3);
    assert(selected.archiveIds.every(id => id.startsWith('article-')));
  }
  assert.equal(data.latestIds.length, 6);
});

test('hero returns an intact issue/editor pair and exhausts all issues before repeating', () => {
  const data = fixture();
  const firstCycle = Array.from({ length: data.features.length }, (_, slot) => atSlot(data, slot).featureId);
  assert.equal(new Set(firstCycle).size, data.features.length);
  firstCycle.forEach(id => {
    const feature = data.features.find(record => record.id === id);
    assert(feature);
    assert.equal(feature.articleId, `editor-${id.slice('issue-'.length)}`);
  });
  assert.equal(atSlot(data, data.features.length).featureId, firstCycle[0]);
});

test('unpaired features never become the hero', () => {
  const data = { locale: 'en', features: [{ id: 'missing-remark' }, { articleId: 'missing-issue' }, { id: '', articleId: 'empty-issue' }] };
  assert.equal(atSlot(data, 0).featureId, null);
  data.features.push({ id: 'paired-issue', articleId: 'paired-editor' });
  assert.equal(atSlot(data, 1).featureId, 'paired-issue');
});

test('explicit null editor remarks allow a cover-only missing-translation fallback', () => {
  const data = {
    locale: 'untranslated', articles: records(4),
    features: [{ id: 'issue-one', articleId: null }, { id: 'issue-two', articleId: null }],
  };
  const first = atSlot(data, 0);
  const second = atSlot(data, 1);
  assert(new Set(['issue-one', 'issue-two']).has(first.featureId));
  assert.notEqual(second.featureId, first.featureId);
  assert.equal(data.features.find(feature => feature.id === first.featureId).articleId, null);
  assert.equal(first.archiveIds.length, 3);
});

test('435 or more archive items stay absent for a full 24 hours after display ends', () => {
  for (const count of [435, 436, 437, 450, 997]) {
    const data = { locale: 'en', articles: records(count) };
    const lastSeen = new Map();
    // Start just before UTC midnight and cross several complete archive cycles.
    const firstSlot = Math.floor(Date.parse('2026-09-30T23:40:00Z') / HOME_SLOT_MS);
    for (let slot = firstSlot; slot < firstSlot + 1000; slot += 1) {
      for (const id of atSlot(data, slot).archiveIds) {
        if (lastSeen.has(id)) {
          const absentMs = (slot - lastSeen.get(id) - 1) * HOME_SLOT_MS;
          assert(absentMs >= 24 * 60 * 60 * 1000, `${count} items: ${id} absent only ${absentMs}ms`);
        }
        lastSeen.set(id, slot);
      }
    }
    assert.equal(lastSeen.size, count);
  }
});

test('432 items have 144-slot start separation but only 23h50m absence', () => {
  const data = { locale: 'en', articles: records(432) };
  assert.deepEqual(atSlot(data, 0).archiveIds, atSlot(data, 144).archiveIds);
  assert.equal((144 - 1) * HOME_SLOT_MS, 24 * 60 * 60 * 1000 - HOME_SLOT_MS);
});

test('archive does not reset or immediately repeat at UTC midnight', () => {
  const data = fixture(435);
  const midnight = Date.parse('2026-10-01T00:00:00Z');
  const before = selectHome(data, midnight - 1).archiveIds;
  const after = selectHome(data, midnight).archiveIds;
  assert(after.every(id => !before.includes(id)));
  assert.notDeepEqual(after, selectHome(data, midnight + 24 * 60 * 60 * 1000).archiveIds);
});

test('small archives use every item before a repeat, including nonmultiples of three', () => {
  for (const count of [1, 2, 3, 4, 5, 7, 13, 31, 434]) {
    const data = { locale: 'en', articles: records(count) };
    const sequence = Array.from({ length: count * 2 }, (_, slot) => atSlot(data, slot).archiveIds).flat();
    assert.equal(new Set(sequence.slice(0, count)).size, count);
    for (let position = count; position < sequence.length; position += 1) {
      assert.equal(sequence[position], sequence[position - count]);
    }
    for (let slot = 0; slot < count * 2; slot += 1) {
      const ids = atSlot(data, slot).archiveIds;
      assert.equal(ids.length, Math.min(count, 3));
      assert.equal(new Set(ids).size, ids.length);
    }
  }
});

test('category subsets rotate fairly instead of always using the first alphabetical eight', () => {
  const data = { locale: 'en', categories: records(19, 'category') };
  const counts = new Map();
  const alphabetical = data.categories.map(record => record.id).sort().slice(0, 8);
  const subsets = new Set();
  for (let slot = 0; slot < 19; slot += 1) {
    const ids = atSlot(data, slot).categoryIds;
    assert.equal(ids.length, 8);
    assert.equal(new Set(ids).size, 8);
    ids.forEach(id => counts.set(id, (counts.get(id) || 0) + 1));
    subsets.add([...ids].sort().join(','));
  }
  assert.equal(counts.size, 19);
  assert([...counts.values()].every(count => count === 8));
  assert(subsets.size > 2);
  assert.notDeepEqual(atSlot(data, 0).categoryIds, alphabetical);
});

test('each locale has a stable independent schedule', () => {
  const data = fixture();
  const en = atSlot(data, 12345);
  for (const locale of ['fr', 'zh-Hans', 'ar']) {
    const localized = { ...data, locale };
    assert.notDeepEqual(atSlot(localized, 12345).archiveIds, en.archiveIds);
    assert.deepEqual(atSlot(localized, 12345), atSlot(structuredClone(localized), 12345));
  }
});

test('empty, completely excluded, and sparse locales produce safe partial results', () => {
  assert.deepEqual(atSlot({ locale: 'empty' }, 0), { featureId: null, archiveIds: [], categoryIds: [], slot: 0 });
  const data = {
    locale: 'small', articles: [{ id: 'latest' }, { id: 'editor' }, { id: 'only-archive' }],
    latestIds: ['latest'], features: [{ id: 'issue', articleId: 'editor' }], categories: records(2, 'category'),
  };
  assert.deepEqual(atSlot(data, 42).archiveIds, ['only-archive']);
  assert.equal(atSlot(data, 42).categoryIds.length, 2);
  data.latestIds.push('only-archive');
  assert.deepEqual(atSlot(data, 42).archiveIds, []);
});

test('pre-epoch dates still return valid selections', () => {
  const data = fixture();
  const selection = selectHome(data, -1);
  assert.equal(selection.slot, -1);
  assert.equal(selection.archiveIds.length, 3);
  assert(selection.archiveIds.every(id => data.articles.some(article => article.id === id)));
});

test('invalid or implicit clocks are rejected rather than choosing visitor-dependent state', () => {
  for (const now of [undefined, null, NaN, Infinity, -Infinity, '123', 1e30]) {
    assert.throws(() => selectHome(fixture(), now), RangeError);
  }
});
