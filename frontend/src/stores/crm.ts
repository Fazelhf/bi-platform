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

/** The lookup fetch that is currently running, shared by concurrent callers. */
let inFlight: Promise<CrmOptions | null> | null = null;

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
    /**
     * Bumped whenever something is saved from outside the page showing it —
     * the global «ثبت جدید» button, chiefly. A list cannot know that a deal
     * was just created over the top of it, and a rep who adds a customer and
     * does not see it appear concludes the save failed and adds it again.
     */
    revision: 0,
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

    /**
     * The one distinction the whole section is arranged around.
     *
     * A manager supervises and therefore sees the team; a کارشناس works their
     * own book and the API answers only with their rows. Every difference in
     * the UI — which filters appear, which columns are worth their width,
     * whether «کارشناس» is a question or a statement — reads this rather than
     * re-deriving it from role names.
     */
    isManager: (state) => !!state.me?.is_manager,
    seesAll: (state) => !!state.me?.sees_all,
    /** In a sales department but linked to no salesperson row. */
    unlinked: (state) => !!state.me?.unlinked,

    /**
     * Which department's customer file is on screen.
     *
     * The three sales departments now share these screens and keep separate
     * books, so «CRM» on its own no longer says whose customers these are.
     * Empty for the CEO and admins, who read all three and for whom naming
     * one would be a lie.
     */
    bookLabel: (state) => state.me?.channel_label ?? "",
  },

  actions: {

    async loadOptions(force = false) {
      if (this.options && !force) return this.options;
      // The `options` guard above only catches callers that arrive *after* the
      // first one finished. The shell and the page it contains both ask on the
      // same tick, so both saw null and both fetched — four requests where two
      // were needed, on the connection least able to spare them. Hold the
      // in-flight promise and hand it to whoever else asks meanwhile.
      if (inFlight && !force) return inFlight;
      this.loading = true;
      inFlight = (async () => {
        try {
          const [options, me] = await Promise.all([crmApi.options(), crmApi.me()]);
          this.options = options;
          this.me = me;
          if (!this.filters.month && this.options.months?.length) {
            this.filters.month = this.options.months[0].key;
          }
          return this.options;
        } finally {
          this.loading = false;
          inFlight = null;
        }
      })();
      return inFlight;
    },

    /** Tell every open list that the data under it changed. */
    bump() {
      this.revision += 1;
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
