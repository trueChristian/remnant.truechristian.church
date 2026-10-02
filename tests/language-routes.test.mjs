import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveLanguageRoute } from '../assets/language-routes.js';

const ARTICLE = '00000000-0000-4000-8000-000000000001';
const OTHER = '00000000-0000-4000-8000-000000000002';
const CATEGORY = '00000000-0000-4000-8000-000000000003';
const ISSUE = '00000000-0000-4000-8000-000000000004';

function fixture() {
  return {
    aliases: {
      [`/faith/article-${ARTICLE}/`]: { kind: 'articles', id: ARTICLE },
      [`/previous-category/article-${ARTICLE}/`]: { kind: 'articles', id: ARTICLE },
      [`/articles/${ARTICLE}/`]: { kind: 'articles', id: ARTICLE },
      [`/category-${CATEGORY}/`]: { kind: 'categories', id: CATEGORY },
      [`/issues/issue-${ISSUE}/`]: { kind: 'issues', id: ISSUE },
    },
    targets: {
      articles: {
        en: { [ARTICLE]: '/en/faith/faithful-life/', [OTHER]: '/en/faith/other-life/' },
        af: { [ARTICLE]: '/af/geloof/getroue-lewe/', [OTHER]: '/af/geloof/ander-lewe/' },
        'zh-Hans': { [ARTICLE]: '/zh-Hans/信仰/信仰-生命/' },
      },
      categories: { af: { [CATEGORY]: '/af/geloof/' } },
      issues: { af: { [ISSUE]: '/af/issues/lente-2024/' } },
    },
  };
}

test('a manually changed legacy language prefix resolves the corresponding localized article', () => {
  const index = fixture();
  assert.equal(resolveLanguageRoute(`/af/faith/article-${ARTICLE}/`, index), '/af/geloof/getroue-lewe/');
  assert.equal(resolveLanguageRoute(`/en/articles/${ARTICLE}/`, index), '/en/faith/faithful-life/');
});

test('previous categories keep the exact article identity instead of guessing from titles', () => {
  const index = fixture();
  assert.equal(resolveLanguageRoute(`/af/previous-category/article-${ARTICLE}/`, index), '/af/geloof/getroue-lewe/');
  assert.equal(resolveLanguageRoute(`/af/previous-category/article-${OTHER}/`, index), null);
});

test('category and issue identities resolve their own localized canonical routes', () => {
  assert.equal(resolveLanguageRoute(`/af/category-${CATEGORY}/`, fixture()), '/af/geloof/');
  assert.equal(resolveLanguageRoute(`/af/issues/issue-${ISSUE}/`, fixture()), '/af/issues/lente-2024/');
});

test('UTF-8 and percent-encoded Unicode routes return readable normalized targets', () => {
  const index = fixture();
  index.aliases[`/信仰/article-${ARTICLE}/`] = { kind: 'articles', id: ARTICLE };
  const input = `/zh-Hans/${encodeURIComponent('信仰')}/article-${ARTICLE}/`;
  assert.equal(resolveLanguageRoute(input, index), '/zh-Hans/信仰/信仰-生命/');
  index.targets.articles['zh-Hans'][ARTICLE] = `/zh-Hans/${encodeURIComponent('信仰')}/${encodeURIComponent('信仰-生命')}/`;
  assert.equal(resolveLanguageRoute(input, index), '/zh-Hans/信仰/信仰-生命/');
});

test('source and stored alias spellings normalize to NFC without changing case', () => {
  const index = fixture();
  index.aliases[`/cafe\u0301/article-${ARTICLE}/`] = { kind: 'articles', id: ARTICLE };
  assert.equal(resolveLanguageRoute(`/af/caf%C3%A9/article-${ARTICLE}/`, index), '/af/geloof/getroue-lewe/');
  assert.equal(resolveLanguageRoute(`/af/CAF%C3%89/article-${ARTICLE}/`, index), null);
});

test('unknown locales, aliases, kinds, and removed identities do not redirect', () => {
  assert.equal(resolveLanguageRoute(`/zz/faith/article-${ARTICLE}/`, fixture()), null);
  assert.equal(resolveLanguageRoute(`/af/unknown/article-${ARTICLE}/`, fixture()), null);
  const removed = fixture();
  delete removed.targets.articles.af[ARTICLE];
  assert.equal(resolveLanguageRoute(`/af/faith/article-${ARTICLE}/`, removed), null);
  const badKind = fixture();
  badKind.aliases[`/faith/article-${ARTICLE}/`].kind = 'unknown';
  assert.equal(resolveLanguageRoute(`/af/faith/article-${ARTICLE}/`, badKind), null);
});

