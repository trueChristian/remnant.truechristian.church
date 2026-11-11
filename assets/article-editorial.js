/** Progressive enhancement for explicitly reviewed compositions, not generic article rewrites. */
const controllers = new WeakMap();

function measureLines(text) {
  const copy = text.cloneNode(true);
  copy.classList.add('article-editorial-measure');
  copy.inert = true;
  copy.setAttribute('aria-hidden', 'true');
  copy.removeAttribute('id');
  for (const node of copy.querySelectorAll('[id]')) node.removeAttribute('id');
  text.parentElement.append(copy);
  const width = copy.getBoundingClientRect().width;
  copy.remove();
  return width;
}

/** Keep the existing verse widths, but let stanzas—not tall artwork—set row heights.
 * The figures stay in source order. Only their visual vertical offsets change.
 */
function arrangeContinuousVerse(article) {
  const window = article.ownerDocument.defaultView;
  const rows = [...article.querySelectorAll(':scope > .article-verse-row')];
  const figures = rows.map(row => row.querySelector(':scope > figure'));
  const reset = () => {
    article.classList.remove('article-verse-continuous--active');
    article.style.removeProperty('--continuous-verse-height');
    article.style.removeProperty('--continuous-stanza-gap');
    for (const row of rows) row.style.removeProperty('--continuous-figure-top');
  };
  const font = parseFloat(window.getComputedStyle(article).fontSize);
  if (!rows.length || article.clientWidth < font * 34 ||
      window.getComputedStyle(article).direction !== 'ltr' ||
      rows.some(row => !row.classList.contains('article-verse-row--aside')) ||
      figures.some(figure => !figure || figure.querySelector('figcaption') ||
        !figure.querySelector('img')?.complete || !figure.querySelector('img')?.naturalWidth)) {
    reset(); return;
  }
  article.classList.add('article-verse-continuous--active');
  const box = article.getBoundingClientRect();
  const stanzas = [...article.querySelectorAll(':scope > p.poem, :scope > .article-verse-row > .article-verse-text > p.poem')];
  if (!stanzas.length) { reset(); return; }
  article.style.setProperty('--continuous-stanza-gap', `${parseFloat(window.getComputedStyle(stanzas[0]).fontSize) * 1.55}px`);
  const lines = [];
  for (const stanza of stanzas) {
    const walker = article.ownerDocument.createTreeWalker(stanza, window.NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const range = article.ownerDocument.createRange();
      range.selectNodeContents(walker.currentNode);
      for (const line of range.getClientRects()) if (line.width && line.height) lines.push(line);
    }
  }
  if (!lines.length) { reset(); return; }
  const gap = Math.max(24, font * 1.5), clearance = Math.max(12, font * .65);
  let bottom = -gap;
  for (let index = 0; index < rows.length; index++) {
    const image = figures[index].querySelector('img');
    // This width is set by the existing verseLayout, measured from the same
    // source stanzas as before. Never resize the cups to compact the poem.
    const width = parseFloat(rows[index].style.getPropertyValue('--article-verse-image-width'));
    if (!Number.isFinite(width) || width <= 0 || width >= box.width) { reset(); return; }
    const height = width * image.naturalHeight / image.naturalWidth;
    const left = box.right - width;
    let top = Math.max(0, bottom + gap);
    // Earliest nonoverlapping position above/beside the next stanzas. Moving
    // an illustration never changes a paragraph's width, line breaks or gap.
    for (let pass = 0; pass <= lines.length; pass++) {
      const collision = lines.find(line => line.right > left - clearance &&
        line.left < box.right && line.top < box.top + top + height + clearance &&
        line.bottom > box.top + top - clearance);
      if (!collision) break;
      top = collision.bottom - box.top + clearance;
    }
    rows[index].style.setProperty('--continuous-figure-top', `${top}px`);
    bottom = top + height;
  }
  const textBottom = Math.max(...stanzas.map(stanza => stanza.getBoundingClientRect().bottom)) - box.top;
  article.style.setProperty('--continuous-verse-height', `${Math.max(textBottom, bottom)}px`);
}

