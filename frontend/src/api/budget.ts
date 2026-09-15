/**
 * Budget API. Money comes back as strings so Rial figures stay exact; only
 * percentages and counts are numbers.
 *
 * There is no «actual» endpoint to write to: actuals are the cash movements
 * the finance team already records, matched to budget lines on the server.
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

/** Accrual sales for one channel — beside the cash lines, never in their totals. */
export interface SalesForecastRow {
  channel: string;
  label: string;
  /** Keyed by budget_period_id. */
  cells: Record<string, { amount_rial: string; baseline_rial: string | null }>;
}

export interface BudgetGrid {
  budget: Budget;
  months: GridMonth[];
  lines: GridLine[];
  sales: SalesForecastRow[];
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

export interface SaveSalesCell {
  budget_period_id: number;
  channel: string;
  amount_rial: string;
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
}

export interface SalesVarianceRow extends VarianceCell {
  channel: string;
  label: string;
}

export interface VarianceReport {
  budget: { id: number; title: string };
  period: { id: number; label: string; kind: string };
  month: { id: number; label: string };
  budget_period_id: number | null;
  grain: "month" | "week";
  /** True for a week: its plan is the month's, pro-rated by day count. */
  prorated: boolean;
  status: BudgetStatus;
  status_label: string;
  approved_at: string | null;
  rows: VarianceRow[];
  totals: { in: VarianceCell; out: VarianceCell; net: VarianceCell };
  thresholds: { pct: string; rial: string };
  unbudgeted_count: number;
  /** False when no cash movement has been recorded in the period yet. */
  has_actuals: boolean;
  /** Forecast sales against recorded sales, per channel. */
  sales: { rows: SalesVarianceRow[]; total: VarianceCell };
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

/** One سرفصل on the finance team's weekly actuals sheet. */
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
  month_budget_rial: string;
  month_actual_rial: string;
}

export interface ActualEntrySheet {
  budget: { id: number; title: string };
  period: { id: number; label: string; kind: string };
  month: { id: number; label: string; days: number };
  /** A month cut into weeks, read as the sum of its weeks — not writable. */
  is_rollup: boolean;
  /** The entry periods: the month's weeks, or the month itself. */
  weeks: { period_id: number; label: string; seq: number; days: number; entered: number }[];
  line_count: number;
  lines: ActualEntryLine[];
  totals: { in: VarianceCell; out: VarianceCell };
  can_edit: boolean;
  unit: FinanceSettings;
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
  async saveGrid(cells: SaveCell[], salesCells: SaveSalesCell[] = []) {
    const { data } = await api.post("/finance/budget-grid/", {
      cells,
      sales_cells: salesCells,
    });
    return data as { written: number };
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
    cells: { line_id: number; amount_rial: string; note: string }[],
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
