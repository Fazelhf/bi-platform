/**
 * Budget API. Money comes back as strings so Rial figures stay exact; only
 * percentages and counts are numbers.
 *
 * The budget is not an island: a سرفصل's actual is the cash ledger's figure
 * for its category unless finance keyed one (which replaces it), and the
 * sales forecast reads the sales section's approved figures per channel.
 */
import api from "./client";
import type { CashCategory, FinanceSettings } from "./finance";

export type Direction = "in" | "out";
/** How a variance reads — never infer it from the sign of the number. */
export type Verdict = "good" | "bad" | "on-track";
export type BudgetStatus = "draft" | "approved" | "closed";

/** A cash category with its place in the tree. */
export type TreeCategory = CashCategory & {
  parent: number | null;
  parent_code: string;
  is_leaf: boolean;
  needs_credit_line: boolean;
};

export interface Budget {
  id: number;
  title: string;
  jalali_year: number;
  start_period: number;
  start_label: string;
  end_period: number;
  end_label: string;
  is_active: boolean;
  note: string;
  line_count: number;
  month_count: number;
  approved_count: number;
  created_at: string;
}

export interface BudgetLine {
  id: number;
  budget: number;
  category: number;
  category_name: string;
  category_code: string;
  parent_name: string;
  credit_line: number | null;
  counterparty: string;
  direction: Direction;
  direction_label: string;
  label: string;
  sort_order: number;
  is_active: boolean;
  note: string;
}

export interface GridCell {
  amount_rial: string;
  /** What was approved; null while the month is still a draft. */
  baseline_rial: string | null;
  variance_note: string;
}

export interface GridMonth {
  budget_period_id: number;
  period_id: number;
  label: string;
  status: BudgetStatus;
  status_label: string;
  approved_at: string | null;
  days: number;
}

export interface GridLine extends BudgetLine {
  /** Keyed by budget_period_id. */
  cells: Record<string, GridCell>;
}

/** One sales channel's forecast row in the plan grid. */
export interface GridSalesRow {
  channel: string;
  label: string;
  /** Keyed by budget_period_id; actual_rial is what the sales section recorded. */
  cells: Record<string, { amount_rial: string; baseline_rial: string | null; actual_rial: string }>;
}

export interface BudgetGrid {
  budget: Budget;
  months: GridMonth[];
  lines: GridLine[];
  sales: GridSalesRow[];
  unit: FinanceSettings;
  can_edit: boolean;
}

export interface SaveCell {
  budget_period_id: number;
  line_id: number;
  amount_rial?: string;
  variance_note?: string;
  /** Why an approved figure moved — kept in the change history. */
  reason?: string;
}

export interface VarianceCell {
  budget_rial: string;
  baseline_rial: string | null;
  actual_rial: string;
  variance_rial: string;
  variance_pct: number | null;
  verdict: Verdict;
  is_material: boolean;
}

export interface VarianceRow extends VarianceCell {
  kind: "category" | "line" | "unbudgeted";
  line_id: number | null;
  label: string;
  code: string;
  direction: Direction;
  credit_line: string;
  note: string;
  depth: number;
  /** Where the actual came from: keyed by finance, or the cash ledger. */
  source?: ActualSource;
}

export type ActualSource = "keyed" | "ledger" | "none";

export interface SalesBlock {
  rows: (VarianceCell & { channel: string; label: string })[];
  total: VarianceCell;
  has_actuals: boolean;
}

export interface VarianceReport {
  budget: { id: number; title: string };
  period: { id: number; label: string; kind: string };
  month: { id: number; label: string };
  budget_period_id: number | null;
  status: BudgetStatus;
  status_label: string;
  approved_at: string | null;
  rows: VarianceRow[];
  totals: { in: VarianceCell; out: VarianceCell; net: VarianceCell };
  thresholds: { pct: string; rial: string };
  unbudgeted_count: number;
  /** False when nothing — keyed, ledger or sales — exists for the month yet. */
  has_actuals: boolean;
  sources: Record<ActualSource, number>;
  /** Forecast sales per channel against the sales section — never in the cash totals. */
  sales: SalesBlock;
}

export interface SeriesPoint {
  period_id: number;
  label: string;
  status: BudgetStatus;
  budget_in: string;
  budget_out: string;
  actual_in: string;
  actual_out: string;
  budget_net: string;
  actual_net: string;
  cumulative_budget: string;
  cumulative_actual: string;
  has_actuals: boolean;
  budget_sales: string;
  actual_sales: string;
}

