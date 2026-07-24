import api from "./client";
import type { DashboardSummary, Period, SalesMonthly } from "@/types";

export const salesApi = {
  async periods(): Promise<Period[]> {
    const { data } = await api.get("/sales/periods/");
    return data.results ?? data;
  },

  async employees(): Promise<{ id: number; full_name_fa: string; team_name?: string }[]> {
    const { data } = await api.get("/sales/employees/", { params: { page_size: 200 } });
    return data.results ?? data;
  },

  async dashboard(periodId: number, channel = "team"): Promise<DashboardSummary> {
    const { data } = await api.get("/sales/dashboard/summary/", {
      params: { period: periodId, channel },
    });
    return data;
  },

  async salesRows(periodId: number, channel = "team"): Promise<SalesMonthly[]> {
    const { data } = await api.get("/sales/sales-monthly/", {
      params: { period: periodId, channel, page_size: 100 },
    });
    return data.results ?? data;
  },

  async updateRow(id: number, patch: Partial<SalesMonthly>): Promise<SalesMonthly> {
    const { data } = await api.patch(`/sales/sales-monthly/${id}/`, patch);
    return data;
  },

  async transition(id: number, action: "submit" | "approve" | "reject") {
    const { data } = await api.post(`/sales/sales-monthly/${id}/${action}/`);
    return data as SalesMonthly;
  },
};
