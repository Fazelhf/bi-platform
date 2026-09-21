import { computed, ref, watch } from "vue";

/**
 * Which columns a list shows, remembered per list and per browser.
 *
 * Kept in localStorage on purpose: it is a personal convenience, not data.
 * Losing it (a private window, cleared storage) costs nothing but a click,
 * so every read and write is guarded and the list works without it.
 */
export function useListPrefs(listKey: string, columns: { key: string; label: string; default?: boolean }[]) {
  const storageKey = `ntp.crm.cols.${listKey}`;
  const defaults = columns.filter((c) => c.default !== false).map((c) => c.key);

  function read(): string[] {
    try {
      const raw = localStorage.getItem(storageKey);
      const saved = raw ? (JSON.parse(raw) as string[]) : null;
      // A column added since the list was saved still shows up.
      return saved && Array.isArray(saved) ? saved.filter((k) => columns.some((c) => c.key === k)) : defaults;
    } catch {
      return defaults;
    }
  }

  const visible = ref<string[]>(read());
  watch(visible, (v) => {
    try { localStorage.setItem(storageKey, JSON.stringify(v)); } catch { /* not important */ }
  }, { deep: true });

  const shown = (key: string) => visible.value.includes(key);
  function toggle(key: string) {
    visible.value = shown(key) ? visible.value.filter((k) => k !== key) : [...visible.value, key];
  }
  function reset() { visible.value = [...defaults]; }

  return { visible, shown, toggle, reset, columns: computed(() => columns) };
}

/**
 * Server-side sort state: `ordering` is what the API takes (`-amount`), and a
 * click cycles a column through descending → ascending → off. Descending
 * first because on a money column that is the question — «the biggest».
 */
export function useSort(initial = "") {
  const ordering = ref(initial);
  function sortBy(key: string) {
    if (ordering.value === `-${key}`) ordering.value = key;
    else if (ordering.value === key) ordering.value = "";
    else ordering.value = `-${key}`;
  }
  function dir(key: string): "asc" | "desc" | "" {
    if (ordering.value === `-${key}`) return "desc";
    if (ordering.value === key) return "asc";
    return "";
  }
  return { ordering, sortBy, dir };
}
