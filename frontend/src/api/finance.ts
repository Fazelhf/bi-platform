/**
 * Treasury API. Money comes back as strings so Rial figures stay exact;
 * only percentages and counts are numbers.
 */
import api from "./client";

export interface CashCategory {
  id: number;
  code: string;
  name_fa: string;
  direction: "in" | "out" | "both";
  direction_label: string;
  expects_credit_line: boolean;
  sort_order: number;
  is_active: boolean;
  note: string;
}

export interface CreditLine {
  id: number;
  kind: "facility" | "lending" | "partner";
  kind_label: string;
  title: string;
  counterparty: string;
  principal_rial: string;
  rate_pct: string;
  opened_on: string | null;
  due_on: string | null;
  installments: number;
  status: "active" | "settled" | "overdue" | "cancelled";
  status_label: string;
  note: string;
  balance_rial: string;
  received_rial: string;
  paid_rial: string;
  movement_count: number;
}

export interface BankAccount {
  id: number;
  title: string;
  label: string;
  bank_name: string;
  account_no: string;
  iban: string;
  kind: "bank" | "cash" | "petty";
  kind_label: string;
  opening_balance_rial: string;
  color: string;
  sort_order: number;
  is_active: boolean;
  note: string;
  movement_count: number;
}

export interface AccountBalance {
  id: number;
  title: string;
  label: string;
  kind: string;
  color: string;
  opening_rial: string;
  balance_rial: string;
  is_active: boolean;
}

/** One row of a cell — a cell can hold several, one per account. */
export interface EntryRow {
  movement_id?: number;
  amount_rial: string;
  account: number | null;
  credit_line: number | null;
  note: string;
}

export interface EntryDay {
  period_id: number;
  label: string;
  date: string | null;
  in: Record<string, EntryRow[]>;
  out: Record<string, EntryRow[]>;
}

export interface CashEntry {
  period: { id: number; label: string };
  is_month: boolean;
  categories: { in: CashCategory[]; out: CashCategory[] };
  days: EntryDay[];
  accounts: BankAccount[];
  unit: FinanceSettings;
  can_edit: boolean;
}

export interface AccountSlice {
  id: number | null;
  title: string;
  label: string;
  color: string;
  kind: string;
  amount: string;
}

export interface TrendRow {
  period_id: number;
  label: string;
  month?: number;
  day_count: number;
  average_rial: string;
  closing_rial: string;
  by_account: AccountSlice[];
  has_data?: boolean;
}

export interface MonthTrend {
  period: { id: number; label: string };
  grain: "week" | "month";
  rows: TrendRow[];
  month: Omit<TrendRow, "period_id" | "label">;
  accounts: AccountSlice[];
}

export interface YearTrend {
  year: number | null;
  years: number[];
  rows: TrendRow[];
  year_average_rial: string;
  accounts: AccountSlice[];
}

export interface ReportDay {
  period_id: number;
  label: string;
  date: string | null;
  in: Record<string, string>;
  out: Record<string, string>;
  total_in: string;
  total_out: string;
  net: string;
  balance: string;
}

export interface CreditSummaryLine {
  id: number;
  title: string;
  counterparty: string;
  principal_rial: string;
  balance_rial: string;
  status: string;
  due_on: string | null;
}

export interface CashReport {
  title: string;
  period_id: number | null;
  categories: {
    in: { id: number; name: string; code: string }[];
    out: { id: number; name: string; code: string }[];
  };
  days: ReportDay[];
  totals: {
    in: Record<string, string>;
    out: Record<string, string>;
    total_in: string;
    total_out: string;
    net: string;
  };
  balance: { opening: string; closing: string; low_threshold: string };
  warnings: { level: "warning" | "danger"; text: string; amount: string }[];
  credit_summary: {
    lines: {
      facility: CreditSummaryLine[];
      lending: CreditSummaryLine[];
      partner: CreditSummaryLine[];
    };
    owed_by_company: string;
    owed_to_company: string;
    partner_net: string;
  };
}

export interface FinanceSettings {
  opening_balance_rial: string;
  opening_on: string | null;
  low_balance_rial: string;
  /** Display only — storage is always Rial. */
  unit: "rial" | "toman";
  unit_label: string;
  unit_divisor: number;
}

export const financeApi = {
  async entry(periodId: number): Promise<CashEntry> {
    const { data } = await api.get("/finance/entry/", { params: { period: periodId } });
    return data;
  },
  async saveEntry(payload: Record<string, unknown>) {
    const { data } = await api.post("/finance/entry/", payload);
    return data as { ok: boolean; submitted: boolean; movements: number };
  },
  async report(periodId: number): Promise<CashReport> {
    const { data } = await api.get("/finance/report/", { params: { period: periodId } });
    return data;
  },
  async reportRange(from: number, to: number): Promise<CashReport> {
    const { data } = await api.get("/finance/report/", { params: { from, to } });
    return data;
  },
  async categories(): Promise<CashCategory[]> {
    const { data } = await api.get("/finance/categories/", { params: { page_size: 100 } });
    return data.results ?? data;
  },
  async creditLines(kind?: string): Promise<CreditLine[]> {
    const { data } = await api.get("/finance/credit-lines/", {
      params: { kind, page_size: 200 },
    });
    return data.results ?? data;
  },
  async saveCreditLine(payload: Record<string, unknown>, id?: number) {
    const { data } = id
      ? await api.patch(`/finance/credit-lines/${id}/`, payload)
      : await api.post("/finance/credit-lines/", payload);
    return data as CreditLine;
  },
  async removeCreditLine(id: number) {
    await api.delete(`/finance/credit-lines/${id}/`);
  },
  async creditMovements(id: number) {
    const { data } = await api.get(`/finance/credit-lines/${id}/movements/`);
    return data as {
      id: number; period_label: string; direction: "in" | "out";
      category_name: string; amount_rial: string; note: string;
    }[];
  },
  async accounts(): Promise<BankAccount[]> {
    const { data } = await api.get("/finance/accounts/", { params: { page_size: 200 } });
    return data.results ?? data;
  },
  async saveAccount(payload: Record<string, unknown>, id?: number) {
    const { data } = id
      ? await api.patch(`/finance/accounts/${id}/`, payload)
      : await api.post("/finance/accounts/", payload);
    return data as BankAccount;
  },
  async removeAccount(id: number) {
    await api.delete(`/finance/accounts/${id}/`);
  },
  async accountBalances() {
    const { data } = await api.get("/finance/accounts/balances/");
    return data as {
      accounts: AccountBalance[];
      total_rial: string;
      unassigned_rial: string;
    };
  },
  async monthTrend(periodId: number): Promise<MonthTrend> {
    const { data } = await api.get("/finance/balance-trend/", {
      params: { period: periodId },
    });
    return data;
  },
  async yearTrend(year?: number): Promise<YearTrend> {
    const { data } = await api.get("/finance/balance-trend/", { params: { year } });
    return data;
  },
  async settings(): Promise<FinanceSettings> {
    const { data } = await api.get("/finance/settings/");
    return data;
  },
  async saveSettings(payload: Partial<FinanceSettings>): Promise<FinanceSettings> {
    const { data } = await api.patch("/finance/settings/", payload);
    return data;
  },
};
