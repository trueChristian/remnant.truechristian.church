import { preferredLocale, normalize, prepare, search } from './search-core.js';
const config = JSON.parse(document.querySelector('#page-config')?.textContent || '{}');
const ui = config.ui || {};
const safeStore = (key, value) => { try { localStorage.setItem(key, value); } catch {} };
const root = document.documentElement;
root.classList.add('enhanced');

if (config.rootRedirect) {
  let saved;
  try { saved = localStorage.getItem('remnant-language'); } catch {}
  const locale = preferredLocale(saved, navigator.languages || [navigator.language], config.locales);
  location.replace(`/${locale}/${location.search}${location.hash}`);
}

if (config.notFound) {
  const pathLocale = location.pathname.split('/')[1];
  const locale = config.locales.includes(pathLocale) ? pathLocale : preferredLocale(null, navigator.languages || [navigator.language], config.locales);
  const unavailable = () => location.replace(`/${locale}/404/`);
  if (config.legacyRouteIndex && /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/iu.test(location.pathname)) {
    (async () => {
      try {
        const [{ resolveLanguageRoute }, response] = await Promise.all([
          import('./language-routes.js'), fetch(config.legacyRouteIndex, { signal: AbortSignal.timeout(5000) })
        ]);
        if (!response.ok) throw new Error('Legacy routing unavailable');
        const destination = resolveLanguageRoute(location.pathname, await response.json());
        if (destination) { location.replace(destination); return; }
      } catch { /* Unknown legacy routes use the ordinary localized 404. */ }
      unavailable();
    })();
  } else {
    unavailable();
  }
}

const themeSelect = document.querySelector('[data-theme-select]');
const systemTheme = matchMedia('(prefers-color-scheme: dark)');
const applyTheme = () => {
  const mode = root.dataset.themeMode || 'system';
  root.dataset.theme = mode === 'system' ? (systemTheme.matches ? 'dark' : 'light') : mode;
  if (themeSelect) themeSelect.value = mode;
};
themeSelect?.addEventListener('change', () => {
  root.dataset.themeMode = themeSelect.value;
  safeStore('remnant-theme', themeSelect.value);
  applyTheme();
});
systemTheme.addEventListener('change', applyTheme);
applyTheme();
document.querySelector('[data-language-select]')?.addEventListener('change', event => {
  const selected = event.target.selectedOptions[0];
  safeStore('remnant-language', selected.dataset.locale);
  location.assign(selected.value);
});

const copyButton = document.querySelector('[data-copy-markdown]');
copyButton?.addEventListener('click', async () => {
  const fallback = document.querySelector('#markdown-fallback');
  const status = document.querySelector('#copy-status');
  copyButton.disabled = true;
  try {
    const response = await fetch(copyButton.dataset.copyMarkdown);
    if (!response.ok) throw new Error('Download unavailable');
    const text = await response.text();
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(text);
      status.textContent = ui.copied;
    } catch {
      fallback.hidden = false;
      const textarea = fallback.querySelector('textarea');
      textarea.value = text;
      textarea.focus(); textarea.select();
      status.textContent = ui.copy_fallback;
    }
  } catch { status.textContent = ui.copy_error; }
  finally { copyButton.disabled = false; }
});

if (config.homeData) {
  import('./home.js').then(({ enhanceHome }) => enhanceHome(config.homeData, config.homeUi)).catch(() => {});
}

function markedText(container, text, query) {
  // Highlight complete original graphemes; never inject article HTML.
  const terms = query.trim().split(/\s+/u).filter(Boolean).map(normalize);
  if (!terms.length) { container.textContent = text; return; }
  const segments = typeof Intl.Segmenter === 'function'
    ? [...new Intl.Segmenter(config.locale, { granularity: 'grapheme' }).segment(text)].map(x => x.segment)
    : Array.from(text);
  let normalized = '', offsets = [];
  segments.forEach((segment, index) => {
    const part = normalize(segment);
    for (let i = 0; i < part.length; i++) offsets.push(index);
    normalized += part;
  });
  const marked = new Set();
  for (const term of terms) {
    let position = normalized.indexOf(term);
    while (position !== -1) {
      for (let i = position; i < position + term.length; i++) if (offsets[i] !== undefined) marked.add(offsets[i]);
      position = normalized.indexOf(term, position + Math.max(1, term.length));
    }
  }
  let node, previous;
  segments.forEach((segment, index) => {
    const isMarked = marked.has(index);
    if (isMarked !== previous) {
      node = isMarked ? document.createElement('mark') : document.createTextNode('');
      container.append(node); previous = isMarked;
    }
    if (isMarked) node.textContent += segment; else node.appendData(segment);
  });
}