export function initEditorialLayouts(document) {
  if (controllers.has(document)) return controllers.get(document);
  const window = document.defaultView;
  const rows = [...document.querySelectorAll('.prose article :is(.article-editorial-verse, .article-editorial-prose, .article-quote-frame, figure[data-reader-enlarge])')];
  const continuous = [...document.querySelectorAll('.prose article[data-reader-continuous-verse]')];
  if (!rows.length && !continuous.length) return null;
  const updateVerse = () => continuous.forEach(arrangeContinuousVerse);
  const media = window.matchMedia('(min-width: 48rem)');
  const images = [...new Set(rows.flatMap(row => [...row.querySelectorAll('img')]))];
  let frame = null;
  const update = () => {
    frame = null;
    for (const row of rows) {
      const art = row.querySelector(':scope > .article-editorial-art');
      const text = row.querySelector(':scope > .article-editorial-text');
      const pictures = [...row.querySelectorAll('img')];
      const width = row.clientWidth;
      const font = parseFloat(window.getComputedStyle(row).fontSize);
      const gap = Math.max(24, font * 1.5);
      const loaded = pictures.every(image => image.complete && image.naturalWidth > 0 && image.naturalHeight > 0);
      if (row.hasAttribute('data-reader-enlarge')) {
        const displayWidth = Number(row.dataset.readerEnlarge);
        const expected = loaded && pictures.length === 1 &&
          pictures[0].naturalWidth === Number(row.dataset.sourceWidth) &&
          pictures[0].naturalHeight === Number(row.dataset.sourceHeight);
        row.classList.toggle('article-standalone--enlarged', expected);
        if (expected) row.style.setProperty('--standalone-display-width', `${displayWidth}px`);
        else row.style.removeProperty('--standalone-display-width');
        continue;
      }
      let active = media.matches && loaded;
      row.style.setProperty('--editorial-gap', `${gap}px`);
      if (row.classList.contains('article-editorial-verse')) {
        const native = row.classList.contains('article-editorial-verse--native');
        const artWidth = loaded ? (native ? pictures[0].naturalWidth : Math.min(160, ...pictures.map(image => image.naturalWidth * 2))) : 0;
        const textWidth = active ? measureLines(text) + 1 : 0;
        active = active && textWidth + gap + artWidth <= width;
        row.style.setProperty('--editorial-art-width', `${artWidth}px`);
        row.style.setProperty('--editorial-text-width', `${textWidth}px`);
      } else if (row.classList.contains('article-editorial-prose')) {
        const reviewed = Number(row.dataset.displayWidth);
        const expected = !reviewed || (pictures.length === 1 &&
          pictures[0].naturalWidth === Number(row.dataset.sourceWidth) &&
          pictures[0].naturalHeight === Number(row.dataset.sourceHeight));
        const artWidth = reviewed || pictures.reduce((sum, image) => sum + image.naturalWidth, 0) + (pictures.length - 1) * 18;
        active = active && expected && width >= font * 34 && width - artWidth - gap >= font * 14;
        if (expected) row.style.setProperty('--editorial-art-width', `${artWidth}px`);
        else row.style.removeProperty('--editorial-art-width');
        if (pictures.length === 2 && loaded) {
          art.style.setProperty('--editorial-pair-columns', pictures.map(image => `${image.naturalWidth}fr`).join(' '));
        }
      } else {
        const quote = row.querySelector(':scope > blockquote');
        const size = parseFloat(window.getComputedStyle(quote).fontSize);
        active = active && pictures.length === 2 && width >= font * 34 &&
          width - Math.max(...pictures.map(image => image.naturalWidth)) - gap >= size * 14 &&
          Boolean(window.CSS?.supports('shape-outside', 'inset(1px 0 0 0)'));
        row.classList.toggle('article-editorial--active', active);
        if (active) {
          const [first, last] = pictures;
          row.style.setProperty('--frame-left-width', `${first.naturalWidth}px`);
          row.style.setProperty('--frame-left-height', `${first.naturalHeight}px`);
          row.style.setProperty('--frame-right-width', `${last.naturalWidth}px`);
          row.style.setProperty('--frame-right-height', `${last.naturalHeight}px`);
          const fits = height => {
            row.style.setProperty('--frame-height', `${height}px`);
            return quote.getBoundingClientRect().height <= height + .1;
          };
          let low = Math.max(first.naturalHeight, last.naturalHeight);
          let high = first.naturalHeight + last.naturalHeight + gap;
          for (let pass = 0; pass < 6 && !fits(high); pass++) {
            high = Math.max(high + gap, Math.ceil(quote.getBoundingClientRect().height));
          }
          // Keep the lower illustration against the quotation, not hundreds of
          // pixels below it. Increasing height only moves its exclusion down.
          for (let pass = 0; pass < 12 && high - low > 1; pass++) {
            const middle = (low + high) / 2;
            if (fits(middle)) high = middle;
            else low = middle;
          }
          active = fits(Math.ceil(high));
        }
      }
      row.classList.toggle('article-editorial--active', active);
    }
  };
  const schedule = () => { if (frame === null) frame = window.requestAnimationFrame(update); };
  for (const image of images) {
    image.addEventListener('load', schedule);
    image.addEventListener('error', schedule);
  }
  window.addEventListener('resize', schedule, { passive: true });
  media.addEventListener('change', schedule);
  const observed = new WeakMap();
  const observer = window.ResizeObserver ? new window.ResizeObserver(entries => {
    for (const entry of entries) {
      const signature = `${entry.contentRect.width}:${window.getComputedStyle(entry.target).fontSize}`;
      if (observed.get(entry.target) !== signature) {
        observed.set(entry.target, signature);
        schedule();
      }
    }
  }) : null;
  for (const row of rows) {
    observer?.observe(row);
    for (const text of row.querySelectorAll('.poem, blockquote')) observer?.observe(text);
  }
  document.fonts?.ready.then(schedule);
  document.fonts?.addEventListener?.('loadingdone', schedule);
  const controller = { update, updateVerse };
  controllers.set(document, controller);
  update();
  return controller;
}
