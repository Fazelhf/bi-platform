/**
 * Admin-Panel API client.
 *
 * One thin module per panel section. Two conventions worth knowing:
 *  - exports use `fmt`, not `format` — DRF reserves `format` for content
 *    negotiation and 404s on an unknown value;
 *  - `download()` fetches as a blob and saves it, so the bearer token still
 *    travels (a plain <a href> would be unauthenticated).
 */
import api from "./client";
import type {
  AdminBootstrap,
  AdminRole,
  AdminTeam,
  AdminUser,
  AnnouncementRow,
  ApiTokenRow,
  BackupRow,
  BroadcastRow,
  ContentCategory,
  ContentTag,
  ContentTemplateRow,
  DashboardStats,
  DataField,
  DataModelInfo,
  FeatureFlag,
  FileRow,
  FolderRow,
  IPRule,
  LoginEventRow,
  Monitoring,
  Paginated,
  PasswordPolicy,
  RecycleEntry,
  ReportDefinition,
  SecurityOverview,
  SessionRow,
  SettingGroup,
  StaticPageRow,
  SystemSetting,
  TeamNode,
  WorkflowDomain,
} from "@/types/admin";

const BASE = "/admin";

export type Query = Record<string, any>;

async function list<T>(url: string, params: Query = {}): Promise<Paginated<T>> {
  const { data } = await api.get(url, { params: { page_size: 50, ...params } });
  // Endpoints that opt out of pagination still return a bare array.
  return Array.isArray(data)
    ? { count: data.length, next: null, previous: null, results: data }
    : data;
}

/** Download a binary/inline export using the authenticated client. */
export async function download(url: string, params: Query = {}, fallback = "export") {
  const response = await api.get(url, { params, responseType: "blob" });
  const disposition = String(response.headers["content-disposition"] || "");
  const match = /filename\*=UTF-8''([^;]+)/.exec(disposition);
  const name = match ? decodeURIComponent(match[1]) : fallback;

  const blobUrl = URL.createObjectURL(response.data);
  // Print-ready PDFs are HTML documents: open them so the print dialog fires.
  if (String(response.data.type).startsWith("text/html")) {
    window.open(blobUrl, "_blank");
    setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
    return;
  }
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(blobUrl);
}

/** Generic CRUD over one router-registered resource. */
function resource<T>(path: string) {
  const url = `${BASE}/${path}/`;
  return {
    url,
    list: (params: Query = {}) => list<T>(url, params),
    get: async (id: number) => (await api.get<T>(`${url}${id}/`)).data,
    create: async (payload: Partial<T> | Record<string, any>) =>
      (await api.post<T>(url, payload)).data,
    patch: async (id: number, payload: Partial<T> | Record<string, any>) =>
      (await api.patch<T>(`${url}${id}/`, payload)).data,
    remove: async (id: number) => { await api.delete(`${url}${id}/`); },
    bulkDelete: async (ids: number[]) =>
      (await api.post(`${url}bulk-delete/`, { ids })).data as
        { deleted: number; errors: any[] },
    bulkUpdate: async (ids: number[], changes: Record<string, any>) =>
      (await api.patch(`${url}bulk-update/`, { ids, changes })).data as
        { updated: number; errors: any[] },
    export: (fmt: string, params: Query = {}) =>
      download(`${url}export/`, { fmt, ...params }),
  };
}

// ---------------------------------------------------------------- shell
export const shellApi = {
  async bootstrap(): Promise<AdminBootstrap> {
    const { data } = await api.get(`${BASE}/bootstrap/`);
    return data;
  },
  async dashboard(): Promise<DashboardStats> {
    const { data } = await api.get(`${BASE}/dashboard/`);
    return data;
  },
};

// ------------------------------------------------------------- 1 · users
export const usersApi = {
  ...resource<AdminUser>("users"),
  async stats() {
    const { data } = await api.get(`${BASE}/users/stats/`);
    return data as {
      total: number; active: number; inactive: number;
      locked: number; admins: number; by_role: Record<string, number>;
    };
  },
  async resetPassword(id: number, payload: { password?: string; must_change?: boolean; force_logout?: boolean } = {}) {
    const { data } = await api.post(`${BASE}/users/${id}/reset-password/`, payload);
    return data as { ok: boolean; password: string | null; message: string };
  },
  async setActive(id: number, isActive: boolean) {
    const { data } = await api.post(`${BASE}/users/${id}/set-active/`, { is_active: isActive });
    return data as AdminUser;
  },
  async lock(id: number, reason: string) {
    const { data } = await api.post(`${BASE}/users/${id}/lock/`, { reason });
    return data as AdminUser;
  },
  async unlock(id: number) {
    const { data } = await api.post(`${BASE}/users/${id}/unlock/`);
    return data as AdminUser;
  },
  async forceLogout(id: number) {
    const { data } = await api.post(`${BASE}/users/${id}/force-logout/`);
    return data as { ok: boolean; message: string };
  },
  async assignRoles(id: number, roleIds: number[]) {
    const { data } = await api.post(`${BASE}/users/${id}/assign-roles/`, { role_ids: roleIds });
    return data as AdminUser;
  },
  async assignTeams(id: number, teamIds: number[]) {
    const { data } = await api.post(`${BASE}/users/${id}/assign-teams/`, { team_ids: teamIds });
    return data as AdminUser;
  },
  async activity(id: number) {
    const { data } = await api.get(`${BASE}/users/${id}/activity/`);
    return data as { audit: any[]; logins: LoginEventRow[]; permissions: string[] };
  },
};