const searchForm = document.querySelector('[data-search-form]');
if (searchForm) {
  const query = searchForm.elements.q;
  const category = searchForm.elements.category;
  const issue = searchForm.elements.issue;
  const results = document.querySelector('#search-results');
  const status = document.querySelector('#search-status');
  let worker, sequence = 0, timer, fallbackRecords, resultPage = 0;
  const render = data => {
    if (data.id !== sequence) return;
    results.replaceChildren();
    if (data.error) { status.textContent = ui.search_error; return; }
    status.textContent = ui.results_count.replace('{count}', String(data.total));
    if (!data.total) {
      const empty = document.createElement('p'); empty.className = 'empty-message'; empty.textContent = ui.no_results; results.append(empty); return;
    }
    data.results.forEach(record => {
      const item = document.createElement('article'); item.className = 'search-result';
      const meta = document.createElement('div'); meta.className = 'eyebrow'; meta.textContent = record.categories[0] || '';
      const title = document.createElement('h2'), link = document.createElement('a'); link.href = record.url;
      markedText(link, record.title, query.value); title.append(link);
      const snippet = document.createElement('p'); markedText(snippet, record.snippet, query.value);
      const foot = document.createElement('small'); foot.textContent = [record.author, record.issue].filter(Boolean).join(' · ');
      item.append(meta, title, snippet, foot); results.append(item);
    });
    if (data.offset > 0 || data.hasMore) {
      const navigation = document.createElement('nav'); navigation.className = 'pagination'; navigation.setAttribute('aria-label', ui.search);
      if (data.offset > 0) {
        const previous = document.createElement('button'); previous.type = 'button'; previous.className = 'button button--quiet'; previous.textContent = ui.prev;
        previous.addEventListener('click', () => { resultPage--; run('pushState', true); }); navigation.append(previous);
      }
      const count = document.createElement('span'); count.textContent = `${Math.floor(data.offset / 40) + 1} / ${Math.ceil(data.total / 40)}`; navigation.append(count);
      if (data.hasMore) {
        const next = document.createElement('button'); next.type = 'button'; next.className = 'button button--quiet'; next.textContent = ui.next;
        next.addEventListener('click', () => { resultPage++; run('pushState', true); }); navigation.append(next);
      }
      results.append(navigation);
    }
  };
  const run = async (historyMode, preservePage = false) => {
    if (!preservePage) resultPage = 0;
    const params = new URLSearchParams();
    for (const control of [query, category, issue]) if (control.value.trim()) params.set(control.name, control.value.trim());
    if (resultPage) params.set('page', String(resultPage + 1));
    const url = `${location.pathname}${params.size ? `?${params}` : ''}`;
    if (historyMode && url !== `${location.pathname}${location.search}`) history[historyMode]({}, '', url);
    const id = ++sequence;
    if (!params.size) { status.textContent = ui.search_hint; results.replaceChildren(); return; }
    status.textContent = ui.searching;
    const message = { id, offset: resultPage * 40, url: config.searchIndex, query: query.value, filters: { category: config.categoryFilters?.[category.value] || category.value, issue: config.issueFilters?.[issue.value] || issue.value } };
    if ('Worker' in window) {
      try {
        if (!worker) {
          worker = new Worker('/assets/search-worker.js', { type: 'module' });
          worker.onmessage = event => render(event.data);
          worker.onerror = () => { worker.terminate(); worker = undefined; render({ id: sequence, error: true }); };
        }
        worker.postMessage(message); return;
      } catch { /* Accessible fallback for browsers without module workers. */ }
    }
    try {
      if (!fallbackRecords) {
        const response = await fetch(config.searchIndex);
        if (!response.ok) throw new Error('Index unavailable');
        fallbackRecords = prepare(await response.json());
      }
      render({ id, ...search(fallbackRecords, message.query, message.filters, message.offset) });
    } catch { render({ id, error: true }); }
  };
  const fromURL = () => {
    const params = new URLSearchParams(location.search);
    const readableFilter = (value, mapping) => Object.hasOwn(mapping || {}, value) ? value : Object.keys(mapping || {}).find(slug => mapping[slug] === value) || value;
    query.value = params.get('q') || '';
    category.value = readableFilter(params.get('category') || '', config.categoryFilters);
    issue.value = readableFilter(params.get('issue') || '', config.issueFilters);
    resultPage = Math.max(0, (parseInt(params.get('page'), 10) || 1) - 1);
    run('replaceState', true);
  };
  query.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => run('pushState'), 220); });
  category.addEventListener('change', () => run('pushState'));
  issue.addEventListener('change', () => run('pushState'));
  searchForm.addEventListener('submit', event => { event.preventDefault(); clearTimeout(timer); run('pushState'); });
  searchForm.addEventListener('reset', () => { clearTimeout(timer); setTimeout(() => run('pushState'), 0); });
  addEventListener('popstate', fromURL);
  fromURL();
}
