export interface Period {
  id: number;
  jalali_year: number;
  jalali_month: number;
  label: string;
}

export interface KpiResult {
  id: number;
  period: number;
  kpi_code: string;
  kpi_name_fa: string;
  kpi_name_en: string;
  unit: string;
  direction: "higher" | "lower";
  scope: "company" | "team" | "employee";
  scope_id: number | null;
  scope_label: string;
  actual: string | null;
  target: string | null;
  ideal: string | null;
  deviation: string | null;
  efficiency_pct: string | null;
}

export interface DashboardSummary {
  period: Period;
  kpis: KpiResult[];
  team_revenue: { scope_label: string; actual: number }[];
  province_sales: { province__name_fa: string; sales: number; target: number }[];
  collections: { bank__name_fa: string; amount: number }[];
  leaderboard: { scope_label: string; actual: number }[];
}

export interface SalesMonthly {
  id: number;
  period: number;
  period_label: string;
  employee: number;
  employee_name: string;
  revenue_rial: string;
  invoice_count: number;
  active_customers: number;
  new_customers: number;
  profit_rial: string;
  cost_rial: string;
  target_rial: string;
  calls: number;
  status: "draft" | "submitted" | "approved" | "rejected";
  updated_at: string;
}
