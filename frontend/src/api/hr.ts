/**
 * منابع انسانی API — the chart, the people on it, and the archive.
 *
 * The rest of the site reads people from here indirectly: a sales channel's
 * roster, its entry sheet and its targets are all derived from who holds a
 * position in the unit that channel belongs to.
 */
import api from "./client";

export type UnitKind = "board" | "executive" | "staff" | "department" | "section";
export type SalesChannelCode = "" | "team" | "organizational" | "b2b" | "psp";

export interface OrgUnit {
  id: number;
  name_fa: string;
  kind: UnitKind;
  kind_label: string;
  parent: number | null;
  color: string;
  sort_order: number;
  sales_channel: SalesChannelCode;
  sales_channel_label: string;
  is_active: boolean;
}

export interface Seat {
  id: number;
  title: string;
  is_head: boolean;
  on_sales_sheet: boolean;
  note: string;
  holder: number | null;
  holder_name: string;
  /** The holder's login account; null when they have none. */
  holder_user: number | null;
}

export interface ChartNode extends OrgUnit {
  positions: Seat[];
  children: ChartNode[];
}

export interface ChartStats {
  units: number;
  positions: number;
  vacant: number;
  people: number;
  unplaced: number;
  archived: number;
  duplicates: number;
}

export interface Chart {
  roots: ChartNode[];
  stats: ChartStats;
}

export interface Person {
  id: number;
  code: string;
  full_name_fa: string;
  mobile: string;
  hired_on: string | null;
  note: string;
  is_active: boolean;
  archived_at: string | null;
  archive_note: string;
  user: number | null;
  username: string;
  account_name: string;
  account_active: boolean;
  account_role: string;
  account_last_login: string | null;
  positions: { id: number; title: string; unit: string; unit_id: number }[];
  /** Sales channels whose entry sheet this person is on. */
  channels: string[];
  sales_records: number;
}

export interface DeleteImpact {
  person: string;
  /** Rows removed with the person (sales figures, targets, memberships). */
  deleted: { model: string; label: string; count: number }[];
  /** Rows kept with their owner cleared (CRM records, chart seats). */
  unlinked: { model: string; label: string; count: number }[];
  /** A login account left in place, if any. */
  account: string;
}

export interface Account {
  id: number;
  username: string;
  name: string;
  linked_to: string;
}

export const SALES_CHANNELS: { value: SalesChannelCode; label: string }[] = [
  { value: "team", label: "فروش همکار" },
  { value: "organizational", label: "فروش بانکی" },
  { value: "b2b", label: "فروش B2B" },
  { value: "psp", label: "فروش PSP" },
];

export const UNIT_KINDS: { value: UnitKind; label: string }[] = [
  { value: "department", label: "واحد" },
  { value: "section", label: "زیرواحد" },
  { value: "staff", label: "واحد ستادی" },
  { value: "executive", label: "مدیریت عامل" },
  { value: "board", label: "هیئت‌مدیره" },
];

export const hrApi = {
  async chart(): Promise<Chart> {
    const { data } = await api.get("/hr/chart/");
    return data;
  },
  async importChart() {
    const { data } = await api.post("/hr/chart/import/");
    return data;
  },

  async saveUnit(payload: Partial<OrgUnit>, id?: number): Promise<OrgUnit> {
    const { data } = id
      ? await api.patch(`/hr/units/${id}/`, payload)
      : await api.post("/hr/units/", payload);
    return data;
  },
  async removeUnit(id: number) {
    await api.delete(`/hr/units/${id}/`);
  },

  async savePosition(payload: Record<string, unknown>, id?: number) {
    const { data } = id
      ? await api.patch(`/hr/positions/${id}/`, payload)
      : await api.post("/hr/positions/", payload);
    return data;
  },
  async removePosition(id: number) {
    await api.delete(`/hr/positions/${id}/`);
  },

  async people(status: "active" | "archived" | "unplaced" = "active"): Promise<Person[]> {
    const { data } = await api.get("/hr/people/", { params: { status } });
    return data;
  },
  async savePerson(payload: Record<string, unknown>, id?: number): Promise<Person> {
    const { data } = id
      ? await api.patch(`/hr/people/${id}/`, payload)
      : await api.post("/hr/people/", payload);
    return data;
  },
  async archive(id: number, note = ""): Promise<Person> {
    const { data } = await api.post(`/hr/people/${id}/archive/`, { note });
    return data;
  },
  async restore(id: number): Promise<Person> {
    const { data } = await api.post(`/hr/people/${id}/restore/`);
    return data;
  },
  async merge(id: number, into: number) {
    const { data } = await api.post(`/hr/people/${id}/merge/`, { into });
    return data as { moved: Record<string, number>; person: Person };
  },
  /** Admin only: attach a login account that already exists to this person. */
  async linkAccount(id: number, userId: number): Promise<Person> {
    const { data } = await api.post(`/hr/people/${id}/link-account/`, { user: userId });
    return data;
  },
  /** Admin only: a login account for this person, made with the panel's own rules. */
  async createAccount(id: number, payload: Record<string, unknown>): Promise<Person> {
    const { data } = await api.post(`/hr/people/${id}/account/`, payload);
    return data;
  },
  /** Main admin only: what a permanent delete would remove and orphan. */
  async deletePreview(id: number): Promise<DeleteImpact> {
    const { data } = await api.get(`/hr/people/${id}/delete-preview/`);
    return data;
  },
  /** Main admin only. `confirm` must be the person's exact name. */
  async hardDelete(id: number, confirm: string): Promise<DeleteImpact> {
    const { data } = await api.delete(`/hr/people/${id}/`, { data: { confirm } });
    return data;
  },
  async duplicates(): Promise<Person[][]> {
    const { data } = await api.get("/hr/people/duplicates/");
    return data;
  },
  async accounts(): Promise<Account[]> {
    const { data } = await api.get("/hr/people/accounts/");
    return data;
  },
};
