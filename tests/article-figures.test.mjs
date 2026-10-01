import test from 'node:test';
import assert from 'node:assert/strict';
import { figureLayout } from '../assets/article-figures.js';

const layout = (options = {}) => figureLayout({ naturalWidth: 422, naturalHeight: 679,
  containerWidth: 750, fontSize: 18, wideScreen: true, index: 0, ...options });

test('Courtship portraits wrap with ample text measure and no upscaling', () => {
  assert.deepEqual(layout(), { width: 285, gap: 27, side: 'start' });
  assert.deepEqual(layout({ naturalWidth: 397, naturalHeight: 552, index: 1 }),
    { width: 285, gap: 27, side: 'end' });
  assert.equal(layout({ naturalWidth: 120, naturalHeight: 180 }).width, 120);
});

test('wide photography and large square images keep the stacked layout', () => {
  for (const [naturalWidth, naturalHeight] of [[1200, 700], [422, 300], [750, 750], [250, 100]]) {
    assert.equal(layout({ naturalWidth, naturalHeight }), null);
  }
  assert.equal(layout({ naturalWidth: 240, naturalHeight: 240 }).width, 240);
});

test('mobile, narrow reading columns, and larger text cannot create tiny gutters', () => {
  assert.equal(layout({ wideScreen: false }), null);
  for (const containerWidth of [320, 500, 611]) assert.equal(layout({ containerWidth }), null);
  assert.equal(layout({ containerWidth: 750, fontSize: 24 }), null);
  for (const containerWidth of [612, 650, 750, 900, 1200]) {
    const result = layout({ containerWidth });
    assert(result);
    assert(containerWidth - result.width - result.gap >= 18 * 18);
    assert(result.width <= 320);
  }
});

test('source position fixes the logical side across independent image loads and resizing', () => {
  for (let index = 0; index < 8; index++) {
    for (const containerWidth of [612, 750, 1200]) {
      assert.equal(layout({ index, containerWidth }).side, index % 2 ? 'end' : 'start');
    }
  }
});

test('missing, broken, and invalid image dimensions never produce a float', () => {
  for (const field of ['naturalWidth', 'naturalHeight', 'containerWidth', 'fontSize']) {
    for (const value of [0, -1, NaN, Infinity, undefined]) assert.deepEqual(layout({ [field]: value }),
      field === 'fontSize' && value === undefined ? layout() : null);
  }
});
