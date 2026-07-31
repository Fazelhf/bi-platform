import api from "./client";
import type { DashboardSummary, MonthProgress, Period, SalesMonthly } from "@/types";

export const salesApi = {
  async periods(): Promise<Period[]> {
    const { data } = await api.get("/sales/periods/");
    return data.results ?? data;
  },

  async employees(): Promise<{ id: number; full_name_fa: string; team_name?: string }[]> {
    const { data } = await api.get("/sales/employees/", { params: { page_size: 200 } });
    return data.results ?? data;
  },

  /** A month's weeks plus how much of it has been filled in. */
  async monthProgress(monthId: number): Promise<MonthProgress> {
    const { data } = await api.get(`/sales/periods/${monthId}/weeks/`);
    return data;
  },

  /** Cut a month into weeks (CEO only; refused once the month has figures). */
  async splitIntoWeeks(monthId: number): Promise<Period[]> {
    const { data } = await api.post(`/sales/periods/${monthId}/split/`);
    return data;
  },

  async dashboard(periodId: number, channel = "team"): Promise<DashboardSummary> {
    const { data } = await api.get("/sales/dashboard/summary/", {
      params: { period: periodId, channel },
    });
    return data;
  },

  async salesRows(periodId: number, channel = "team"): Promise<SalesMonthly[]> {
    const { data } = await api.get("/sales/sales-monthly/", {
      params: { period: periodId, channel, page_size: 100 },
    });
    return data.results ?? data;
  },

  async updateRow(id: number, patch: Partial<SalesMonthly>): Promise<SalesMonthly> {
    const { data } = await api.patch(`/sales/sales-monthly/${id}/`, patch);
    return data;
  },

  async transition(id: number, action: "submit" | "approve" | "reject") {
    const { data } = await api.post(`/sales/sales-monthly/${id}/${action}/`);
    return data as SalesMonthly;
  },
};

/** One کارشناس on a department's roster. */
export interface RosterMember {
  id: number;
  employee: number;
  employee_name: string;
  channel: string;
  channel_display: string;
  team: number | null;
  team_name: string;
  has_login: boolean;
  username: string;
  is_active: boolean;
  joined_at: string | null;
  left_at: string | null;
  note: string;
  periods_filled: number;
  total_revenue: string;
  last_period: string;
}

export const rosterApi = {
  async list(channel: string, params: Record<string, any> = {}): Promise<RosterMember[]> {
    const { data } = await api.get("/sales/roster/", { params: { channel, ...params } });
    return data.results ?? data;
  },

  /** People not yet on this roster — including which channels they are in. */
  async available(channel: string) {
    const { data } = await api.get("/sales/roster/available/", { params: { channel } });
    return data as { id: number; name: string; team: number | null; team_name: string; channels: string[] }[];
  },

  async add(channel: string, payload: { employee?: number; name?: string; team?: number | null }) {
    const { data } = await api.post("/sales/roster/", { channel, ...payload });
    return data as RosterMember;
  },

  async update(id: number, payload: Record<string, any>) {
    const { data } = await api.patch(`/sales/roster/${id}/`, payload);
    return data as RosterMember;
  },

  /** Deletes when the person has no figures, otherwise deactivates. */
  async remove(id: number) {
    const { data } = await api.delete(`/sales/roster/${id}/`);
    return data as { detail?: string; deactivated?: boolean } | null;
  },

  async teams(): Promise<Team[]> {
    const { data } = await api.get("/sales/teams/", { params: { page_size: 100 } });
    return data.results ?? data;
  },

  async addTeam(name: string) {
    const { data } = await api.post("/sales/teams/", { name_fa: name });
    return data as Team;
  },

  async renameTeam(id: number, name: string) {
    const { data } = await api.patch(`/sales/teams/${id}/`, { name_fa: name });
    return data as Team;
  },

  /** Refused by the API while the team still has members. */
  async deleteTeam(id: number) {
    await api.delete(`/sales/teams/${id}/`);
  },
};

export interface Team {
  id: number;
  code: string;
  name_fa: string;
  name_en: string;
  member_count: number;
}
