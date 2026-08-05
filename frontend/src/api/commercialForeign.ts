/**
 * بازرگانی خارجی API.
 *
 * Rial figures stay strings so they never round through a float. Foreign
 * amounts do too — a USD figure with two decimals is money, not a quantity.
 * Day counts are numbers, and `null` where the answer genuinely is not known
 * yet (a container that has not arrived has no days-at-port, which is a
 * different statement from zero).
 */
import api from "./client";

export type RateKind = "free" | "centre" | "customs";
export type OrderStatus =
  | "draft" | "registered" | "queued" | "allocated" | "remitted"
  | "purchased" | "shipping" | "customs" | "cleared" | "closed" | "cancelled";
export type ShipmentStatus =
  | "ready" | "departed" | "at_sea" | "at_port"
  | "customs" | "cleared" | "delivered" | "cancelled";

export interface Bank {
  id: number;
  code: string;
  name_fa: string;
  color: string;
  sort_order: number;
  is_active: boolean;
  note: string;
  order_count: number;
}

export interface FxRate {
  id: number;
  currency: string;
  currency_label: string;
  kind: RateKind;
  kind_label: string;
  on_date: string;
  rate_rial: string;
  is_manual: boolean;
  source: string;
  note: string;
}

export interface RateCell {
  currency: string;
  currency_label: string;
  kind: RateKind;
  kind_label: string;
  rate_rial: string | null;
  on_date: string | null;
  is_manual: boolean | null;
  source: string;
  /** How stale the figure is. A rate from three weeks ago is not today's. */
  age_days: number | null;
}

export interface OrderEvent {
  id: number;
  order: number;
  at: string;
  title: string;
  blocked_reason: string;
  note: string;
  created_by_name: string;
}

export interface ShipmentCost {
  id: number;
  shipment: number;
  kind: string;
  kind_label: string;
  amount_rial: string;
  amount_fx: string;
  currency: string;
  is_estimate: boolean;
  due_on: string | null;
  paid_on: string | null;
  note: string;
}

export interface Shipment {
  id: number;
  order: number;
  file_no: string;
  pi_no: string;
  lot_no: string;
  bl_no: string;
  container_no: string;
  carrier: string;
  origin_port: string;
  destination_port: string;
  goods_desc: string;
  weight_ton: string;
  value_amount: string;
  etd: string | null;
  eta: string | null;
  arrived_on: string | null;
  released_on: string | null;
  declared_on: string | null;
  cleared_on: string | null;
  free_days: number;
  demurrage_daily_rial: string;
  storage_daily_rial: string;
  status: ShipmentStatus;
  status_label: string;
  note: string;
  days_at_port: number | null;
  free_days_left: number | null;
  demurrage_days: number;
  demurrage_rial: string;
  storage_rial: string;
  accruing_rial: string;
  is_accruing: boolean;
  transit_days: number | null;
  clearance_days: number | null;
  costs: ShipmentCost[];
}

export interface ForeignOrder {
  id: number;
  file_no: string;
  pi_no: string;
  registration_no: string;
  statistical_no: string;
  supplier: number | null;
  supplier_name: string;
  country: string;
  brand: string;
  material: number | null;
  goods_desc: string;
  weight_ton: string;
  currency: string;
  currency_label: string;
  amount: string;
  bank: number | null;
  bank_name: string;
  registered_on: string | null;
  valid_until: string | null;
  queued_on: string | null;
  allocated_on: string | null;
  purchase_deadline: string | null;
  expected_queue_days: number;
  status: OrderStatus;
  status_label: string;
  owner: number | null;
  owner_name: string;
  note: string;
  days_in_queue: number | null;
  idle_days: number | null;
  last_action_on: string | null;
  days_to_expiry: number | null;
  days_to_purchase_deadline: number | null;
  is_waiting_allocation: boolean;
  shipment_count: number;
}

