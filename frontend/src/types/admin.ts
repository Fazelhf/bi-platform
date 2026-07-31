/** Types for the Admin Panel API (/api/admin/). */

/** One entry in the panel's sidebar / command palette. */
export interface AdminNavItem {
  name: string;
  label: string;
  icon: string;
  /** Any one of these permission codes reveals the entry. Empty = always. */
  permissions: string[];
  group: string;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface PermissionGroup {
  area: string;
  label: string;
  permissions: [string, string][];
}

export interface AdminBootstrap {
  user: {
    id: number;
    username: string;
    name: string;
    role: string;
    is_superuser: boolean;
    avatar_color: string;
    avatar_image: string;
    initials: string;
  };
  permissions: string[];
  catalog: PermissionGroup[];
  maintenance: boolean;
  company_name: string;
  flags: Record<string, boolean>;
}

export interface AdminUser {
  id: number;
  username: string;
  name: string;
  display_name_fa: string;
  job_title_fa: string;
  email: string;
  phone: string;
  role: string;
  role_label: string;
  department: string;
  department_label: string;
  is_active: boolean;
  is_staff: boolean;
  is_superuser: boolean;
  admin_access: boolean;
  is_admin_panel_user: boolean;
  avatar_color: string;
  avatar_image: string;
  last_login: string | null;
  last_seen: string | null;
  is_online: boolean;
  date_joined: string;
  admin_role_ids: number[];
  admin_role_names: string[];
  team_ids: number[];
  team_names: string[];
  is_locked: boolean;
  locked_until: string | null;
  must_change_password: boolean;
  twofa_enabled: boolean;
  last_login_ip: string | null;
  password?: string;
}

export interface AdminRole {
  id: number;
  code: string;
  name_fa: string;
  description: string;
  permissions: string[];
  color: string;
  is_system: boolean;
  is_active: boolean;
  user_count: number;
  created_at: string;
}

export interface AdminTeam {
  id: number;
  code: string;
  name_fa: string;
  description: string;
  department: string;
  department_label: string;
  manager: number | null;
  manager_name: string;
  parent: number | null;
  parent_name: string;
  is_active: boolean;
  member_count: number;
  members: { id: number; user_id: number; name: string; username: string; is_lead: boolean }[];
}

export interface TeamNode extends Pick<AdminTeam, "id" | "code" | "name_fa" | "department" | "is_active" | "manager_name" | "member_count"> {
  children: TeamNode[];
}

export interface DataModelInfo {
  label: string;
  title: string;
  app: string;
  rows: number;
}

export interface DataField {
  name: string;
  label: string;
  type: string;
  required: boolean;
  editable: boolean;
  choices?: { value: string | number; label: string }[];
  related?: string;
}

export interface RecycleEntry {
  id: number;
  model_label: string;
  model_label_fa: string;
  object_id: string;
  object_repr: string;
  payload: Record<string, any>;
  deleted_by_name: string;
  deleted_at: string;
  restored_at: string | null;
  restored_by_name: string;
  is_restored: boolean;
  note: string;
}

export interface SystemSetting {
  id: number;
  key: string;
  label_fa: string;
  category: string;
  value: string;
  typed: any;
  value_type: "string" | "int" | "bool" | "json";
  description: string;
  is_secret: boolean;
  updated_by_name: string;
  updated_at: string;
}

export interface SettingGroup {
  key: string;
  label: string;
  settings: SystemSetting[];
}

export interface FeatureFlag {
  id: number;
  key: string;
  name_fa: string;
  description: string;
  is_enabled: boolean;
  roles: string[];
  updated_by_name: string;
  updated_at: string;
}

export interface DashboardStats {
  users: {
    total: number; active: number; inactive: number;
    online: number; admins: number; new_this_week: number;
  };
  activity: {
    audit_24h: number; audit_total: number; logins_24h: number;
    failed_logins_24h: number; notifications_unread: number;
  };
  storage: {
    disk: { available: boolean; total?: number; used?: number; free?: number };
    db_files_bytes: number; db_avatars_bytes: number;
    backups_bytes: number; db_file_bytes: number | null;
  };
  database: {
    vendor: string; name: string; size_bytes: number | null;
    table_count: number; row_total: number;
    tables: { table: string; model: string; label: string; rows: number; bytes: number | null }[];
  };
  content: {
    periods: number; kpi_results: number; teams: number;
    files: number; recycle_bin: number; backups: number;
  };
  errors: {
    window_days: number; failed_logins: number;
    failed_by_reason: Record<string, number>;
    locked_accounts: number; expired_tokens: number;
  };
  recent_activity: TimelineItem[];
  generated_at: string;
}

export interface TimelineItem {
  kind: string;
  action: string;
  actor: string;
  text: string;
  at: string;
}

export interface LoginEventRow {
  id: number;
  user: number | null;
  name: string;
  username_attempted: string;
  success: boolean;
  reason: string;
  reason_fa: string;
  ip_address: string | null;
  user_agent: string;
  created_at: string;
}

export interface SecurityOverview {
  policy: PasswordPolicy;
  locked_users: {
    id: number; username: string; name: string;
    reason: string; locked_until: string | null; is_locked: boolean;
  }[];
  twofa_enabled: number;
  must_change_password: number;
  failed_24h: number;
  failed_7d: number;
  active_sessions: number;
  ip_rules: { enforced: boolean; allow: number; deny: number };
  tokens: { active: number; expired: number };
}

export interface PasswordPolicy {
  id: number;
  min_length: number;
  require_uppercase: boolean;
  require_lowercase: boolean;
  require_digit: boolean;
  require_symbol: boolean;
  expiry_days: number;
  history_size: number;
  max_failed_attempts: number;
  lockout_minutes: number;
  session_timeout_minutes: number;
  enforce_ip_rules: boolean;
}

export interface IPRule {
  id: number;
  mode: "allow" | "deny";
  cidr: string;
  note: string;
  is_active: boolean;
  created_by_name: string;
  created_at: string;
}

export interface ApiTokenRow {
  id: number;
  name: string;
  user: number;
  user_name: string;
  prefix: string;
  scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  is_active: boolean;
  is_expired: boolean;
  created_at: string;
  token?: string;
}

export interface SessionRow {
  user_id: number;
  username: string;
  name: string;
  role: string;
  last_seen: string;
  ip_address: string | null;
  user_agent: string;
  since: string | null;
}

export interface BroadcastRow {
  id: number;
  title: string;
  body: string;
  level: string;
  audience: string;
  audience_label: string;
  audience_value: (string | number)[];
  send_email: boolean;
  recipient_count: number;
  sent_by_name: string;
  created_at: string;
}

export interface FolderRow {
  id: number;
  name: string;
  parent: number | null;
  path: string;
  file_count: number;
  created_at: string;
}

export interface FileRow {
  id: number;
  name: string;
  folder: number | null;
  folder_path: string;
  mime: string;
  size_bytes: number;
  visibility: string;
  version: number;
  version_count: number;
  is_current: boolean;
  uploaded_by_name: string;
  created_at: string;
  content?: string;
}

export interface ReportDefinition {
  id: number;
  name: string;
  kind: string;
  kind_label: string;
  fmt: string;
  params: Record<string, any>;
  frequency: string;
  frequency_label: string;
  recipients: number[];
  is_active: boolean;
  last_run_at: string | null;
  last_run_rows: number;
  created_by_name: string;
}

export interface BackupRow {
  id: number;
  filename: string;
  size_bytes: number;
  scope: string;
  note: string;
  created_by_name: string;
  created_at: string;
  restored_at: string | null;
}

export interface WorkflowDomain {
  key: string;
  label: string;
  counts: { status: string; label: string; n: number }[];
  total: number;
  stuck: { id: number; repr: string; period: string; waiting_days: number }[];
}

export interface Monitoring {
  server: {
    python: string; django: string; platform: string; hostname: string;
    debug: boolean; timezone: string; pid: number;
    started_at: string | null; uptime_seconds: number | null;
  };
  api: { ok: boolean; checks: { name: string; ok: boolean; ms?: number; error?: string; backend?: string }[] };
  queues: { available: boolean; reason?: string; detail?: string; broker?: string; workers?: any[] };
  errors: DashboardStats["errors"];
  database: { vendor: string; name: string; size_bytes: number | null; table_count: number; row_total: number };
  checked_at: string;
}

export interface ContentCategory {
  id: number; name: string; slug: string;
  parent: number | null; parent_name: string;
  description: string; is_active: boolean;
}

export interface ContentTag { id: number; name: string; color: string; usage: number }

export interface ContentTemplateRow {
  id: number; name: string; kind: string; kind_label: string;
  subject: string; body: string; variables: string[]; is_active: boolean;
}

export interface AnnouncementRow {
  id: number; title: string; body: string; level: string;
  is_published: boolean; is_live: boolean;
  starts_at: string | null; ends_at: string | null;
  category: number | null; tags: number[]; tag_names: string[];
  created_by_name: string; created_at: string;
}

export interface StaticPageRow {
  id: number; slug: string; title: string; body: string;
  is_published: boolean; updated_by_name: string; updated_at: string;
}
