import api from "./client";

export type Shift = "day" | "night";

/** One shift's share of every table on the input form. */
export interface ShiftBlock {
  headcount: number;
  cutting: Record<string, any>[];
  print: Record<string, any> | null;
  /** Entered in metres; m² = متر × 1.035. */
  print_colors: { color_count: number; length_m: string }[];
  costs: { category: number; category_code: string; category_name: string; amount_rial: string; description: string }[];
  /** `source`: which total from tables 1/3 fills the count (null: typed). */
  rolls: {
    product: number; product_code?: string; product_name: string; piece_rate_rial: string; quantity: string;
    source?: "actual_pos" | "actual_journal" | "actual_receipt" | "print_sqm" | null;
  }[];
}

export interface ProdInput {
  period: { id: number; label: string };
  benchmark: { total_headcount: number; ideal_output_per_shift: number; days_in_month: number };
  shifts: Record<Shift, ShiftBlock>;
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
