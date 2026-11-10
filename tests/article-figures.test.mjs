import test from 'node:test';
import assert from 'node:assert/strict';
import { figureLayout, figureFlowHeadings, verseLayout, contourLayout } from '../assets/article-figures.js';

const contour = (options = {}) => contourLayout({ naturalWidth: 1045, naturalHeight: 261,
  expectedWidth: 1045, expectedHeight: 261, textStart: 104, containerWidth: 750,
  fontSize: 18, ...options });

test('reviewed contour fits the complete image and keeps normal-size prose', () => {
  const result = contour();
  assert(result);
  assert(result.offset > result.height * .39);
  assert(result.offset < result.height * .5);
  assert(result.gap >= 10);
  assert.equal(contour({ containerWidth: 1400 }).height, 261);
});

test('contour keeps stacked reading for narrow columns, large type, and unsupported shapes', () => {
  for (const options of [{ containerWidth: 390 }, { containerWidth: 500 }, { fontSize: 24 },
    { wideScreen: false }, { supportsShapes: false }]) {
    assert.equal(contour(options), null);
  }
});

test('changed or missing image dimensions cannot apply an obsolete contour', () => {
  for (const options of [{ naturalWidth: 1044 }, { naturalHeight: 260 }, { naturalWidth: 0 },
    { expectedWidth: NaN }, { expectedHeight: 0 }, { textStart: 261 },
    { containerWidth: Infinity }, { fontSize: -1 }]) {
    assert.equal(contour(options), null);
  }
});

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

test('explicit poetry enlarges small artwork and uses the available line measure', () => {
  assert.deepEqual(verse({ naturalWidth: 120, naturalHeight: 137, textWidth: 360,
    fontSize: 18, enlarge: true }), { width: 240, gap: 27 });
  assert.equal(verse({ textWidth: 360, enlarge: true }).width, 320);
  assert.equal(verse({ textWidth: 530, enlarge: true }).width, 192.5);
  assert.equal(verse({ textWidth: 650, enlarge: true }), null);
  const tall = verse({ naturalWidth: 495, naturalHeight: 2049, textWidth: 360, enlarge: true });
  assert.equal(tall.width, 495 / 2049 * 600);
  const small = verse({ naturalWidth: 69, naturalHeight: 323, textWidth: 360, enlarge: true });
  assert(small.width <= 69 * 2);
  assert(small.width / 69 * 323 <= 600);
  // A credit/address selected by line breaks is not permission to enlarge it.
  assert.equal(verse({ naturalWidth: 120, naturalHeight: 137, textWidth: 360 }).width, 120);
});

test('reviewed verse quotations retain native artwork or stack without shortening lines', () => {
  const native = { naturalWidth: 241, naturalHeight: 360, textWidth: 480, preserveSize: true };
  assert.deepEqual(verse(native), { width: 241, gap: 25.5 });
  assert.equal(verse({ ...native, textWidth: 500 }), null);
  assert.equal(verse({ ...native, enlarge: true }).width, 241);
  assert.equal(verse({ ...native, wideScreen: false }), null);
});

test('very tall artwork has a proportionate box in prose and verse', () => {
  assert.equal(verse({ naturalWidth: 100, naturalHeight: 1200 }), null);
  const tall = figureLayout({ naturalWidth: 200, naturalHeight: 2000,
    containerWidth: 750, fontSize: 18 });
  assert.equal(tall, null);
});

const layout = (options = {}) => figureLayout({ naturalWidth: 422, naturalHeight: 679,
  containerWidth: 750, fontSize: 18, wideScreen: true, index: 0, ...options });

test('Courtship portraits wrap at their full native size', () => {
  assert.deepEqual(layout(), { width: 422, gap: 27, side: 'start' });
  assert.deepEqual(layout({ naturalWidth: 397, naturalHeight: 552, index: 1 }),
    { width: 397, gap: 27, side: 'end' });
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
    assert.equal(layout({ naturalWidth, naturalHeight }).width, naturalWidth);
  }
});

test('reviewed small wide photos wrap without bypassing size or readability limits', () => {
  const photo = { naturalWidth: 294, naturalHeight: 129, index: 1 };
  assert.deepEqual(layout(photo), { width: 294, gap: 27, side: 'end' });
  const wider = { ...photo, naturalHeight: 100 };
  assert.equal(layout(wider), null);
  const reviewed = { ...wider, reviewedWrap: true };
  assert.deepEqual(layout(reviewed), { width: 294, gap: 27, side: 'end' });
  assert.equal(layout({ ...reviewed, containerWidth: 1200 }).width, 294);
  for (const options of [{ wideScreen: false }, { containerWidth: 500 }, { fontSize: 24 },
    { naturalHeight: 0 }, { naturalWidth: 481 }, { naturalWidth: 725, naturalHeight: 170 }]) {
    assert.equal(layout({ ...reviewed, ...options }), null);
  }
});

test('mobile, narrow reading columns, and larger text cannot create tiny gutters', () => {
  assert.equal(layout({ wideScreen: false }), null);
  for (const containerWidth of [320, 500, 611, 650, 700]) assert.equal(layout({ containerWidth }), null);
  assert.equal(layout({ containerWidth: 750, fontSize: 24 }), null);
  for (const containerWidth of [701, 750, 900, 1200]) {
    const result = layout({ containerWidth });
    assert(result);
    assert(containerWidth - result.width - result.gap >= 18 * 14);
    assert.equal(result.width, 422);
  }
});

