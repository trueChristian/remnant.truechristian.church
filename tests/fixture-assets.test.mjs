import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fixtureAsset } from './browser/fixture-assets.mjs';

const root = path.resolve('assets');

test('isolated article fixtures serve the production entry module unchanged', () => {
  const response = fixtureAsset('/assets/article-figures.js');
  assert.deepEqual(response, { path: path.join(root, 'article-figures.js'), contentType: 'text/javascript' });
  assert.match(fs.readFileSync(response.path, 'utf8'), /initArticleFigures/);
});

test('relative editorial imports resolve to the real module rather than a fixture 404', () => {
  const entry = 'http://127.0.0.1:8080/assets/article-figures.js';
  const source = fs.readFileSync(fixtureAsset(new URL(entry).pathname).path, 'utf8');
  assert.match(source, /import\s+\{\s*initEditorialLayouts\s*\}\s+from\s+["']\.\/article-editorial\.js["']/);
  const response = fixtureAsset(new URL('./article-editorial.js', entry).pathname);
  assert.deepEqual(response, { path: path.join(root, 'article-editorial.js'), contentType: 'text/javascript' });
  assert.match(fs.readFileSync(response.path, 'utf8'), /export function initEditorialLayouts/);
});

test('nested production modules and styles retain their correct content types', () => {
  assert.deepEqual(fixtureAsset('/assets/vendor/getbible/3.1.0/Api.js'), {
    path: path.join(root, 'vendor/getbible/3.1.0/Api.js'), contentType: 'text/javascript',
  });
  assert.deepEqual(fixtureAsset('/assets/article-figures.css'), {
    path: path.join(root, 'article-figures.css'), contentType: 'text/css',
  });
});

test('unrelated requests, missing files and path traversal are not served as assets', () => {
  for (const request of [undefined, '', '/', '/picture.svg', '/figures.js', '/assets/',
    '/assets/missing-fixture-file.js', '/assets/../tests/browser/fixture-assets.mjs',
    '/assets/../../outside.js', '/assets//etc/passwd', '/assets/vendor/getbible/3.1.0/LICENSE.md']) {
    assert.equal(fixtureAsset(request), null, String(request));
  }
});

test('all isolated article fixtures use the canonical module URL and shared asset responder', () => {
  for (const name of ['contour-openings', 'figure-quotes', 'native-figure-wrap',
    'native-verse-quote', 'verse-image-sizing']) {
    const source = fs.readFileSync(`tests/browser/${name}.spec.mjs`, 'utf8');
    assert.match(source, /import \{ fixtureAsset \} from '\.\/fixture-assets\.mjs';/, name);
    assert.match(source, /const asset = fixtureAsset\(path(?:name)?\);/, name);
    assert.match(source, /if \(asset\) return route\.fulfill\(asset\);/, name);
    assert.match(source, /src="\/assets\/article-figures\.js"/, name);
    assert.doesNotMatch(source, /src="\/figures\.js"/, name);
  }
});
