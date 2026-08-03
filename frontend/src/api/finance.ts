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

export interface EntryCell {
  amount_rial: string;
  credit_line: number | null;
  note: string;
}

export interface EntryDay {
  period_id: number;
  label: string;
  date: string | null;
  in: Record<string, EntryCell>;
  out: Record<string, EntryCell>;
}

export interface CashEntry {
  period: { id: number; label: string };
  is_month: boolean;
  categories: { in: CashCategory[]; out: CashCategory[] };
  days: EntryDay[];
  can_edit: boolean;
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
  async settings(): Promise<FinanceSettings> {
    const { data } = await api.get("/finance/settings/");
    return data;
  },
  async saveSettings(payload: Partial<FinanceSettings>): Promise<FinanceSettings> {
    const { data } = await api.patch("/finance/settings/", payload);
    return data;
  },
};
