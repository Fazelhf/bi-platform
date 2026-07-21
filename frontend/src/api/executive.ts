import api from "./client";
import type { ExecutiveOverview } from "@/types";

export const executiveApi = {
  async overview(periodId: number): Promise<ExecutiveOverview> {
    const { data } = await api.get("/executive/overview/", {
      params: { period: periodId },
    });
    return data;
  },
};