export interface ForeignOrderDetail extends ForeignOrder {
  shipments: Shipment[];
  events: OrderEvent[];
  amount_rial_centre: string | null;
}

export interface QueueRow {
  id: number;
  file_no: string;
  pi_no: string;
  registration_no: string;
  bank_id: number | null;
  bank: string;
  bank_color: string;
  supplier: string;
  goods: string;
  weight_ton: string;
  currency: string;
  amount: string;
  queued_on: string | null;
  days_waiting: number;
  expected_days: number;
  is_overdue: boolean;
  over_by: number;
  valid_until: string | null;
  days_to_expiry: number | null;
}

export interface BankQueueRow {
  id: number | null;
  name: string;
  color: string;
  count: number;
  share_pct: number;
  amount: string;
  min_days: number;
  max_days: number;
  avg_days: number;
  overdue_count: number;
}

export interface QueueReport {
  rows: QueueRow[];
  by_bank: BankQueueRow[];
  totals: {
    count: number; amount: string;
    min_days: number; max_days: number; avg_days: number;
    overdue_count: number;
  };
}

export interface StalledRow {
  id: number;
  file_no: string;
  pi_no: string;
  status: OrderStatus;
  status_label: string;
  bank: string;
  supplier: string;
  goods: string;
  currency: string;
  amount: string;
  owner: string;
  idle_days: number;
  level: "ok" | "warn" | "danger";
  last_action_on: string | null;
  last_action: string;
  blocked_reason: string;
}

export interface StalledReport {
  rows: StalledRow[];
  counts: { ok: number; warn: number; danger: number };
  bands: { warn_after: number; danger_after: number };
}

export interface DemurrageRow {
  id: number;
  order_id: number;
  file_no: string;
  pi_no: string;
  container_no: string;
  bl_no: string;
  carrier: string;
  goods: string;
  weight_ton: string;
  status: ShipmentStatus;
  status_label: string;
  arrived_on: string | null;
  cleared_on: string | null;
  days_at_port: number | null;
  free_days: number;
  free_days_used: number | null;
  free_days_left: number | null;
  demurrage_days: number;
  demurrage_daily_rial: string;
  demurrage_rial: string;
  storage_rial: string;
  total_rial: string;
  is_accruing: boolean;
  level: "ok" | "warn" | "danger" | "none";
  daily_rial: string;
}

export interface DemurrageReport {
  rows: DemurrageRow[];
  totals: {
    demurrage_rial: string;
    storage_rial: string;
    total_rial: string;
    container_count: number;
    accruing_count: number;
    /** What standing still costs the company today. */
    daily_burn_rial: string;
    expiring_soon: number;
    over_free_days: number;
  };
}

export interface Alert {
  level: "danger" | "warn";
  kind: string;
  text: string;
  order_id: number | null;
  file_no: string;
  shipment_id: number | null;
  days: number | null;
  amount_rial: string | null;
}

export interface ForeignDashboard {
  counts: {
    active_orders: number;
    stalled_orders: number;
    in_queue: number;
    allocated: number;
    in_transit: number;
    at_customs: number;
    cleared: number;
  };
  value_by_currency: { currency: string; label: string; amount: string }[];
  queue: {
    count: number; avg_days: number; max_days: number; min_days: number;
    overdue_count: number; by_bank: BankQueueRow[];
  };
  demurrage: DemurrageReport["totals"];
  tonnage: { in_transit: string; at_customs: string };
  customs_by_brand: { brand: string; tons: string; containers: number }[];
  rates: RateCell[];
  alerts: Alert[];
  can_edit: boolean;
}

export interface Choice { value: string; label: string }

export interface ForeignOptions {
  currencies: Choice[];
  rate_kinds: Choice[];
  order_statuses: Choice[];
  shipment_statuses: Choice[];
  cost_kinds: Choice[];
}

const BASE = "/commercial/foreign";
const list = (data: any) => data.results ?? data;

