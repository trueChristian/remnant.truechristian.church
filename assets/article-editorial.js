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

export function initEditorialLayouts(document) {
  if (controllers.has(document)) return controllers.get(document);
  const window = document.defaultView;
  const rows = [...document.querySelectorAll('.prose article :is(.article-editorial-verse, .article-editorial-prose, .article-quote-frame)')];
  if (!rows.length) return null;
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
  const controller = { update };
  controllers.set(document, controller);
  update();
  return controller;
}
