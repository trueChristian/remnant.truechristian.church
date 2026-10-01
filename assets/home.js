import { HOME_SLOT_MS, selectHome } from './home-selection.js';

// All HTML in this digest-addressed, same-origin file is rendered and escaped by
// the static generator. No user input, article body, or external HTML is injected.
async function loadData(url) {
  if ('DecompressionStream' in globalThis) {
    try {
      const response = await fetch(`${url}.gz`);
      if (!response.ok || !response.body) throw new Error('Compressed previews unavailable');
      return await new Response(response.body.pipeThrough(new DecompressionStream('gzip'))).json();
    } catch { /* Plain JSON supports older browsers and hosts with gzip transforms. */ }
  }
  const response = await fetch(url);
  if (!response.ok) throw new Error('Homepage previews unavailable');
  return response.json();
}

export async function enhanceHome(url) {
  // Keep the static HTML intact on network/decompression/schema failure.
  const data = await loadData(url);
  if (data.schema !== 1 || data.locale !== document.documentElement.lang ||
      !['features', 'articles', 'categories'].every(key => Array.isArray(data[key]))) return;
  const feature = document.querySelector('[data-home-feature]');
  const archive = document.querySelector('[data-home-archive]');
  const categories = document.querySelector('[data-home-categories]');
  const byId = key => new Map(data[key].map(row => [row.id, row]));
  const featureRows = byId('features'), articleRows = byId('articles'), categoryRows = byId('categories');
  let timer;
  const replace = (element, key, markup) => {
    if (!element || element.dataset.selection === key) return;
    // Never remove the reader's keyboard focus. This island catches up on blur.
    if (element.contains(document.activeElement)) return;
    element.innerHTML = markup;
    element.dataset.selection = key;
  };
  const update = () => {
    clearTimeout(timer);
    if (!document.hidden) {
      const selection = selectHome(data, Date.now());
      const selectedFeature = featureRows.get(selection.featureId);
      if (selectedFeature) {
        replace(feature, selection.featureId, selectedFeature.html);
        if (feature?.dataset.selection === selection.featureId) feature.dataset.featureId = selection.featureId;
      }
      replace(archive, selection.archiveIds.join(','), selection.archiveIds.map(id =>
        `<div data-home-article-id="${id}">${articleRows.get(id).html}</div>`).join(''));
      replace(categories, selection.categoryIds.join(','), selection.categoryIds.map(id => categoryRows.get(id).html).join(''));
      document.documentElement.dataset.homeSlot = String(selection.slot);
    }
    // Recompute the shared clock slot after suspended tabs/sleep; no drifting interval.
    timer = setTimeout(update, HOME_SLOT_MS - (Date.now() % HOME_SLOT_MS) + 20);
  };
  document.addEventListener('visibilitychange', update);
  window.addEventListener('pageshow', update);
  document.addEventListener('focusout', () => setTimeout(update, 0));
  window.addEventListener('pagehide', () => clearTimeout(timer));
  update();
}