export interface BudgetSeries {
  budget: { id: number; title: string };
  points: SeriesPoint[];
}

export interface WaterfallStep {
  label: string;
  code: string;
  direction: Direction;
  /** Signed by the effect on cash, so the steps add up to the gap. */
  effect_rial: string;
  verdict: Verdict;
  is_material: boolean;
}

export interface Waterfall {
  budget: { id: number; title: string };
  period: { id: number; label: string; kind: string };
  start_rial: string;
  end_rial: string;
  steps: WaterfallStep[];
}

/** One سرفصل on the finance team's monthly actuals sheet. */
export interface ActualEntryLine extends VarianceCell {
  line_id: number;
  label: string;
  category_name: string;
  parent_name: string;
  counterparty: string;
  direction: Direction;
  /** Whether anything was keyed for it in this period. */
  entered: boolean;
  note: string;
  /** The cash ledger's figure — the actual while nothing is keyed. */
  ledger_rial: string | null;
  source: ActualSource;
}

export interface ActualEntrySheet {
  budget: { id: number; title: string };
  period: { id: number; label: string; kind: string };
  month: { id: number; label: string; days: number };
  line_count: number;
  lines: ActualEntryLine[];
  totals: { in: VarianceCell; out: VarianceCell };
  sales: SalesBlock;
  can_edit: boolean;
  unit: FinanceSettings;
}

// ---- Excel import -----------------------------------------------------------

export interface ImportMonth {
  key: string;
  year: number;
  month: number;
  label: string;
  has_budget: boolean;
  has_actual: boolean;
}

export interface ImportRow {
  row: number;
  label: string;
  direction: Direction;
  include: boolean;
  is_total: boolean;
  /** For a total: true when it equals the rows it is made of (so skipping it loses nothing). */
  check?: boolean | null;
  reason: string;
  warnings: string[];
  /** line: an existing سرفصل of the budget · category: an existing category · new · sales: a channel's forecast */
  match: "line" | "category" | "new" | "sales";
  channel: string | null;
  channel_label?: string;
  category_id: number | null;
  category_name: string;
  category_parent: string;
  new_parent_id: number | null;
  new_parent_name: string;
  /** Keyed by month key «1405-07». */
  budget: Record<string, string | null>;
  actual: Record<string, string | null>;
}

export interface ImportAnalysis {
  sheet: string;
  sheets: string[];
  header_row: number;
  label_column: string;
  duplicate_columns: string[];
  months: ImportMonth[];
  rows: ImportRow[];
  year: number;
  can_plan: boolean;
  can_actual: boolean;
}

export interface ImportOptions {
  parts: ("budget" | "actual")[];
  mode: "merge" | "replace";
  title?: string;
  rows: { row: number; include?: boolean; direction?: Direction; category_id?: number | null }[];
}

export interface ImportResult {
  budget_id: number;
  budget_title: string;
  created: boolean;
  lines: number;
  new_categories: number;
  written_budget: number;
  written_actual: number;
  written_forecasts: number;
  cleared_budget: number;
  cleared_actual: number;
  skipped_negative: number;
}

export interface BudgetStats {
  lines: number;
  months: number;
  amounts: number;
  actuals: number;
  forecasts: number;
  approved: number;
}

export type ClearWhat = "plan" | "actuals" | "sales" | "lines" | "all";

/** Top-level groups × months, for the variance heatmap. */
export interface BudgetHeatmapData {
  budget: { id: number; title: string };
  months: { period_id: number; label: string; has_actuals: boolean }[];
  groups: { key: string; code: string; label: string; direction: Direction }[];
  cells: (VarianceCell & { group: string; period_id: number })[];
}

const many = <T>(data: any): T[] => data.results ?? data;

