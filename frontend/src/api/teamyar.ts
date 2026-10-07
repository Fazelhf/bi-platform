import api from "./client";

export type TaskStatus = "todo" | "doing" | "blocked" | "done";

export interface Phase {
  id: number;
  title: string;
  order: number;
  color: string;
}

export interface TeamyarTask {
  id: number;
  phase: number | null;
  phase_title: string;
  title: string;
  description: string;
  owner: string;
  start_on: string;
  end_on: string;
  progress: number;
  status: TaskStatus;
  status_label: string;
  is_milestone: boolean;
  /** null on save = read from the title. */
  module: number | null;
  module_title: string;
  depends_on: number | null;
  done_on: string | null;
  order: number;
  is_overdue: boolean;
  days_left: number;
  updated_at: string;
}

export type MeetingKind = "vendor" | "internal" | "training" | "steering";
export type MeetingStatus = "planned" | "held" | "cancelled";

export interface Meeting {
  id: number;
  title: string;
  kind: MeetingKind;
  kind_label: string;
  status: MeetingStatus;
  status_label: string;
  held_at: string;
  duration_min: number;
  attendees: string;
  agenda: string;
  summary: string;
  decisions: string;
  rating: number | null;
  task: number | null;
  module: number | null;
  module_title: string;
}

export type LogKind =
  | "call" | "message" | "email" | "visit" | "issue" | "decision" | "note" | "system";

export interface LogEntry {
  id: number;
  happened_at: string;
  kind: LogKind;
  kind_label: string;
  counterpart: string;
  subject: string;
  body: string;
  resolved: boolean;
  task: number | null;
  task_title: string;
  meeting: number | null;
  author_name: string;
}

/** A module row — the charter's twelve are seeded, more can be added. */
export interface Module {
  id: number;
  title: string;
  owner: string;
  specialist: string;
  keywords: string;
  starts_on: string | null;
  ends_on: string | null;
  in_scope: boolean;
  order: number;
}

/** A module as the overview reports it; key "general" = filed under none. */
export interface ModuleCard {
  key: number | "general";
  label: string;
  in_scope: boolean;
  keywords: string;
  owner: string;
  specialist: string;
  progress: number;
  planned: number;
  status: TaskStatus;
  status_label: string;
  start_on: string | null;
  end_on: string | null;
  task_count: number;
  done_count: number;
  blocked_count: number;
  overdue_count: number;
  next_deadline: { id: number; title: string; end_on: string } | null;
  meetings_held: number;
  meeting_minutes: number;
  avg_rating: number | null;
  open_issues: number;
  last_activity: string | null;
}

export interface Overview {
  today: string;
  /** Average of the in-scope modules — see apps/teamyar/progress.py. */
  progress: number;
  planned_progress: number;
  modules: ModuleCard[];
  general: ModuleCard | null;
  modules_in_scope: number;
  modules_live: number;
  modules_started: number;
  task_count: number;
  by_status: Partial<Record<TaskStatus, number>>;
  overdue: TeamyarTask[];
  upcoming: TeamyarTask[];
  in_progress: TeamyarTask[];
  meetings: {
    held: number;
    avg_rating: number;
    with_decisions: number;
    planned: number;
    cancelled: number;
    total_minutes: number;
    next: Meeting | null;
  };
  open_issues: number;
  log_count: number;
}

export const STATUS_LABELS: Record<TaskStatus, string> = {
  todo: "شروع نشده",
  doing: "در حال انجام",
  blocked: "متوقف",
  done: "انجام شده",
};

export const MEETING_KINDS: Record<MeetingKind, string> = {
  vendor: "با تیمیار",
  internal: "داخلی",
  training: "آموزش",
  steering: "کمیته راهبری",
};

export const MEETING_STATUSES: Record<MeetingStatus, string> = {
  planned: "برنامه‌ریزی شده",
  held: "برگزار شد",
  cancelled: "لغو شد",
};

/** «system» is written by the server on status changes, never by hand. */
export const LOG_KINDS: Record<Exclude<LogKind, "system">, string> = {
  call: "تماس تلفنی",
  message: "پیام / چت",
  email: "ایمیل / نامه",
  visit: "حضوری",
  issue: "مشکل",
  decision: "تصمیم",
  note: "یادداشت",
};

function crud<T extends { id: number }>(path: string) {
  return {
    list: (params?: Record<string, string>) =>
      api.get<T[]>(`/teamyar/${path}/`, { params }).then((r) => r.data),
    create: (body: Partial<T>) => api.post<T>(`/teamyar/${path}/`, body).then((r) => r.data),
    update: (id: number, body: Partial<T>) =>
      api.patch<T>(`/teamyar/${path}/${id}/`, body).then((r) => r.data),
    remove: (id: number) => api.delete(`/teamyar/${path}/${id}/`),
  };
}

export interface Person {
  name: string;
  group: "ours" | "teamyar" | "past";
  note: string;
}

export const teamyarApi = {
  overview: () => api.get<Overview>("/teamyar/overview/").then((r) => r.data),
  /** Attendee picker: our staff (HR), Teamyar's team, and names used before. */
  people: () => api.get<Person[]>("/teamyar/people/").then((r) => r.data),
  modules: crud<Module>("modules"),
  phases: crud<Phase>("phases"),
  tasks: crud<TeamyarTask>("tasks"),
  meetings: crud<Meeting>("meetings"),
  logs: crud<LogEntry>("logs"),
};

/** A server datetime as the "YYYY-MM-DDTHH:mm" local value JalaliDateField edits. */
export function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** The local calendar day of a server datetime, "YYYY-MM-DD". */
export function localDay(iso: string): string {
  return toLocalInput(iso).slice(0, 10);
}
