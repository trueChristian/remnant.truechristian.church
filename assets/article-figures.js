/** Size-aware figure wrapping; source nodes, image attributes, and captions stay intact. */
const controllers = new WeakMap();
const WIDE_SCREEN = '(min-width: 48rem)';

/** A readable measure takes priority over wrapping, including in narrow desktop columns. */
export function figureLayout({ naturalWidth, naturalHeight, containerWidth, fontSize = 18,
  wideScreen = true, index = 0 }) {
  if (!wideScreen || ![naturalWidth, naturalHeight, containerWidth, fontSize]
    .every(value => Number.isFinite(value) && value > 0)) return null;
  if (containerWidth < fontSize * 34) return null;

  const width = Math.min(naturalWidth, 320, containerWidth * 0.38);
  const gap = Math.max(24, fontSize * 1.5);
  const ratio = naturalWidth / naturalHeight;
  // Large portraits can be scaled down; naturally small square-ish images need no upscaling.
  // Landscape photography and multi-image compositions retain their full reading-column width.
  if (!(ratio <= 0.9 || (naturalWidth <= width && ratio <= 1.25))) return null;
  if (containerWidth - width - gap < fontSize * 18) return null;
  return { width, gap, side: index % 2 === 0 ? 'start' : 'end' };
}

export function initArticleFigures(document) {
  if (controllers.has(document)) return controllers.get(document);
  const window = document.defaultView;
  const articles = [...document.querySelectorAll('.prose article[data-article-id]')];
  const records = [];
  const containers = new Set();
  for (const article of articles) {
    const figures = [...article.querySelectorAll('figure')];
    if (!figures.length) continue;
    article.classList.add('article-figures');
    figures.forEach((figure, index) => {
      const parent = figure.parentElement;
      // Leave illustrations inside quotes, lists, and callouts in their original layout.
      if (parent !== article && (parent.tagName !== 'SECTION' ||
        parent.closest('aside, blockquote, li, table, figure'))) return;
      const images = figure.querySelectorAll('img');
      if (images.length !== 1) return;
      if (parent !== article) parent.classList.add('article-figure-section');
      containers.add(parent);
      records.push({ figure, image: images[0], parent, index });
    });
  }
  if (!records.length) return null;

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
    for (const { figure, image, parent, index } of records) {
      const layout = image.complete ? figureLayout({
        ...measurements.get(parent), naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight, wideScreen: media.matches, index,
      }) : null;
      figure.classList.toggle('article-figure--wrap', Boolean(layout));
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
  };
  const schedule = () => {
    if (frame === null) frame = window.requestAnimationFrame(update);
  };
  // Both cached and delayed/lazy images work; an error or a new source removes old wrapping.
  for (const { image } of records) {
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