test('source position fixes the logical side across independent image loads and resizing', () => {
  for (let index = 0; index < 8; index++) {
    for (const containerWidth of [701, 750, 1200]) {
      assert.equal(layout({ index, containerWidth }).side, index % 2 ? 'end' : 'start');
    }
  }
});

test('all wrapping preserves native dimensions and stacks when they do not fit', () => {
  const lion = { naturalWidth: 242, naturalHeight: 429 };
  assert.deepEqual(layout(lion), { width: 242, gap: 27, side: 'start' });
  assert.equal(layout({ ...lion, containerWidth: 637 }).width, 242);
  for (const options of [{ containerWidth: 611 },
    { containerWidth: 390 }, { fontSize: 24 }, { wideScreen: false },
    { naturalWidth: 500, naturalHeight: 600 }, { naturalHeight: 900 }]) {
    assert.equal(layout({ ...lion, ...options }), null);
  }
  assert.equal(layout({ ...lion, containerWidth: 612 }).width, 242);
  assert.equal(layout({ naturalWidth: 447, naturalHeight: 322 }).width, 447);
  assert.equal(layout({ naturalWidth: 188, naturalHeight: 107 }).width, 188);
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

const ordinaryQuote = () => {
  const paragraph = { tagName: 'P', nodeType: 1, textContent: 'A faithful quotation.',
    hidden: false, matches: () => false, querySelector: () => null };
  return { tagName: 'BLOCKQUOTE', textContent: paragraph.textContent, hidden: false,
    children: [paragraph], firstElementChild: paragraph,
    childNodes: [{ nodeType: 3, textContent: '\n  ' }, paragraph,
      { nodeType: 8, textContent: 'source comment' }],
    matches: () => false, querySelector: selector => paragraph.matches(selector) ? paragraph : null };
};
const quoteFigure = (...following) => siblings({ tagName: 'FIGURE',
}, ...following);
const matchesSelector = token => selector => selector.split(',').some(value => value.trim() === token);

test('eligible figures can flow beside immediately adjacent ordinary quotations', () => {
  assert.deepEqual(figureFlowHeadings(quoteFigure(ordinaryQuote(), 'P')), []);
  assert.deepEqual(figureFlowHeadings(siblings('FIGURE', ordinaryQuote(), 'P')), []);
  assert.equal(figureFlowHeadings(quoteFigure('H2', ordinaryQuote(), 'P')), null);
  const consecutive = quoteFigure(ordinaryQuote());
  consecutive.previousElementSibling = { tagName: 'FIGURE', classList: { contains: () => false } };
  assert.equal(figureFlowHeadings(consecutive), null);
  for (const ancestor of ['.poem', '.lyrics']) {
    const figure = quoteFigure(ordinaryQuote());
    figure.closest = selector => matchesSelector(ancestor)(selector) ? {} : null;
    assert.equal(figureFlowHeadings(figure), null);
  }
});

test('reviewed quote flow still excludes verse, line breaks, media, and ambiguous structure', () => {
  const changes = [
    ['hidden quote', quote => { quote.hidden = true; }],
    ['hidden paragraph', quote => { quote.firstElementChild.hidden = true; }],
    ['empty quote', quote => { quote.textContent = quote.firstElementChild.textContent = '  '; }],
    ['poem quote', quote => { quote.matches = matchesSelector('.poem'); }],
    ['lyrics paragraph', quote => { quote.firstElementChild.matches = matchesSelector('.lyrics'); }],
    ['non-paragraph content', quote => { quote.firstElementChild.tagName = 'DIV'; }],
    ['two paragraphs', quote => {
      const paragraph = { ...quote.firstElementChild };
      quote.children.push(paragraph); quote.childNodes.push(paragraph);
    }],
    ['loose direct text', quote => { quote.childNodes.push({ nodeType: 3, textContent: 'Additional source words.' }); }],
  ];
  for (const descendant of ['br', '.poem', '.lyrics', 'blockquote', 'figure', 'img', 'ul', 'table', 'video']) {
    changes.push([`nested ${descendant}`, quote => {
      const query = selector => matchesSelector(descendant)(selector) ? {} : null;
      quote.querySelector = query; quote.firstElementChild.querySelector = query;
    }]);
  }
  for (const [label, change] of changes) {
    const quote = ordinaryQuote(); change(quote);
    assert.equal(figureFlowHeadings(quoteFigure(quote)), null, label);
  }
});

test('only contiguous opening headings with adjacent prose qualify for figure flow', () => {
  const figure = siblings('FIGURE', 'H2', 'H3', 'P', 'H2', 'P');
  assert.deepEqual(figureFlowHeadings(figure), [figure.nextElementSibling, figure.nextElementSibling.nextElementSibling]);
  for (const prose of ['P', 'OL', 'UL']) {
    assert.deepEqual(figureFlowHeadings(siblings('FIGURE', prose)), []);
    assert.equal(figureFlowHeadings(siblings('FIGURE', 'H2', prose)).length, 1);
  }
});

test('only an explicitly standalone predecessor permits an adjacent figure to wrap', () => {
  const preceding = standalone => ({ tagName: 'FIGURE', classList: {
    contains: name => standalone && name === 'article-figure--standalone',
  } });
  const figure = siblings('FIGURE', 'P');
  figure.previousElementSibling = preceding(true);
  assert.deepEqual(figureFlowHeadings(figure), []);
  figure.previousElementSibling = preceding(false);
  assert.equal(figureFlowHeadings(figure), null);
  for (const next of [preceding(false), preceding(true)]) {
    const group = siblings('FIGURE', next, 'P');
    group.previousElementSibling = preceding(true);
    assert.equal(figureFlowHeadings(group), null);
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
