/** Exact recovery of historical aliases after a manually edited language prefix.
 * Current readable aliases have static redirects. This bounded lookup is only
 * needed for legacy addresses, whose UUIDs never appear in canonical targets.
 */
const KINDS = new Set(['articles', 'categories', 'issues']);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const UUID_IN_PATH = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
const LOCALE = /^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/;
const SLUG = /^[\p{L}\p{N}\p{M}-]+$/u;
const own = (object, key) => Object.hasOwn(object, key);
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);

function localPath(value) {
  if (typeof value !== 'string' || value.length > 4096 || !value.startsWith('/') ||
      value.startsWith('//') || !value.endsWith('/') || /%(?:2f|5c)/i.test(value)) return null;
  let decoded;
  try { decoded = decodeURIComponent(value).normalize('NFC'); }
  catch { return null; }
  if (/[\\?#%\u0000-\u001f\u007f]/.test(decoded)) return null;
  const parts = decoded.slice(1, -1).split('/');
  if (!parts.length || parts.some(part => !part || part === '.' || part === '..' || !SLUG.test(part))) return null;
  return { path: decoded, parts };
}

/** Return one validated local destination, or null for unknown/unsafe metadata. */
export function resolveLanguageRoute(pathname, index) {
  try {
    const source = localPath(pathname);
    if (!source || source.parts.length < 2 || !LOCALE.test(source.parts[0]) ||
        !record(index) || !record(index.aliases) || !record(index.targets)) return null;
    const locale = source.parts[0];
    const tail = `/${source.parts.slice(1).join('/')}/`;
    let alias = null;
    for (const [spelling, entry] of Object.entries(index.aliases)) {
      const known = localPath(spelling);
      if (!known || known.path !== tail) continue;
      if (!record(entry) || !KINDS.has(entry.kind) || typeof entry.id !== 'string' || !UUID.test(entry.id)) return null;
      if (alias && (alias.kind !== entry.kind || alias.id !== entry.id)) return null;
      alias = entry;
    }
    if (!alias || !own(index.targets, alias.kind)) return null;
    const targets = index.targets[alias.kind];
    if (!record(targets) || !own(targets, locale) || !record(targets[locale]) ||
        !own(targets[locale], alias.id)) return null;
    const destination = localPath(targets[locale][alias.id]);
    if (!destination || destination.parts[0] !== locale || UUID_IN_PATH.test(destination.path)) return null;
    const expectedSegments = alias.kind === 'categories' ? 2 : 3;
    if (destination.parts.length !== expectedSegments ||
        (alias.kind === 'issues' && destination.parts[1] !== 'issues')) return null;
    return destination.path === source.path ? null : destination.path;
  } catch {
    return null;
  }
}
