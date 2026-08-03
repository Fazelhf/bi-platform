import api from "./client";

export interface SalesInput {
  period: { id: number; label: string };
  channel: string;
  metric_rows: { field: string; label: string }[];
  /** Fields the CEO owns (targets) — shown but not editable here. */
  readonly_fields: string[];
  can_edit_targets: boolean;
  columns: Record<string, any>[];
  provinces: { province_id: number; name: string; sales_rial: string; target_rial: string }[];
  all_provinces: { id: number; name: string }[];
  /** B2B only — empty for the other channels, which report no segment split. */
  customer_groups: CustomerGroupRow[];
}

export interface CustomerGroupRow {
  group_id: number;
  name: string;
  sales_rial: string;
  profit_rial: string;
  invoice_count: number;
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

/**
 * Customer segments are reference data the B2B manager owns — they add,
 * rename and retire them without going through an administrator.
 */
export interface CustomerGroup {
  id: number;
  code: string;
  name_fa: string;
  sort_order: number;
  is_active: boolean;
  has_data: boolean;
}

export const customerGroupApi = {
  async list(includeInactive = false): Promise<CustomerGroup[]> {
    const { data } = await api.get("/sales/customer-groups/", {
      params: { page_size: 100, all: includeInactive ? 1 : undefined },
    });
    return data.results ?? data;
  },
  async create(payload: { name_fa: string; sort_order?: number }) {
    const { data } = await api.post("/sales/customer-groups/", payload);
    return data as CustomerGroup;
  },
  async patch(id: number, payload: Partial<CustomerGroup>) {
    const { data } = await api.patch(`/sales/customer-groups/${id}/`, payload);
    return data as CustomerGroup;
  },
  /** Retires a group that already has figures; deletes one that does not. */
  async remove(id: number) {
    await api.delete(`/sales/customer-groups/${id}/`);
  },
};
