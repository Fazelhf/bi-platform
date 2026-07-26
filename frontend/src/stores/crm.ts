import { defineStore } from "pinia";
import { crmApi, type CrmMe, type CrmOptions, type Drill } from "@/api/crm";

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