// ------------------------------------------------------------- 2 · roles
export const rolesApi = {
  ...resource<AdminRole>("roles"),
  async catalog() {
    const { data } = await api.get(`${BASE}/roles/catalog/`);
    return data as { catalog: AdminBootstrap["catalog"]; mine: string[]; is_superuser: boolean };
  },
  async matrix() {
    const { data } = await api.get(`${BASE}/roles/matrix/`);
    return data as { catalog: AdminBootstrap["catalog"]; roles: AdminRole[] };
  },
  async clone(id: number, payload: { code: string; name_fa: string }) {
    const { data } = await api.post(`${BASE}/roles/${id}/clone/`, payload);
    return data as AdminRole;
  },
  async users(id: number) {
    const { data } = await api.get(`${BASE}/roles/${id}/users/`);
    return data as { id: number; username: string; name: string }[];
  },
};

// ------------------------------------------------------------- 3 · teams
export const teamsApi = {
  ...resource<AdminTeam>("teams"),
  async tree(): Promise<TeamNode[]> {
    const { data } = await api.get(`${BASE}/teams/tree/`);
    return data;
  },
  async addMember(id: number, userId: number, isLead = false) {
    const { data } = await api.post(`${BASE}/teams/${id}/add-member/`, {
      user_id: userId, is_lead: isLead,
    });
    return data;
  },
  async removeMember(id: number, userId: number) {
    const { data } = await api.post(`${BASE}/teams/${id}/remove-member/`, { user_id: userId });
    return data as { removed: number };
  },
};

// -------------------------------------------------------------- 4 · data
export const dataApi = {
  async overview() {
    const { data } = await api.get(`${BASE}/data-overview/`);
    return data as {
      tables: DataModelInfo[]; recycle_pending: number; recycle_restored: number;
    };
  },
  async models(): Promise<DataModelInfo[]> {
    const { data } = await api.get(`${BASE}/data/models/`);
    return data;
  },
  async schema(model: string) {
    const { data } = await api.get(`${BASE}/data/schema/`, { params: { model } });
    return data as { model: string; title: string; fields: DataField[] };
  },
  async rows(model: string, params: Query = {}) {
    const { data } = await api.get(`${BASE}/data/`, { params: { model, ...params } });
    return data as { count: number; page: number; page_size: number; results: Record<string, any>[] };
  },
  async create(model: string, values: Record<string, any>) {
    const { data } = await api.post(`${BASE}/data/`, { model, values });
    return data;
  },
  async update(model: string, id: number, values: Record<string, any>) {
    const { data } = await api.patch(`${BASE}/data/${id}/?model=${encodeURIComponent(model)}`, {
      model, values,
    });
    return data;
  },
  async remove(model: string, id: number) {
    const { data } = await api.delete(`${BASE}/data/${id}/?model=${encodeURIComponent(model)}`);
    return data as { ok: boolean; recycle_id: number };
  },
  async bulkDelete(model: string, ids: number[]) {
    const { data } = await api.post(`${BASE}/data/bulk-delete/`, { model, ids });
    return data as { deleted: number; errors: any[] };
  },
  async bulkUpdate(model: string, ids: number[], changes: Record<string, any>) {
    const { data } = await api.patch(`${BASE}/data/bulk-update/`, { model, ids, changes });
    return data as { updated: number; errors: any[] };
  },
  async import(model: string, payload: { rows?: any[]; file?: string; mode: "validate" | "commit" }) {
    const { data } = await api.post(`${BASE}/data/import/`, { model, ...payload });
    return data as {
      total: number; valid: number; invalid: number; create: number; update: number;
      errors: { row: number; errors: any }[]; committed: boolean; preview?: any[];
    };
  },
  exportTable: (model: string, fmt: string) =>
    download(`${BASE}/data/export/`, { model, fmt }),
  importTemplate: (model: string) =>
    download(`${BASE}/data/import-template/`, { model }),
};

