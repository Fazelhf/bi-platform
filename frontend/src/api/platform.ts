import api from "./client";
import type {
  AppNotification,
  AuditEntry,
  Formula,
  KpiDefinition,
  UserRow,
} from "@/types";

function unwrap<T>(data: any): T[] {
  return (data?.results ?? data) as T[];
}

// ---------------- Notifications ----------------
export const notificationsApi = {
  async list(): Promise<AppNotification[]> {
    const { data } = await api.get("/executive/notifications/", {
      params: { page_size: 30 },
    });
    return unwrap<AppNotification>(data);
  },
  async unreadCount(): Promise<number> {
    const { data } = await api.get("/executive/notifications/unread_count/");
    return data.count;
  },
  async markRead(id: number) {
    await api.post(`/executive/notifications/${id}/mark_read/`);
  },
  async markAllRead() {
    await api.post("/executive/notifications/mark_all_read/");
  },
  async remove(id: number) {
    await api.delete(`/executive/notifications/${id}/`);
  },
  async clearRead(): Promise<number> {
    const { data } = await api.post("/executive/notifications/clear-read/");
    return data.deleted;
  },
  async clearAll(): Promise<number> {
    const { data } = await api.post("/executive/notifications/clear-all/");
    return data.deleted;
  },
};

// ---------------- Formulas ----------------
export const formulasApi = {
  async list(params: Record<string, unknown> = {}): Promise<Formula[]> {
    const { data } = await api.get("/executive/formulas/", {
      params: { page_size: 200, ...params },
    });
    return unwrap<Formula>(data);
  },
  async create(payload: { kpi: number; slot: string; expression: string; note?: string }) {
    const { data } = await api.post("/executive/formulas/", payload);
    return data as Formula;
  },
  async activate(id: number) {
    const { data } = await api.post(`/executive/formulas/${id}/activate/`);
    return data as Formula;
  },
  async deactivate(id: number) {
    const { data } = await api.post(`/executive/formulas/${id}/deactivate/`);
    return data as Formula;
  },
  async test(expression: string, domain: string, variables: Record<string, number> = {}) {
    const { data } = await api.post("/executive/formulas/test/", {
      expression, domain, variables,
    });
    return data as { ok: boolean; result?: string | null; error?: string };
  },
  async variables(domain: string): Promise<string[]> {
    const { data } = await api.get("/executive/formulas/variables/", {
      params: { domain },
    });
    return data;
  },
  async requestChange(id: number, note: string) {
    const { data } = await api.post(`/executive/formulas/${id}/request_change/`, { note });
    return data as { ok: boolean; message: string };
  },
};

// ---------------- KPI catalog ----------------
export const kpiApi = {
  async list(domain?: string): Promise<KpiDefinition[]> {
    const { data } = await api.get("/sales/kpi-definitions/", {
      params: { domain, page_size: 100 },
    });
    return unwrap<KpiDefinition>(data);
  },
  async patch(id: number, payload: Partial<KpiDefinition>) {
    const { data } = await api.patch(`/sales/kpi-definitions/${id}/`, payload);
    return data as KpiDefinition;
  },
};

// ---------------- Audit log ----------------
export const auditApi = {
  async list(params: Record<string, unknown> = {}): Promise<AuditEntry[]> {
    const { data } = await api.get("/executive/audit-logs/", {
      params: { page_size: 100, ...params },
    });
    return unwrap<AuditEntry>(data);
  },
};

// ---------------- Users ----------------
export const usersApi = {
  async list(): Promise<UserRow[]> {
    const { data } = await api.get("/auth/users/", { params: { page_size: 200 } });
    return unwrap<UserRow>(data);
  },
  async create(payload: Partial<UserRow> & { password: string }) {
    const { data } = await api.post("/auth/users/", payload);
    return data as UserRow;
  },
  async patch(id: number, payload: Partial<UserRow> & { password?: string }) {
    const { data } = await api.patch(`/auth/users/${id}/`, payload);
    return data as UserRow;
  },
  async remove(id: number) {
    await api.delete(`/auth/users/${id}/`);
  },
};

// ---------------- Generic CRUD (dimension tables) ----------------
export const crudApi = {
  async list(endpoint: string): Promise<Record<string, any>[]> {
    const { data } = await api.get(endpoint, { params: { page_size: 300 } });
    return unwrap<Record<string, any>>(data);
  },
  async create(endpoint: string, payload: Record<string, any>) {
    const { data } = await api.post(endpoint, payload);
    return data;
  },
  async patch(endpoint: string, id: number, payload: Record<string, any>) {
    const { data } = await api.patch(`${endpoint}${id}/`, payload);
    return data;
  },
  async remove(endpoint: string, id: number) {
    await api.delete(`${endpoint}${id}/`);
  },
};

// ---------------- Approval inbox ----------------
/** One sales sheet in the کارتابل: a channel's whole period, decided as one. */
export interface SalesSheet {
  key: string;
  period: { id: number; label: string; kind: "month" | "week" | "day" };
  channel: string;
  channel_label: string;
  status: string;
  submitted_by: string;
  submitted_at: string | null;
  salespeople: ({ employee_id: number; name: string } & Record<string, any>)[];
  provinces: { province_id: number; name: string; sales_rial: string }[];
  customer_groups: {
    group_id: number; name: string; sales_rial: string; profit_rial: string; invoice_count: number;
  }[];
  totals: {
    people_revenue_rial: string;
    province_sales_rial: string;
    salespeople: number;
    provinces: number;
    customer_groups: number;
  };
}

export const inboxApi = {
  async salesSheets(status = "submitted"): Promise<SalesSheet[]> {
    const { data } = await api.get("/sales/approvals/", { params: { status } });
    return data.sheets;
  },
  async decideSalesSheet(
    period: number,
    channel: string,
    action: "approve" | "reject" | "request-revision",
    note = "",
  ) {
    const { data } = await api.post("/sales/approvals/decide/", { period, channel, action, note });
    return data;
  },
  async pendingSales() {
    const { data } = await api.get("/sales/sales-monthly/", {
      params: { status: "submitted", page_size: 100 },
    });
    return unwrap<any>(data);
  },
  async pendingProduction() {
    const { data } = await api.get("/production/production/", {
      params: { status: "submitted", page_size: 100 },
    });
    return unwrap<any>(data);
  },
  async decideSales(id: number, action: "approve" | "reject" | "request-revision", note = "") {
    const { data } = await api.post(`/sales/sales-monthly/${id}/${action}/`, { note });
    return data;
  },
  async decideProduction(id: number, action: "approve" | "reject" | "request-revision", note = "") {
    const { data } = await api.post(`/production/production/${id}/${action}/`, { note });
    return data;
  },
};
