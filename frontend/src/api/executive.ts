import api from "./client";
import type { ExecutiveOverview } from "@/types";

/** One month of the year, as the overview's trend needs it. */
export interface TrendMonth {
  period: number;
  label: string;
  month: number;
  total: number;
  profit: number;
  target: number;
  achievement: number;
  production_cost: number;
  channel_team: number;
  channel_organizational: number;
  channel_b2b: number;
}

export const executiveApi = {
  async overview(periodId: number): Promise<ExecutiveOverview> {
    const { data } = await api.get("/executive/overview/", {
      params: { period: periodId },
    });
    return data;
  },

  /** The whole year in one request — the context a single month cannot give. */
  async trend(year?: number): Promise<{ year: number; months: TrendMonth[] }> {
    const { data } = await api.get("/executive/trend/", {
      params: year ? { year } : {},
    });
    return data;
  },
};