export const recycleApi = {
  ...resource<RecycleEntry>("recycle-bin"),
  async restore(id: number) {
    const { data } = await api.post(`${BASE}/recycle-bin/${id}/restore/`);
    return data as RecycleEntry;
  },
  async purge(payload: { ids?: number[]; all?: boolean }) {
    const { data } = await api.post(`${BASE}/recycle-bin/purge/`, payload);
    return data as { purged: number };
  },
};

// ------------------------------------------------------------ 5 · system
export const systemApi = {
  settings: resource<SystemSetting>("settings"),
  flags: resource<FeatureFlag>("feature-flags"),
  async grouped(): Promise<SettingGroup[]> {
    const { data } = await api.get(`${BASE}/settings/grouped/`);
    return data;
  },
  async bulkSet(values: Record<string, any>) {
    const { data } = await api.patch(`${BASE}/settings/bulk-set/`, { values });
    return data as { updated: string[] };
  },
  async toggleFlag(id: number) {
    const { data } = await api.post(`${BASE}/feature-flags/${id}/toggle/`);
    return data as FeatureFlag;
  },
  async maintenance() {
    const { data } = await api.get(`${BASE}/maintenance/`);
    return data as { enabled: boolean; message: string };
  },
  async setMaintenance(enabled: boolean, message?: string) {
    const { data } = await api.post(`${BASE}/maintenance/`, { enabled, message });
    return data as { enabled: boolean; message: string };
  },
};

// ------------------------------------------------------- 7-8 · audit/sec
export const auditApi = {
  ...resource<any>("audit-logs"),
  async summary(days = 30) {
    const { data } = await api.get(`${BASE}/audit-logs/summary/`, { params: { days } });
    return data as {
      window_days: number; total: number;
      by_action: { action: string; n: number }[];
      by_model: { model_label: string; n: number }[];
      by_user: { user: string; name: string; n: number }[];
      models: string[];
    };
  },
};

export const loginEventsApi = {
  ...resource<LoginEventRow>("login-events"),
  async summary(days = 7) {
    const { data } = await api.get(`${BASE}/login-events/summary/`, { params: { days } });
    return data as {
      window_days: number; total: number; success: number; failed: number;
      by_reason: { reason: string; n: number }[];
      top_ips: { ip_address: string; n: number }[];
    };
  },
};

export const securityApi = {
  ipRules: resource<IPRule>("ip-rules"),
  tokens: resource<ApiTokenRow>("api-tokens"),
  async overview(): Promise<SecurityOverview> {
    const { data } = await api.get(`${BASE}/security/`);
    return data;
  },
  async policy(): Promise<PasswordPolicy> {
    const { data } = await api.get(`${BASE}/security/policy/`);
    return data;
  },
  async savePolicy(payload: Partial<PasswordPolicy>): Promise<PasswordPolicy> {
    const { data } = await api.patch(`${BASE}/security/policy/`, payload);
    return data;
  },
  async sessions(): Promise<SessionRow[]> {
    const { data } = await api.get(`${BASE}/security/sessions/`);
    return data;
  },
  async endSessions(payload: { user_ids?: number[]; all?: boolean }) {
    const { data } = await api.post(`${BASE}/security/sessions/`, payload);
    return data as { logged_out: number };
  },
  async revokeToken(id: number) {
    const { data } = await api.post(`${BASE}/api-tokens/${id}/revoke/`);
    return data as ApiTokenRow;
  },
  async twoFactor() {
    const { data } = await api.get(`${BASE}/security/two-factor/`);
    return data as {
      enforced_at_login: boolean;
      users: { id: number; username: string; name: string; enabled_at: string }[];
    };
  },
  /** Admins can only switch 2FA off — turning it on needs the user's own phone. */
  async disableTwoFactor(userId: number) {
    const { data } = await api.post(`${BASE}/security/two-factor/`, {
      user_id: userId, enabled: false,
    });
    return data as { ok: boolean; user_id: number; twofa_enabled: boolean };
  },
};

// ------------------------------------------------- 9-10 · notify & files
export const broadcastApi = {
  ...resource<BroadcastRow>("broadcasts"),
  async preview(audience: string, audienceValue: (string | number)[]) {
    const { data } = await api.post(`${BASE}/broadcasts/preview/`, {
      audience, audience_value: audienceValue,
    });
    return data as { count: number; sample: { id: number; name: string; username: string }[] };
  },
  async audiences() {
    const { data } = await api.get(`${BASE}/broadcasts/audiences/`);
    return data as {
      roles: { value: string; label: string }[];
      departments: { value: string; label: string }[];
      teams: { value: number; label: string }[];
      users: { value: number; label: string; username: string }[];
    };
  },
};

