import api from "./client";

export interface SalesInput {
  period: { id: number; label: string };
  channel: string;
  metric_rows: { field: string; label: string }[];
  columns: Record<string, any>[];
  provinces: { province_id: number; name: string; sales_rial: string; target_rial: string }[];
  all_provinces: { id: number; name: string }[];
}

export const salesInputApi = {
  async get(periodId: number, channel: string): Promise<SalesInput> {
    const { data } = await api.get("/sales/input/", { params: { period: periodId, channel } });
    return data;
  },
  async save(payload: Record<string, any>) {
    const { data } = await api.post("/sales/input/", payload);
    return data as { ok: boolean; submitted: boolean; salespeople: number };
  },
};
