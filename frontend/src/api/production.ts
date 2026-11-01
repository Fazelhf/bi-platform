import api from "./client";
import type { ProductionDashboard, ProductionRow } from "@/types";

/** تولید روزانه — `GET /production/dashboard/daily/`. */
export interface ProductionDaily {
  month: number;
  label: string;
  /** Whether this month is recorded day by day at all. */
  daily: boolean;
  days: {
    date: string; label: string; day: number; weekday: number; period: number | null;
    workday: boolean; off: string; entered: boolean; missing: boolean;
    output: number; journal: number; pos: number; receipt: number; active_shifts: number;
    downtime: number; waste_pct: number; day_shift: number; night_shift: number;
  }[];
  summary: {
    output: number; workdays: number; entered_workdays: number; missing: number;
    per_workday: number; per_shift: number; ideal_per_shift: number;
  };
  detail?: {
    machine: string; kind: string; shift: string; shift_label: string; output: number; journal: number;
    pos: number; receipt: number; active_shifts: number; waste_pct: number; downtime_breakdown: number;
    downtime_sizechange: number; downtime_nowork: number; description: string; print_design: string;
  }[];
}

export const productionApi = {
  async daily(month: number, day?: number): Promise<ProductionDaily> {
    const { data } = await api.get("/production/dashboard/daily/", { params: { month, ...(day ? { day } : {}) } });
    return data;
  },
  async dashboard(periodId: number): Promise<ProductionDashboard> {
    const { data } = await api.get("/production/dashboard/summary/", {
      params: { period: periodId },
    });
    return data;
  },

  async rows(periodId: number): Promise<ProductionRow[]> {
    const { data } = await api.get("/production/production/", {
      params: { period: periodId, page_size: 100 },
    });
    return data.results ?? data;
  },

  async updateRow(id: number, patch: Partial<ProductionRow>): Promise<ProductionRow> {
    const { data } = await api.patch(`/production/production/${id}/`, patch);
    return data;
  },

  async transition(id: number, action: "submit" | "approve" | "reject") {
    const { data } = await api.post(`/production/production/${id}/${action}/`);
    return data as ProductionRow;
  },
};