test('malformed encodings, traversal, encoded separators, and foreign URLs are rejected', () => {
  for (const input of [
    `/af/faith/article-${ARTICLE}/%`, `/af/faith/%E0%A4%A/`, `/af/faith/%ED%A0%80/`,
    `/af/../faith/article-${ARTICLE}/`, `/af/%2e%2e/faith/article-${ARTICLE}/`,
    `/af/faith%2fextra/article-${ARTICLE}/`, `/af/faith%5cextra/article-${ARTICLE}/`,
    `/af/faith%252fextra/article-${ARTICLE}/`, `/af//article-${ARTICLE}/`,
    `//af/faith/article-${ARTICLE}/`, `https://example.org/af/faith/article-${ARTICLE}/`,
    `/af/faith/article-${ARTICLE}/?query`, `/af/faith/article-${ARTICLE}/#fragment`,
    `/af/faith/article-${ARTICLE}%00/`, `/af/faith/article-${ARTICLE}%0a/`,
  ]) assert.equal(resolveLanguageRoute(input, fixture()), null, input);
});

test('unsafe target URLs and targets in a different locale are rejected', () => {
  for (const target of [
    'https://example.org/af/geloof/getroue-lewe/', '//example.org/af/geloof/getroue-lewe/',
    '/en/faith/faithful-life/', '/af/../getroue-lewe/', '/af/geloof/./',
    '/af/geloof/getroue-lewe/?query', '/af/geloof/getroue-lewe/#fragment',
    '/af/geloof/getroue-lewe%5c/', '/af/geloof/getroue-lewe%2f/',
    '/af/geloof/getroue-lewe%252f/', '/af/geloof/getroue-lewe%00/',
    '/af/geloof/getroue-lewe', '/af//getroue-lewe/', '/af/geloof/getroue-lewe%/',
  ]) {
    const index = fixture();
    index.targets.articles.af[ARTICLE] = target;
    assert.equal(resolveLanguageRoute(`/af/faith/article-${ARTICLE}/`, index), null, target);
  }
});

test('a canonical target can never retain any UUID in its path', () => {
  for (const target of [`/af/geloof/article-${ARTICLE}/`, `/af/category-${CATEGORY}/getroue-lewe/`,
    `/af/geloof/article-${OTHER.toUpperCase()}/`]) {
    const index = fixture();
    index.targets.articles.af[ARTICLE] = target;
    assert.equal(resolveLanguageRoute(`/af/faith/article-${ARTICLE}/`, index), null);
  }
});

test('malformed metadata and inherited records cannot supply redirects', () => {
  const pathname = `/af/faith/article-${ARTICLE}/`;
  for (const index of [null, [], {}, { aliases: [], targets: {} }, { aliases: {}, targets: [] }]) {
    assert.equal(resolveLanguageRoute(pathname, index), null);
  }
  for (const replacement of [null, [], 'article', { kind: 'articles', id: 'invalid' }]) {
    const index = fixture();
    index.aliases[`/faith/article-${ARTICLE}/`] = replacement;
    assert.equal(resolveLanguageRoute(pathname, index), null);
  }
  const inherited = fixture();
  inherited.targets.articles.af = Object.create({ [ARTICLE]: '/af/geloof/getroue-lewe/' });
  assert.equal(resolveLanguageRoute(pathname, inherited), null);
});

test('conflicting Unicode-equivalent metadata aliases are rejected', () => {
  const index = fixture();
  index.aliases[`/café/article-${ARTICLE}/`] = { kind: 'articles', id: ARTICLE };
  index.aliases[`/cafe\u0301/article-${ARTICLE}/`] = { kind: 'articles', id: OTHER };
  assert.equal(resolveLanguageRoute(`/af/café/article-${ARTICLE}/`, index), null);
});

test('canonical destinations must match the route kind', () => {
  const index = fixture();
  index.targets.categories.af[CATEGORY] = '/af/geloof/another-segment/';
  index.targets.issues.af[ISSUE] = '/af/geloof/lente-2024/';
  assert.equal(resolveLanguageRoute(`/af/category-${CATEGORY}/`, index), null);
  assert.equal(resolveLanguageRoute(`/af/issues/issue-${ISSUE}/`, index), null);
});

test('an already canonical destination cannot cause a redirect loop', () => {
  const index = fixture();
  index.aliases['/geloof/getroue-lewe/'] = { kind: 'articles', id: ARTICLE };
  assert.equal(resolveLanguageRoute('/af/geloof/getroue-lewe/', index), null);
});

test('route lookup leaves published metadata unchanged', () => {
  const index = fixture();
  const before = JSON.stringify(index);
  assert.equal(resolveLanguageRoute(`/af/faith/article-${ARTICLE}/`, index), '/af/geloof/getroue-lewe/');
  assert.equal(JSON.stringify(index), before);
});
