import { prepare, search } from './search-core.js';
let records;
let loading;
self.onmessage = async ({ data }) => {
  const { id, url, query, filters, offset = 0 } = data;
  try {
    if (!loading) loading = (async () => {
      if ('DecompressionStream' in self) {
        try {
          const compressed = await fetch(`${url}.gz`);
          if (!compressed.ok) throw new Error('Compressed index unavailable');
          return await new Response(compressed.body.pipeThrough(new DecompressionStream('gzip'))).json();
        } catch { /* Older/intermediary servers: use the plain JSON fallback. */ }
      }
      const response = await fetch(url);
      if (!response.ok) throw new Error('Index unavailable');
      return response.json();
    })().then(data => { records = prepare(data); });
    await loading;
    self.postMessage({ id, ...search(records, query, filters, offset) });
  } catch {
    loading = undefined;
    self.postMessage({ id, error: true });
  }
};
