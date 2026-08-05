/**
 * بازرگانی داخلی API.
 *
 * Money and quantities come back as strings so a Rial figure never rounds
 * through a float on its way to the screen; only counts, percentages and
 * day-counts are numbers.
 */
import api from "./client";

export type MaterialUnitCode =
  | "kg" | "ton" | "pcs" | "roll" | "m" | "lit" | "pack" | "ctn";

export interface UnitChoice {
  value: MaterialUnitCode;
  label: string;
}

export interface MaterialCategory {
  id: number;
  code: string;
  name_fa: string;
  sort_order: number;
  is_active: boolean;
  material_count: number;
}

export interface Material {
  id: number;
  code: string;
  name_fa: string;
  category: number | null;
  category_name: string;
  unit: MaterialUnitCode;
  unit_label: string;
  min_stock: string;
  is_active: boolean;
  note: string;
  order_count: number;
  last_price_rial: string;
}

export interface Supplier {
  id: number;
  code: string;
  name_fa: string;
  contact_name: string;
  mobile: string;
  phone: string;
  email: string;
  address: string;
  activity: string;
  is_active: boolean;
  note: string;
  order_count: number;
  quote_count: number;
}

export interface QuoteReason {
  id: number;
  kind: "win" | "lose";
  kind_label: string;
  code: string;
  name_fa: string;
  sort_order: number;
  is_active: boolean;
}

export interface Quote {
  id: number;
  request: number;
  request_no: string;
  material_name: string;
  supplier: number;
  supplier_name: string;
  unit_price_rial: string;
  total_rial: string;
  quoted_on: string | null;
  delivery_days: number;
  validity_days: number;
  is_selected: boolean;
  reason: number | null;
  reason_name: string;
  reason_kind: "win" | "lose" | "";
  decision_note: string;
  note: string;
}

export type RequestStatus =
  | "open" | "quoting" | "awarded" | "ordered" | "cancelled";

export interface PurchaseRequest {
  id: number;
  request_no: string;
  material: number;
  material_name: string;
  material_unit: string;
  quantity: string;
  requester_unit: string;
  requested_on: string;
  needed_by: string | null;
  period: number | null;
  period_label: string;
  status: RequestStatus;
  status_label: string;
  note: string;
  quote_count: number;
  best_price_rial: string;
  selected_supplier: string;
  quotes?: Quote[];
}

export type OrderStatus =
  | "pending" | "buying" | "shipped" | "delivered" | "cancelled";

export interface PurchaseOrder {
  id: number;
  order_no: string;
  request: number | null;
  request_no: string;
  quote: number | null;
  supplier: number;
  supplier_name: string;
  material: number;
  material_name: string;
  material_unit: string;
  quantity: string;
  unit_price_rial: string;
  total_rial: string;
  ordered_on: string;
  delivered_on: string | null;
  delivery_days: number | null;
  period: number | null;
  period_label: string;
  status: OrderStatus;
  status_label: string;
  note: string;
}

/** A month bucket. `has_data: false` means nobody bought — draw it hollow. */
export interface MonthRow {
  key: string;
  year: number;
  month: number;
  label: string;
  amount_rial: string;
  order_count: number;
  change_pct: number | null;
  has_data: boolean;
}

export interface ConsumptionRow {
  key: string;
  year: number;
  month: number;
  label: string;
  quantity: string;
  amount_rial: string;
  order_count: number;
  avg_price_rial: string;
  qty_change_pct: number | null;
  has_data: boolean;
}

export interface ConsumptionReport {
  material: { id: number; name: string; unit: string; unit_label: string };
  rows: ConsumptionRow[];
  total_qty: string;
  total_amount: string;
  average_qty: string;
  max_qty: string;
  min_qty: string;
}

export interface PriceRow {
  key: string;
  year: number;
  month: number;
  label: string;
  paid_rial: string | null;
  quote_low_rial: string | null;
  quote_high_rial: string | null;
  quote_count: number;
  change_pct: number | null;
}

export interface PriceEntry {
  id: number;
  request_id: number;
  request_no: string;
  supplier_id: number;
  supplier: string;
  unit_price_rial: string;
  quoted_on: string | null;
  delivery_days: number;
  is_selected: boolean;
  reason: string;
  reason_kind: string;
  decision_note: string;
}

export interface PriceHistory {
  material: { id: number; name: string; unit: string; unit_label: string };
  rows: PriceRow[];
  entries: PriceEntry[];
  latest_rial: string;
  previous_rial: string;
  change_pct: number | null;
}

