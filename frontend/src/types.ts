export interface Period {
  id: number;
  jalali_year: number;
  jalali_month: number;
  label: string;
}

export type Department = "" | "production" | "sales_org" | "sales_team";

export interface Me {
  username: string;
  display_name_fa: string;
  role: "executive" | "manager" | "operator" | "viewer";
  department: Department;
  is_superuser: boolean;
  can_enter_data: boolean;
  can_approve: boolean;
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

// ---------------- Production ----------------
export interface ProductionRow {
  id: number;
  period: number;
  period_label: string;
  machine: number;
  machine_name: string;
  machine_kind: "cutting" | "print";
  active_shifts: string;
  output_units: string;
  waste_pct: string;
  repair_count: string;
  downtime_breakdown_shifts: string;
  downtime_sizechange_shifts: string;
  downtime_nowork_shifts: string;
  total_downtime_shifts: string;
  status: "draft" | "submitted" | "approved" | "rejected";
  updated_at: string;
}

export interface ProductionDashboard {
  period: Period;
  kpis: KpiResult[];
  machine_kpis: KpiResult[];
  machines: {
    machine__name_fa: string;
    machine__kind: string;
    active_shifts: number;
    output_units: number;
    waste_pct: number;
    downtime_breakdown_shifts: number;
    downtime_sizechange_shifts: number;
    downtime_nowork_shifts: number;
  }[];
  costs: { category__name_fa: string; amount: number }[];
  revenue: { product: string; quantity: number; amount: number }[];
  print_colors: { color_count: number; area_sqm: number }[];
}

// ---------------- Cross-domain executive overview ----------------
interface Completeness {
  total: number;
  approved: number;
  complete: boolean;
}

export interface ExecutiveOverview {
  period: Period;
  sales_team: { kpis: KpiResult[]; revenue: number };
  sales_org: { kpis: KpiResult[]; revenue: number };
  sales_completeness: Completeness;
  production: {
    kpis: KpiResult[];
    output: number | null;
    cost: number;
    piece_rate_revenue: number;
    completeness: Completeness;
  };
  combined: {
    total_sales_revenue: number;
    sales_team_revenue: number;
    sales_org_revenue: number;
    internal_piece_rate_revenue: number;
    production_cost: number;
    production_margin: number;
    note: string;
  };
}
