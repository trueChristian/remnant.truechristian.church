/* Runs before styles paint. Safe if browser storage is unavailable. */
(function () {
  const root = document.documentElement;
  let mode = 'system';
  try { mode = localStorage.getItem('remnant-theme') || 'system'; } catch {}
  if (!['system', 'light', 'dark'].includes(mode)) mode = 'system';
  root.dataset.themeMode = mode;
  root.dataset.theme = mode === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : mode;
})();
