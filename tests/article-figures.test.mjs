import test from 'node:test';
import assert from 'node:assert/strict';
import { figureLayout, figureFlowHeadings, verseLayout } from '../assets/article-figures.js';

const verse = (options = {}) => verseLayout({ naturalWidth: 320, naturalHeight: 420,
  containerWidth: 750, textWidth: 530, fontSize: 17, ...options });

test('verse illustration uses spare space without shortening printed lines', () => {
  assert.deepEqual(verse(), { width: 180, gap: 25.5 });
  const snug = verse({ textWidth: 600 });
  assert.equal(snug.width, 122.5);
  assert(snug.width + snug.gap + 600 < 750);
  assert.equal(verse({ textWidth: 650 }), null);
  assert.equal(verse({ naturalWidth: 80, naturalHeight: 120 }).width, 80);
});

test('narrow screens, long translated lines, and landscape verse artwork stack', () => {
  for (const options of [{ wideScreen: false }, { containerWidth: 390 },
    { textWidth: 1200 }, { naturalWidth: 1200, naturalHeight: 600 },
    { naturalWidth: 0 }, { textWidth: NaN }, { fontSize: Infinity }]) {
    assert.equal(verse(options), null);
  }
});

test('very tall artwork has a proportionate box in prose and verse', () => {
  assert.equal(verse({ naturalWidth: 100, naturalHeight: 1200 }), null);
  const tall = figureLayout({ naturalWidth: 200, naturalHeight: 2000,
    containerWidth: 750, fontSize: 18 });
  assert.equal(tall, null);
});

const layout = (options = {}) => figureLayout({ naturalWidth: 422, naturalHeight: 679,
  containerWidth: 750, fontSize: 18, wideScreen: true, index: 0, ...options });

test('Courtship portraits wrap with ample text measure and no upscaling', () => {
  assert.deepEqual(layout(), { width: 285, gap: 27, side: 'start' });
  assert.deepEqual(layout({ naturalWidth: 397, naturalHeight: 552, index: 1 }),
    { width: 285, gap: 27, side: 'end' });
  assert.equal(layout({ naturalWidth: 120, naturalHeight: 180 }).width, 120);
});

test('wide photography and large square images keep the stacked layout', () => {
  for (const [naturalWidth, naturalHeight] of [[1200, 700], [750, 750], [250, 100]]) {
    assert.equal(layout({ naturalWidth, naturalHeight }), null);
  }
  assert.equal(layout({ naturalWidth: 240, naturalHeight: 240 }).width, 240);
});

test('small landscape and square illustrations can share readable prose', () => {
  for (const [naturalWidth, naturalHeight] of [[374, 235], [422, 300], [300, 322], [400, 400]]) {
    assert.equal(layout({ naturalWidth, naturalHeight }).width, 285);
  }
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

const siblings = (...nodes) => nodes.reduceRight((nextElementSibling, node) => ({
  tagName: typeof node === 'string' ? node : node.tagName,
  textContent: 'Readable content', ...(typeof node === 'object' ? node : {}), nextElementSibling,
}), null);

test('only contiguous opening headings with adjacent prose qualify for figure flow', () => {
  const figure = siblings('FIGURE', 'H2', 'H3', 'P', 'H2', 'P');
  assert.deepEqual(figureFlowHeadings(figure), [figure.nextElementSibling, figure.nextElementSibling.nextElementSibling]);
  for (const prose of ['P', 'OL', 'UL']) {
    assert.deepEqual(figureFlowHeadings(siblings('FIGURE', prose)), []);
    assert.equal(figureFlowHeadings(siblings('FIGURE', 'H2', prose)).length, 1);
  }
});

test('orphan figures and headings before barriers remain stacked', () => {
  assert.equal(figureFlowHeadings(siblings('FIGURE')), null);
  assert.equal(figureFlowHeadings(siblings('FIGURE', 'H2')), null);
  for (const barrier of ['FIGURE', 'BLOCKQUOTE', 'ASIDE', 'TABLE', 'HR', 'SECTION',
    { tagName: 'P', textContent: '  ' }, { tagName: 'P', hidden: true }]) {
    assert.equal(figureFlowHeadings(siblings('FIGURE', barrier, 'P')), null);
    assert.equal(figureFlowHeadings(siblings('FIGURE', 'H2', barrier, 'P')), null);
  }
  for (const heading of [{ tagName: 'H2', hidden: true }, { tagName: 'H3', textContent: '' }]) {
    assert.equal(figureFlowHeadings(siblings('FIGURE', heading, 'P')), null);
  }
});