export const budgetApi = {
  async list(): Promise<Budget[]> {
    const { data } = await api.get("/finance/budgets/", { params: { page_size: 100 } });
    return many<Budget>(data);
  },
  async create(payload: Partial<Budget>): Promise<Budget> {
    const { data } = await api.post("/finance/budgets/", payload);
    return data;
  },
  async update(id: number, payload: Partial<Budget>): Promise<Budget> {
    const { data } = await api.patch(`/finance/budgets/${id}/`, payload);
    return data;
  },
  async remove(id: number) {
    await api.delete(`/finance/budgets/${id}/`);
  },
  async approve(budgetId: number, periodId: number) {
    const { data } = await api.post(`/finance/budgets/${budgetId}/approve/`, {
      period: periodId,
    });
    return data as { status: BudgetStatus; status_label: string; stamped: number };
  },

  /** A line nobody set up in advance, created on the spot under its group. */
  async createCategory(payload: {
    name_fa: string;
    parent: number | null;
    direction: Direction;
  }): Promise<TreeCategory> {
    const { data } = await api.post("/finance/categories/", payload);
    return data;
  },

  async addLine(payload: Partial<BudgetLine>): Promise<BudgetLine> {
    const { data } = await api.post("/finance/budget-lines/", payload);
    return data;
  },
  async removeLine(id: number) {
    await api.delete(`/finance/budget-lines/${id}/`);
  },

  async grid(budgetId: number): Promise<BudgetGrid> {
    const { data } = await api.get("/finance/budget-grid/", { params: { budget: budgetId } });
    return data;
  },
  async saveGrid(
    cells: SaveCell[],
    salesCells: { budget_period_id: number; channel: string; amount_rial: string }[] = [],
  ) {
    const { data } = await api.post("/finance/budget-grid/", { cells, sales_cells: salesCells });
    return data as { written: number };
  },

  async stats(id: number): Promise<BudgetStats> {
    const { data } = await api.get(`/finance/budgets/${id}/stats/`);
    return data;
  },
  async clear(id: number, what: ClearWhat) {
    const { data } = await api.post(`/finance/budgets/${id}/clear/`, { what });
    return data as { removed: Record<string, number> };
  },
  async exportExcel(id: number): Promise<Blob> {
    const { data } = await api.get(`/finance/budgets/${id}/export/`, { responseType: "blob" });
    return data;
  },

  async importExcel<S extends "analyse" | "apply">(
    step: S,
    form: { file: File; year?: number; budget?: number | null; sheet?: string; scale?: number },
    options?: ImportOptions,
  ): Promise<S extends "analyse" ? ImportAnalysis : ImportResult> {
    const body = new FormData();
    body.append("file", form.file);
    if (form.year) body.append("year", String(form.year));
    if (form.budget) body.append("budget", String(form.budget));
    if (form.sheet) body.append("sheet", form.sheet);
    if (form.scale) body.append("scale", String(form.scale));
    if (options) body.append("options", JSON.stringify(options));
    const { data } = await api.post(`/finance/budget-import/${step}/`, body, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  },

  async actuals(budgetId: number, periodId: number): Promise<ActualEntrySheet> {
    const { data } = await api.get("/finance/budget-actuals/", {
      params: { budget: budgetId, period: periodId },
    });
    return data;
  },
  async saveActuals(
    budgetId: number,
    periodId: number,
    cells: { line_id: number; amount_rial: string; note: string; clear?: boolean }[],
  ) {
    const { data } = await api.post("/finance/budget-actuals/", {
      budget: budgetId,
      period: periodId,
      cells,
    });
    return data as { written: number };
  },
  async saveNote(budgetPeriodId: number, lineId: number, note: string) {
    const { data } = await api.post("/finance/budget-notes/", {
      budget_period_id: budgetPeriodId,
      line_id: lineId,
      variance_note: note,
    });
    return data as { variance_note: string };
  },

  async variance(budgetId: number, periodId: number): Promise<VarianceReport> {
    const { data } = await api.get("/finance/budget-variance/", {
      params: { budget: budgetId, period: periodId },
    });
    return data;
  },
  async heatmap(budgetId: number): Promise<BudgetHeatmapData> {
    const { data } = await api.get("/finance/budget-heatmap/", { params: { budget: budgetId } });
    return data;
  },
  async series(budgetId: number): Promise<BudgetSeries> {
    const { data } = await api.get("/finance/budget-series/", { params: { budget: budgetId } });
    return data;
  },
  async waterfall(budgetId: number, periodId: number): Promise<Waterfall> {
    const { data } = await api.get("/finance/budget-waterfall/", {
      params: { budget: budgetId, period: periodId },
    });
    return data;
  },
};

/** The first readable message out of a DRF error body. */
export function apiError(e: any, fallback: string): string {
  const body = e?.response?.data;
  if (!body) return fallback;
  if (typeof body === "string") return fallback;
  if (body.detail) return String(body.detail);
  const first = Object.values(body).flat()[0];
  return first ? String(first) : fallback;
}