export const filesApi = {
  folders: resource<FolderRow>("folders"),
  ...resource<FileRow>("files"),
  download: (id: number, name: string) =>
    download(`${BASE}/files/${id}/download/`, {}, name),
  async versions(id: number): Promise<FileRow[]> {
    const { data } = await api.get(`${BASE}/files/${id}/versions/`);
    return data;
  },
  async usage() {
    const { data } = await api.get(`${BASE}/files/usage/`);
    return data as {
      total_bytes: number; file_count: number; version_count: number;
      by_folder: { folder: string; files: number; bytes: number }[];
    };
  },
};

// ------------------------------------------------- 11-12 · reports & db
export const reportsApi = {
  ...resource<ReportDefinition>("reports"),
  async kinds() {
    const { data } = await api.get(`${BASE}/reports/kinds/`);
    return data as {
      kinds: { value: string; label: string }[];
      frequencies: { value: string; label: string }[];
      formats: { value: string; label: string }[];
    };
  },
  async preview(kind: string, params: Query = {}) {
    const { data } = await api.get(`${BASE}/reports/preview/`, { params: { kind, ...params } });
    return data as {
      title: string;
      columns: { key: string; label: string }[];
      total: number;
      rows: Record<string, string>[];
    };
  },
  run: (kind: string, fmt: string, params: Query = {}) =>
    download(`${BASE}/reports/run/`, { kind, fmt, ...params }),
  runSaved: (id: number, fmt?: string) =>
    download(`${BASE}/reports/${id}/run-saved/`, fmt ? { fmt } : {}),
};

export const databaseApi = {
  backups: resource<BackupRow>("backups"),
  async stats() {
    const { data } = await api.get(`${BASE}/database/`);
    return data as {
      database: DashboardStats["database"];
      storage: DashboardStats["storage"];
      health: Monitoring["api"];
    };
  },
  async createBackup(scope: string, note = "") {
    const { data } = await api.post(`${BASE}/backups/`, { scope, note });
    return data as BackupRow;
  },
  async restoreBackup(id: number) {
    const { data } = await api.post(`${BASE}/backups/${id}/restore/`, { confirm: true });
    return data as BackupRow;
  },
  downloadBackup: (id: number, name: string) =>
    download(`${BASE}/backups/${id}/download/`, {}, name),
  async scopes() {
    const { data } = await api.get(`${BASE}/backups/scopes/`);
    return data as {
      scopes: { value: string; label: string }[];
      orphan_files: { filename: string; size_bytes: number; modified_at: string }[];
    };
  },
  async cleanupPreview(days = 90) {
    const { data } = await api.get(`${BASE}/database/maintenance/`, { params: { days } });
    return data as {
      jobs: { key: string; label: string }[];
      candidates: Record<string, number>;
      days: number;
    };
  },
  async runCleanup(job: string, days = 90) {
    const { data } = await api.post(`${BASE}/database/maintenance/`, { job, days });
    return data as { job: string; label: string; removed: number };
  },
};

// ------------------------------------------------ 13-14 · workflow & ops
export const workflowApi = {
  async overview() {
    const { data } = await api.get(`${BASE}/workflow/`);
    return data as {
      domains: WorkflowDomain[];
      stale_after_days: number;
      rules: { approver: string; auto_approve_imports: boolean; require_note_on_reject: boolean };
    };
  },
  async act(domain: string, ids: number[], action: "restart" | "force_approve") {
    const { data } = await api.post(`${BASE}/workflow/`, { domain, ids, action });
    return data as { changed: number; status: string };
  },
};

export const monitoringApi = {
  async get(days = 7): Promise<Monitoring> {
    const { data } = await api.get(`${BASE}/monitoring/`, { params: { days } });
    return data;
  },
};

// ----------------------------------------------------------- 15 · content
export const contentApi = {
  categories: resource<ContentCategory>("categories"),
  tags: resource<ContentTag>("tags"),
  templates: resource<ContentTemplateRow>("templates"),
  announcements: resource<AnnouncementRow>("announcements"),
  pages: resource<StaticPageRow>("pages"),
  async renderTemplate(id: number, values: Record<string, string>) {
    const { data } = await api.post(`${BASE}/templates/${id}/render/`, { values });
    return data as { subject: string; body: string };
  },
  async publishAnnouncement(id: number) {
    const { data } = await api.post(`${BASE}/announcements/${id}/publish/`);
    return data as AnnouncementRow;
  },
};
