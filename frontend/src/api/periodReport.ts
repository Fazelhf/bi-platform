/**
 * Range reporting — a span of months next to the span before it.
 *
 * Money comes back as strings (the API keeps Rial figures exact); percentages
 * come back as numbers or `null`, where null means "no base to compare
 * against" rather than zero.
 */
import api from "./client";

export interface PeriodRef {
  id: number;
  label: string;
}

export interface PeriodReportRow {
  employee_id: number;
  name: string;
  sales_rial: string;
  profit_rial: string;
  cost_rial: string;
  invoice_count: number;
  calls: number;
  collected_rial: string;
  receivables_rial: string;
  target_rial: string;
  achievement_pct: number | null;
  margin_pct: number | null;
  prev_sales_rial: string | null;
  growth_pct: number | null;
}

export interface PeriodReportTotals {
  sales_rial: string;
  profit_rial: string;
  cost_rial: string;
  invoice_count: number;
  calls: number;
  collected_rial: string;
  receivables_rial: string;
  target_rial: string;
  achievement_pct: number | null;
  margin_pct: number | null;
  collection_pct: number | null;
  prev_sales_rial: string | null;
  growth_pct: number | null;
}

export interface ProvinceRow {
  province_id: number;
  name: string;
  sales_rial: string;
  target_rial: string;
  achievement_pct: number | null;
  prev_sales_rial: string | null;
  growth_pct: number | null;
}

export interface CustomerGroupRow {
  group_id: number;
  name: string;
  sales_rial: string;
  profit_rial: string;
  invoice_count: number;
  share_pct: number | null;
  margin_pct: number | null;
  prev_sales_rial: string | null;
  growth_pct: number | null;
}

export interface MonthlyRow {
  period_id: number;
  label: string;
  sales_rial: string;
  profit_rial: string;
  target_rial: string;
  achievement_pct: number | null;
}

export interface PeriodReport {
  channel: string;
  range: { from: PeriodRef; to: PeriodRef; months: PeriodRef[]; length: number };
  previous_range: {
    comparable: boolean;
    from: PeriodRef | null;
    to: PeriodRef | null;
    note: string | null;
  };
  rows: PeriodReportRow[];
  totals: PeriodReportTotals;
  provinces: ProvinceRow[];
  customer_groups: CustomerGroupRow[];
  monthly: MonthlyRow[];
}

export interface PeriodPresets {
  year: number;
  years: number[];
  months: { id: number; label: string; jalali_month: number; has_data: boolean }[];
  presets: {
    key: string;
    label: string;
    from: number;
    to: number;
    from_label: string;
    to_label: string;
    /** Whether any month in the span holds figures for this channel. */
    has_data: boolean;
  }[];
}

export const periodReportApi = {
  async presets(channel: string, year?: number): Promise<PeriodPresets> {
    const { data } = await api.get("/sales/period-presets/", {
      params: { channel, year },
    });
    return data;
  },
  async report(from: number, to: number, channel: string): Promise<PeriodReport> {
    const { data } = await api.get("/sales/period-report/", {
      params: { from, to, channel },
    });
    return data;
  },
};
