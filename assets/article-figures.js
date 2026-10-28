/** Size-aware figure wrapping; source nodes, image attributes, and captions stay intact. */
const controllers = new WeakMap();
const WIDE_SCREEN = '(min-width: 48rem)';

/** A readable measure takes priority over wrapping, including in narrow desktop columns. */
export function figureLayout({ naturalWidth, naturalHeight, containerWidth, fontSize = 18,
  wideScreen = true, index = 0 }) {
  if (!wideScreen || ![naturalWidth, naturalHeight, containerWidth, fontSize]
    .every(value => Number.isFinite(value) && value > 0)) return null;
  if (containerWidth < fontSize * 34) return null;

  const gap = Math.max(24, fontSize * 1.5);
  const ratio = naturalWidth / naturalHeight;
  // Very tall illustrations must not reserve a broad, mostly empty float box.
  const width = Math.min(naturalWidth, 320, containerWidth * 0.38, ratio * fontSize * 26);
  // Small photographs and illustrations can sit beside prose too. Large landscapes,
  // banners, and reviewed text-bearing images keep the full reading column.
  if (!(ratio <= 0.9 || (naturalWidth <= 480 && ratio <= 1.75))) return null;
  if (width < Math.min(naturalWidth, 100)) return null;
  if (containerWidth - width - gap < fontSize * 18) return null;
  return { width, gap, side: index % 2 === 0 ? 'start' : 'end' };
}

/** Verse keeps its printed line lengths; artwork uses only the remaining space. */
export function verseLayout({ naturalWidth, naturalHeight, containerWidth, textWidth,
  fontSize = 18, wideScreen = true }) {
  if (!wideScreen || ![naturalWidth, naturalHeight, containerWidth, textWidth, fontSize]
    .every(value => Number.isFinite(value) && value > 0)) return null;
  const ratio = naturalWidth / naturalHeight;
  if (ratio > 1.75) return null;
  const gap = Math.max(24, fontSize * 1.5);
  const width = Math.min(naturalWidth, 180, ratio * 300, containerWidth - textWidth - gap - 2);
  if (width < Math.min(naturalWidth, 100)) return null;
  return { width, gap };
}

function verseMeasure(text) {
  const copy = text.cloneNode(true);
  copy.classList.add('article-verse-measure');
  copy.setAttribute('aria-hidden', 'true');
  copy.inert = true;
  copy.removeAttribute('id');
  for (const element of copy.querySelectorAll('[id]')) element.removeAttribute('id');
  text.parentElement.append(copy);
  const width = copy.getBoundingClientRect().width;
  copy.remove();
  return width;
}

/** Only a figure's opening heading run belongs beside it; later sections still clear. */
export function figureFlowHeadings(figure) {
  const headings = [];
  let next = figure.nextElementSibling;
  while (next && /^H[1-6]$/.test(next.tagName)) {
    if (next.hidden || !next.textContent.trim()) return null;
    headings.push(next);
    next = next.nextElementSibling;
  }
  // Without adjacent readable prose there is no useful wrap. Quotes, tables,
  // callouts, another figure, and section boundaries keep their stacked layout.
  if (!next || next.hidden || !/^(P|UL|OL)$/.test(next.tagName) ||
    !next.textContent.trim()) return null;
  if (next.matches?.('.poem, .lyrics') || next.querySelector?.('br')) return null;
  return headings;
}

