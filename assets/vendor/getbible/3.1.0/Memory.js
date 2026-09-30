/**
 * GetBible loader 3.1.0 Memory interface, hardened for Remnant.
 * Upstream 30-day cache and keys are retained. Storage is optional, corrupt or
 * future-dated entries are misses, and a bounded page-local cache is available.
 * See LICENSE.md and PROVENANCE.md in this directory.
 */
export class Memory {
  static ONE_MONTH_IN_MILLISECONDS = 30 * 24 * 60 * 60 * 1000;
  static #items = new Map();
  static #key(reference, translation) { return `getBible-${translation}-${reference}`; }
  static #remember(key, item) {
    this.#items.delete(key);
    this.#items.set(key, item);
    if (this.#items.size > 128) this.#items.delete(this.#items.keys().next().value);
  }
  static set(reference, translation, data) {
    const key = this.#key(reference, translation);
    const item = { data, timestamp: Date.now() };
    this.#remember(key, item);
    try { globalThis.localStorage.setItem(key, JSON.stringify(item)); } catch { /* optional */ }
  }
  static async get(reference, translation) {
    const key = this.#key(reference, translation);
    let item = this.#items.get(key);
    if (!item) {
      try { item = JSON.parse(globalThis.localStorage.getItem(key)); } catch { /* miss */ }
    }
    const now = Date.now();
    if (item && typeof item.timestamp === 'number' && item.timestamp <= now &&
        item.timestamp > now - this.ONE_MONTH_IN_MILLISECONDS && item.data &&
        typeof item.data === 'object' && !Array.isArray(item.data)) {
      this.#remember(key, item);
      return item.data;
    }
    this.remove(reference, translation);
    return null;
  }
  static remove(reference, translation) {
    const key = this.#key(reference, translation);
    this.#items.delete(key);
    try { globalThis.localStorage.removeItem(key); } catch { /* optional */ }
  }
  static clearMemory() { this.#items.clear(); }
}
