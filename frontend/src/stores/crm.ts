import { defineStore } from "pinia";
import { crmApi, type CrmMe, type CrmOptions, type Drill } from "@/api/crm";
import { CRM_KEY } from "@/api/client";
import { store as storage } from "@/lib/storage";
import { apiError } from "@/components/crm/formError";

/**
 * Shared CRM state: the filter bar and the lookup lists.
 *
 * The filter lives in the store rather than in each page so moving between
 * داشبورد → گزارش‌ها → مراحل فروش keeps the same window and the same rep selected.
 * Losing the filter on every navigation was the single most annoying thing
 * about the tool this replaces.
 */
export type RangeKey = "current" | "last3" | "last6" | "last12" | "month" | "custom";

interface Filters {
  range: RangeKey;
  month: string;        // "1405-4" when range === "month"
  date_from: string;
  date_to: string;
  owner: number | "";
  group: number | "";
  source: number | "";
  province: number | "";
}

export const useCrmStore = defineStore("crm", {
  state: () => ({
    options: null as CrmOptions | null,
    me: null as CrmMe | null,
    loading: false,
    // Demo lock. `unlocked === null` means "not checked yet" — distinct from
    // a confirmed false, so the guard can tell "ask the server" from "locked".
    unlocked: null as boolean | null,
    gateChecking: false,
    filters: {
      range: "last6",
      month: "",
      date_from: "",
      date_to: "",
      owner: "",
      group: "",
      source: "",
      province: "",
    } as Filters,
    // Drill-down drawer, driven from anywhere in the CRM.
    drill: null as { drill: Drill; title: string } | null,
  }),

  getters: {
    /** Filters as API query params — the single place the mapping happens. */
    query(state): Record<string, any> {
      const f = state.filters;
      const q: Record<string, any> = {};
      const months = state.options?.months ?? [];

      if (f.range === "custom") {
        if (f.date_from) q.date_from = f.date_from;
        if (f.date_to) q.date_to = f.date_to;
      } else if (f.range === "month" && f.month) {
        const m = months.find((x) => x.key === f.month);
        if (m) {
          q.date_from = m.date_from;
          q.date_to = m.date_to;
        }
      } else {
        const SPANS: Record<string, number> = { current: 1, last3: 3, last6: 6, last12: 12 };
        const span = SPANS[f.range] ?? 6;
        // `months` is newest-first, so a span of N is the first N entries.
        const slice = months.slice(0, span);
        if (slice.length) {
          q.date_from = slice[slice.length - 1].date_from;
          q.date_to = slice[0].date_to;
        }
      }
      for (const k of ["owner", "group", "source", "province"] as const) {
        if (f[k] !== "" && f[k] !== null) q[k] = f[k];
      }
      return q;
    },

    rangeLabel(state): string {
      const f = state.filters;
      const months = state.options?.months ?? [];
      if (f.range === "month") {
        return months.find((m) => m.key === f.month)?.label ?? "—";
      }
      if (f.range === "custom") return `${f.date_from || "…"} تا ${f.date_to || "…"}`;
      return {
        current: "ماه جاری", last3: "۳ ماه اخیر",
        last6: "۶ ماه اخیر", last12: "۱۲ ماه اخیر",
      }[f.range] ?? "";
    },

    employeeName: (state) => (id: number | null) =>
      state.options?.employees.find((e) => e.id === id)?.name ?? "—",

    canEdit: (state) => !!state.me?.can_edit,
  },

  actions: {
    /**
     * Ask the server whether the stored key still opens the demo. The client
     * cannot judge that itself — the key is signed and expires — so the
     * answer always comes from /crm/gate/.
     */
    async checkGate(force = false): Promise<boolean> {
      if (this.unlocked !== null && !force) return this.unlocked;
      if (!storage.get(CRM_KEY)) {
        this.unlocked = false;
        return false;
      }
      this.gateChecking = true;
      try {
        this.unlocked = (await crmApi.gateStatus()).unlocked;
      } catch {
        this.unlocked = false;
      } finally {
        this.gateChecking = false;
      }
      if (!this.unlocked) storage.remove(CRM_KEY);
      return this.unlocked;
    },

    /** Exchange the demo password for a key. Returns "" on success. */
    async unlock(password: string): Promise<string> {
      try {
        const { key } = await crmApi.unlock(password);
        storage.set(CRM_KEY, key);
        this.unlocked = true;
        return "";
      } catch (e) {
        this.unlocked = false;
        storage.remove(CRM_KEY);
        return apiError(e);
      }
    },

    lock() {
      storage.remove(CRM_KEY);
      this.unlocked = false;
      // Drop everything the demo loaded, so locking really closes it.
      this.options = null;
      this.me = null;
      this.drill = null;
    },

    async loadOptions(force = false) {
      if (this.options && !force) return this.options;
      this.loading = true;
      try {
        const [options, me] = await Promise.all([crmApi.options(), crmApi.me()]);
        this.options = options;
        this.me = me;
        if (!this.filters.month && this.options.months?.length) {
          this.filters.month = this.options.months[0].key;
        }
      } finally {
        this.loading = false;
      }
      return this.options;
    },

    openDrill(drill: Drill, title: string) {
      if (!drill || !drill.kind) return;
      this.drill = { drill, title };
    },

    closeDrill() {
      this.drill = null;
    },

    reset() {
      this.filters.owner = "";
      this.filters.group = "";
      this.filters.source = "";
      this.filters.province = "";
      this.filters.range = "last6";
    },
  },
});
