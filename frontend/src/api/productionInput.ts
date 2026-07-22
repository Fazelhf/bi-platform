import api from "./client";

export interface ProdInput {
  period: { id: number; label: string };
  benchmark: { total_headcount: number; ideal_output_per_shift: number; days_in_month: number };
  cutting: Record<string, any>[];
  print: Record<string, any> | null;
  print_colors: { color_count: number; area_sqm: string }[];
  costs: { category: number; category_name: string; amount_rial: string }[];
  rolls: { product: number; product_name: string; piece_rate_rial: string; quantity: string }[];
}

export const productionInputApi = {
  async get(periodId: number): Promise<ProdInput> {
    const { data } = await api.get("/production/input/", { params: { period: periodId } });
    return data;
  },
  async save(payload: Record<string, any>) {
    const { data } = await api.post("/production/input/", payload);
    return data as { ok: boolean; submitted: boolean; period: string };
  },
};