export interface SupplierStats {
  id: number;
  name: string;
  contact_name: string;
  mobile: string;
  activity: string;
  is_active: boolean;
  quote_count: number;
  win_count: number;
  /** null when the supplier has never been asked — not the same as 0%. */
  win_rate_pct: number | null;
  order_count: number;
  total_spend_rial: string;
  avg_quote_price_rial: string;
  avg_promised_days: number | null;
  avg_actual_days: number | null;
  last_order_on: string | null;
  last_price_rial: string;
  materials: string[];
}

export interface SupplierHistory {
  stats: SupplierStats;
  quotes: {
    id: number; request_id: number; request_no: string; material: string;
    quantity: string; unit_price_rial: string; total_rial: string;
    quoted_on: string | null; delivery_days: number; is_selected: boolean;
    reason: string; reason_kind: string; decision_note: string;
  }[];
  orders: {
    id: number; order_no: string; material: string; quantity: string;
    unit_price_rial: string; total_rial: string; ordered_on: string | null;
    delivered_on: string | null; delivery_days: number | null;
    status: OrderStatus; status_label: string;
  }[];
}

export interface ForecastRow {
  key: string;
  year: number;
  month: number;
  label: string;
  quantity: string;
  months_ahead: number;
}

export interface Forecast {
  material: { id: number; name: string; unit: string; unit_label: string };
  history: ConsumptionRow[];
  rows: ForecastRow[];
  horizon: number;
  method: string;
  observed_months: number;
  slope_per_month?: number;
  moving_average?: number;
  /** Months of history needed before the trend line is trusted. */
  min_months?: number;
  confidence: number;
  confidence_level: "none" | "low" | "medium" | "high";
  note: string;
}

export interface ForecastOverviewRow {
  material_id: number;
  material: string;
  unit_label: string;
  next_label: string;
  next_quantity: string;
  confidence: number;
  confidence_level: "none" | "low" | "medium" | "high";
  observed_months: number;
}

export interface Dashboard {
  month: { label: string; key: string };
  spend_rial: string;
  spend_change_pct: number | null;
  order_count: number;
  quote_count: number;
  open_request_count: number;
  active_supplier_count: number;
  material_count: number;
  top_material: {
    name: string; amount_rial: string; quantity: string; unit_label: string;
  } | null;
  top_supplier: { name: string; amount_rial: string } | null;
  monthly_spend: MonthRow[];
  forecast: ForecastOverviewRow[];
  can_edit: boolean;
}

export interface PurchaseReport {
  rows: {
    id: number; order_no: string; request_no: string;
    material_id: number; material: string; unit_label: string;
    supplier_id: number; supplier: string;
    quantity: string; unit_price_rial: string; total_rial: string;
    ordered_on: string | null; delivered_on: string | null;
    status: OrderStatus; status_label: string;
  }[];
  totals: {
    amount_rial: string; order_count: number; cancelled_count: number;
  };
  by_material: {
    id: number; name: string; unit_label: string;
    orders: number; quantity: string; amount_rial: string;
  }[];
  by_supplier: {
    id: number; name: string; orders: number; amount_rial: string;
  }[];
}

export interface PriceIncreaseRow {
  material_id: number;
  material: string;
  unit_label: string;
  previous_label: string;
  previous_rial: string;
  latest_label: string;
  latest_rial: string;
  change_pct: number;
}

export interface AwardPayload {
  quote: number;
  reason?: number | null;
  decision_note?: string;
  rejections?: { quote: number; reason?: number | null; decision_note?: string }[];
}

/** The list endpoints are paginated; every caller here wants the whole list. */
function unwrap<T>(data: any): T[] {
  return (data?.results ?? data) as T[];
}