export const foreignApi = {
  async dashboard(): Promise<ForeignDashboard> {
    const { data } = await api.get(`${BASE}/dashboard/`);
    return data;
  },
  async options(): Promise<ForeignOptions> {
    const { data } = await api.get(`${BASE}/options/`);
    return data;
  },
  async queue(): Promise<QueueReport> {
    const { data } = await api.get(`${BASE}/queue/`);
    return data;
  },
  async stalled(minDays?: number): Promise<StalledReport> {
    const { data } = await api.get(`${BASE}/stalled/`, {
      params: { min_days: minDays },
    });
    return data;
  },
  async demurrage(accruingOnly = false): Promise<DemurrageReport> {
    const { data } = await api.get(`${BASE}/demurrage/`, {
      params: { accruing: accruingOnly ? 1 : undefined },
    });
    return data;
  },
  async alerts(): Promise<Alert[]> {
    const { data } = await api.get(`${BASE}/alerts/`);
    return data.rows;
  },

  async banks(): Promise<Bank[]> {
    const { data } = await api.get(`${BASE}/banks/`, { params: { page_size: 100 } });
    return list(data);
  },
  async saveBank(payload: Record<string, unknown>, id?: number) {
    const { data } = id
      ? await api.patch(`${BASE}/banks/${id}/`, payload)
      : await api.post(`${BASE}/banks/`, payload);
    return data as Bank;
  },

  async orders(params: Record<string, unknown> = {}): Promise<ForeignOrder[]> {
    const { data } = await api.get(`${BASE}/orders/`, {
      params: { page_size: 500, ...params },
    });
    return list(data);
  },
  async order(id: number): Promise<ForeignOrderDetail> {
    const { data } = await api.get(`${BASE}/orders/${id}/`);
    return data;
  },
  async saveOrder(payload: Record<string, unknown>, id?: number) {
    const { data } = id
      ? await api.patch(`${BASE}/orders/${id}/`, payload)
      : await api.post(`${BASE}/orders/`, payload);
    return data as ForeignOrder;
  },
  async removeOrder(id: number) {
    await api.delete(`${BASE}/orders/${id}/`);
  },
  async addEvent(orderId: number, payload: Record<string, unknown>) {
    const { data } = await api.post(`${BASE}/orders/${orderId}/events/`, payload);
    return data as OrderEvent;
  },

  async shipments(params: Record<string, unknown> = {}): Promise<Shipment[]> {
    const { data } = await api.get(`${BASE}/shipments/`, {
      params: { page_size: 500, ...params },
    });
    return list(data);
  },
  async saveShipment(payload: Record<string, unknown>, id?: number) {
    const { data } = id
      ? await api.patch(`${BASE}/shipments/${id}/`, payload)
      : await api.post(`${BASE}/shipments/`, payload);
    return data as Shipment;
  },
  async removeShipment(id: number) {
    await api.delete(`${BASE}/shipments/${id}/`);
  },

  async rateBoard(): Promise<{
    on: string; rows: RateCell[];
    currencies: Choice[]; kinds: Choice[]; provider: boolean;
  }> {
    const { data } = await api.get(`${BASE}/fx-rates/board/`);
    return data;
  },
  async rateHistory(currency: string, kind: RateKind) {
    const { data } = await api.get(`${BASE}/fx-rates/history/`, {
      params: { currency, kind },
    });
    return data as {
      currency: string; kind: string;
      rows: { on_date: string; rate_rial: string; is_manual: boolean; source: string }[];
    };
  },
  async saveRate(payload: Record<string, unknown>, id?: number) {
    const { data } = id
      ? await api.patch(`${BASE}/fx-rates/${id}/`, payload)
      : await api.post(`${BASE}/fx-rates/`, payload);
    return data as FxRate;
  },
  async syncRates() {
    const { data } = await api.post(`${BASE}/fx-rates/sync/`, {});
    return data as {
      ok: boolean; reason: string; detail: string;
      written: number; skipped: number; missing: string[];
    };
  },
};
