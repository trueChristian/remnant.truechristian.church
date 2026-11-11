import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const assetDirectory = fileURLToPath(new URL('../../assets/', import.meta.url));
const contentTypes = new Map([['.js', 'text/javascript'], ['.css', 'text/css']]);

/** Serve production assets, including relative module imports, inside isolated fixtures. */
export function fixtureAsset(pathname) {
  if (typeof pathname !== 'string' || !pathname.startsWith('/assets/')) return null;
  const filename = path.resolve(assetDirectory, pathname.slice('/assets/'.length));
  const relative = path.relative(assetDirectory, filename);
  if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) return null;
  const contentType = contentTypes.get(path.extname(filename));
  if (!contentType || !fs.existsSync(filename) || !fs.statSync(filename).isFile()) return null;
  // Do not let a fixture request escape the asset directory through a symlink.
  const realRelative = path.relative(fs.realpathSync(assetDirectory), fs.realpathSync(filename));
  if (realRelative === '..' || realRelative.startsWith(`..${path.sep}`) || path.isAbsolute(realRelative)) return null;
  return { path: filename, contentType };
}