export const commercialApi = {
  // -- reference data --------------------------------------------------
  async units(): Promise<UnitChoice[]> {
    const { data } = await api.get("/commercial/units/");
    return data.units;
  },
  async categories(): Promise<MaterialCategory[]> {
    const { data } = await api.get("/commercial/categories/", {
      params: { page_size: 200 },
    });
    return unwrap<MaterialCategory>(data);
  },
  async reasons(kind?: "win" | "lose"): Promise<QuoteReason[]> {
    const { data } = await api.get("/commercial/reasons/", {
      params: { kind, is_active: true, page_size: 200 },
    });
    return unwrap<QuoteReason>(data);
  },

  // -- materials -------------------------------------------------------
  async materials(params: Record<string, unknown> = {}): Promise<Material[]> {
    const { data } = await api.get("/commercial/materials/", {
      params: { page_size: 500, ...params },
    });
    return unwrap<Material>(data);
  },
  async material(id: number): Promise<Material> {
    const { data } = await api.get(`/commercial/materials/${id}/`);
    return data;
  },
  async saveMaterial(payload: Record<string, unknown>, id?: number) {
    const { data } = id
      ? await api.patch(`/commercial/materials/${id}/`, payload)
      : await api.post("/commercial/materials/", payload);
    return data as Material;
  },
  async removeMaterial(id: number) {
    await api.delete(`/commercial/materials/${id}/`);
  },
  async materialHistory(id: number): Promise<PriceHistory> {
    const { data } = await api.get(`/commercial/materials/${id}/history/`);
    return data;
  },
  async materialConsumption(id: number): Promise<ConsumptionReport> {
    const { data } = await api.get(`/commercial/materials/${id}/consumption/`);
    return data;
  },
  async materialForecast(id: number, horizon = 3): Promise<Forecast> {
    const { data } = await api.get(`/commercial/materials/${id}/forecast/`, {
      params: { horizon },
    });
    return data;
  },

  // -- suppliers -------------------------------------------------------
  async suppliers(params: Record<string, unknown> = {}): Promise<Supplier[]> {
    const { data } = await api.get("/commercial/suppliers/", {
      params: { page_size: 500, ...params },
    });
    return unwrap<Supplier>(data);
  },
  async supplier(id: number): Promise<Supplier> {
    const { data } = await api.get(`/commercial/suppliers/${id}/`);
    return data;
  },
  async saveSupplier(payload: Record<string, unknown>, id?: number) {
    const { data } = id
      ? await api.patch(`/commercial/suppliers/${id}/`, payload)
      : await api.post("/commercial/suppliers/", payload);
    return data as Supplier;
  },
  async removeSupplier(id: number) {
    await api.delete(`/commercial/suppliers/${id}/`);
  },
  async supplierHistory(id: number): Promise<SupplierHistory> {
    const { data } = await api.get(`/commercial/suppliers/${id}/history/`);
    return data;
  },

  // -- requests and quotes ---------------------------------------------
  async requests(params: Record<string, unknown> = {}): Promise<PurchaseRequest[]> {
    const { data } = await api.get("/commercial/requests/", {
      params: { page_size: 200, ...params },
    });
    return unwrap<PurchaseRequest>(data);
  },
  async request(id: number): Promise<PurchaseRequest> {
    const { data } = await api.get(`/commercial/requests/${id}/`);
    return data;
  },
  async saveRequest(payload: Record<string, unknown>, id?: number) {
    const { data } = id
      ? await api.patch(`/commercial/requests/${id}/`, payload)
      : await api.post("/commercial/requests/", payload);
    return data as PurchaseRequest;
  },
  async removeRequest(id: number) {
    await api.delete(`/commercial/requests/${id}/`);
  },
  async award(requestId: number, payload: AwardPayload): Promise<PurchaseRequest> {
    const { data } = await api.post(
      `/commercial/requests/${requestId}/award/`, payload,
    );
    return data;
  },
  async saveQuote(payload: Record<string, unknown>, id?: number) {
    const { data } = id
      ? await api.patch(`/commercial/quotes/${id}/`, payload)
      : await api.post("/commercial/quotes/", payload);
    return data as Quote;
  },
  async removeQuote(id: number) {
    await api.delete(`/commercial/quotes/${id}/`);
  },

  // -- orders ----------------------------------------------------------
  async orders(params: Record<string, unknown> = {}): Promise<PurchaseOrder[]> {
    const { data } = await api.get("/commercial/orders/", {
      params: { page_size: 200, ...params },
    });
    return unwrap<PurchaseOrder>(data);
  },
  async saveOrder(payload: Record<string, unknown>, id?: number) {
    const { data } = id
      ? await api.patch(`/commercial/orders/${id}/`, payload)
      : await api.post("/commercial/orders/", payload);
    return data as PurchaseOrder;
  },
  async removeOrder(id: number) {
    await api.delete(`/commercial/orders/${id}/`);
  },

  // -- dashboard and reports -------------------------------------------
  async dashboard(): Promise<Dashboard> {
    const { data } = await api.get("/commercial/dashboard/");
    return data;
  },
  async purchaseReport(params: Record<string, unknown> = {}): Promise<PurchaseReport> {
    const { data } = await api.get("/commercial/reports/purchases/", { params });
    return data;
  },
  async supplierReport(): Promise<SupplierStats[]> {
    const { data } = await api.get("/commercial/reports/suppliers/");
    return data.rows;
  },
  async priceIncreases(): Promise<PriceIncreaseRow[]> {
    const { data } = await api.get("/commercial/reports/price-increase/");
    return data.rows;
  },
  async monthlySpend(months = 12): Promise<MonthRow[]> {
    const { data } = await api.get("/commercial/reports/monthly-spend/", {
      params: { months },
    });
    return data.rows;
  },
  async forecastOverview(horizon = 3): Promise<ForecastOverviewRow[]> {
    const { data } = await api.get("/commercial/forecast/", { params: { horizon } });
    return data.rows;
  },
};
