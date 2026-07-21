import api from "./client";
import type { ProductionDashboard, ProductionRow } from "@/types";

export const productionApi = {
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