export function initArticleFigures(document) {
  if (controllers.has(document)) return controllers.get(document);
  const window = document.defaultView;
  const articles = [...document.querySelectorAll('.prose article[data-article-id]')];
  const records = [];
  const verseRecords = [];
  const containers = new Set();
  for (const article of articles) {
    const figures = [...article.querySelectorAll('figure')];
    if (!figures.length) continue;
    article.classList.add('article-figures');
    for (const row of article.querySelectorAll('.article-verse-row')) {
      const figure = row.querySelector(':scope > figure');
      const text = row.querySelector(':scope > .article-verse-text');
      const image = figure?.querySelector('img');
      if (!image || !text) continue;
      containers.add(row);
      verseRecords.push({ row, image, text });
    }
    figures.forEach((figure, index) => {
      if (figure.classList.contains('article-figure--standalone') ||
        figure.closest('.article-verse-row')) return;
      const parent = figure.parentElement;
      // Leave illustrations inside quotes, lists, and callouts in their original layout.
      if (parent !== article && (parent.tagName !== 'SECTION' ||
        parent.closest('aside, blockquote, li, table, figure'))) return;
      const images = figure.querySelectorAll('img');
      if (images.length !== 1) return;
      // Consecutive floats can squeeze one line between their margin boxes even when
      // clear: both keeps the images apart. Preserve stacked source groups instead.
      if (figure.previousElementSibling?.tagName === 'FIGURE' ||
        figure.nextElementSibling?.tagName === 'FIGURE') return;
      const headings = figureFlowHeadings(figure);
      if (!headings) return;
      if (parent !== article) parent.classList.add('article-figure-section');
      containers.add(parent);
      records.push({ figure, image: images[0], parent, index, headings });
    });
  }
  if (!records.length && !verseRecords.length) return null;

  const media = window.matchMedia(WIDE_SCREEN);
  let frame = null;
  const update = () => {
    frame = null;
    const measurements = new Map([...containers].map(parent => {
      const style = window.getComputedStyle(parent);
      return [parent, {
        containerWidth: parent.clientWidth - parseFloat(style.paddingLeft || 0) - parseFloat(style.paddingRight || 0),
        fontSize: parseFloat(style.fontSize),
      }];
    }));
    for (const { figure, image, parent, index, headings } of records) {
      const layout = image.complete ? figureLayout({
        ...measurements.get(parent), naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight, wideScreen: media.matches, index,
      }) : null;
      figure.classList.toggle('article-figure--wrap', Boolean(layout));
      for (const heading of headings) {
        heading.classList.toggle('article-figure-heading', Boolean(layout));
      }
      for (const side of ['start', 'end']) {
        figure.classList.toggle(`article-figure--${side}`, layout?.side === side);
      }
      if (layout) {
        figure.style.setProperty('--article-figure-width', `${layout.width}px`);
        figure.style.setProperty('--article-figure-gap', `${layout.gap}px`);
      } else {
        figure.style.removeProperty('--article-figure-width');
        figure.style.removeProperty('--article-figure-gap');
      }
    }
    for (const { row, image, text } of verseRecords) {
      const layout = image.complete && media.matches ? verseLayout({
        ...measurements.get(row), naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight, textWidth: verseMeasure(text),
      }) : null;
      row.classList.toggle('article-verse-row--aside', Boolean(layout));
      if (layout) {
        row.style.setProperty('--article-verse-image-width', `${layout.width}px`);
        row.style.setProperty('--article-verse-gap', `${layout.gap}px`);
      } else {
        row.style.removeProperty('--article-verse-image-width');
        row.style.removeProperty('--article-verse-gap');
      }
    }
  };
  const schedule = () => {
    if (frame === null) frame = window.requestAnimationFrame(update);
  };
  // Both cached and delayed/lazy images work; an error or a new source removes old wrapping.
  for (const { image } of [...records, ...verseRecords]) {
    image.addEventListener('load', schedule);
    image.addEventListener('error', schedule);
  }
  window.addEventListener('resize', schedule, { passive: true });
  media.addEventListener('change', schedule);
  const widths = new WeakMap();
  const observer = window.ResizeObserver ? new window.ResizeObserver(entries => {
    for (const entry of entries) {
      if (widths.get(entry.target) !== entry.contentRect.width) {
        widths.set(entry.target, entry.contentRect.width);
        schedule();
      }
    }
  }) : null;
  for (const parent of containers) observer?.observe(parent);
  document.fonts?.ready.then(schedule);
  const controller = { update };
  controllers.set(document, controller);
  update();
  return controller;
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => initArticleFigures(document), { once: true });
  } else initArticleFigures(document);
}
