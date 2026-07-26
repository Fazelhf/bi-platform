/**
 * Namespaced browser storage.
 *
 * This build can be served from a path on a domain that already hosts the v1
 * platform (ntpbi.ir/crm alongside ntpbi.ir). localStorage is scoped to the
 * **origin**, not the path, so both apps see the same keys: unprefixed
 * `access`/`refresh`/`me` would mean signing into one app silently signs you
 * out of the other, and the two would fight over the theme as well.
 *
 * Every key this app stores goes through here.
 */
const PREFIX = import.meta.env.VITE_STORAGE_PREFIX ?? "ntp.";

export const store = {
  get(key: string): string | null {
    return localStorage.getItem(PREFIX + key);
  },
  set(key: string, value: string): void {
    localStorage.setItem(PREFIX + key, value);
  },
  remove(key: string): void {
    localStorage.removeItem(PREFIX + key);
  },
  getJSON<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem(PREFIX + key);
      return raw ? (JSON.parse(raw) as T) : fallback;
    } catch {
      return fallback;
    }
  },
  setJSON(key: string, value: unknown): void {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  },
};
