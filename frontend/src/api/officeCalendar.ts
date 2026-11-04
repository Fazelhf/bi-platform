import api from "./client";
import { saveAsFile } from "@/utils/download";

/** تقویم کاری — the shared calendars, holidays, the weekly days off and reminders. */
export type Level = "read" | "write" | "manage";

export interface CalendarRow {
  id: number;
  name: string;
  kind: "company" | "management" | "unit" | "personal";
  kind_display: string;
  department: string;
  color: string;
  owner: number | null;
  level: Level;
  can_write: boolean;
  /** Shown by default; the rest sit under «سایر تقویم‌ها». */
  mine: boolean;
}

export type EventKind = "meeting" | "event" | "task" | "reminder";
export type Priority = "normal" | "important" | "urgent";
export type Repeat = "" | "daily" | "weekdays" | "weekly" | "monthly" | "yearly";

export type RsvpStatus = "pending" | "accepted" | "tentative" | "declined" | "more_time" | "proposed";

export interface Rsvp {
  user: number;
  name: string;
  status: RsvpStatus;
  status_display: string;
  note: string;
  proposed_start: string | null;
  proposed_end: string | null;
  /** The organiser's answer to a proposed time. */
  proposal_decision: "" | "accepted" | "rejected";
  /** A «more time» request: by when they will answer. */
  wait_until: string | null;
  responded_at: string | null;
  /** Only on an acceptance: what it clashes with on the caller's own calendar. */
  conflicts?: Busy[];
}

export interface Busy {
  id: number;
  title: string;
  start: string;
  end: string;
}

export interface FileMeta {
  id: number;
  name: string;
  mime: string;
  size_bytes: number;
}

export interface EventFile extends FileMeta {
  comment: number | null;
  uploaded_by: number | null;
  uploaded_by_name: string;
  at: string;
}

export interface ActionItem {
  task: number;
  title: string;
  assignee: number | null;
  assignee_name: string;
  due_on: string | null;
  done: boolean;
}

export interface HistoryRow {
  action: string;
  detail: string;
  actor: string;
  at: string;
}

export interface EventComment {
  id: number;
  parent: number | null;
  author: number | null;
  author_name: string;
  author_color: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  /** How many earlier versions an edit kept. */
  versions: number;
  mentions: { id: number; name: string }[];
  attachments: FileMeta[];
  can_edit: boolean;
  can_delete: boolean;
}

export interface NewFile {
  name: string;
  mime: string;
  content: string;
}

export interface CalendarEvent {
  id: number;
  calendar: number;
  calendar_name: string;
  color: string;
  title: string;
  kind: EventKind;
  priority: Priority;
  /** This occurrence's start/end; the series' first start is `series_start`. */
  start: string;
  end: string;
  series_start?: string;
  key?: string;
  all_day: boolean;
  repeat: Repeat;
  repeat_until: string | null;
  /** Minutes before the start; null = the priority's default. */
  reminders: number[] | null;
  location: string;
  description: string;
  attendees: number[];
  attendee_names: string[];
  /** Outside the company, by name. */
  guests: string[];
  /** Invitees are asked to answer by then. */
  respond_by: string | null;
  /** Every invitee's answer — the organiser's view of who is coming. */
  responses: Rsvp[];
  /** The caller's own invitation, if they are on it. */
  my_response: Rsvp | null;
  comment_count: number;
  online_link: string;
  /** For the people in the meeting only (empty for everyone else). */
  attachments: EventFile[];
  action_items: ActionItem[];
  minutes: string;
  minutes_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string;
  /** An occurrence edited on its own: the series it came from. */
  series: number | null;
  original_start: string | null;
  /** The caller is the organiser, an invitee, or runs the calendar it is on: sees its discussion and files. */
  in_meeting: boolean;
  /** The caller is an attendee. */
  invited?: boolean;
  /** Invited to an event on someone else's calendar: it shows on this one, the caller's own. */
  home_calendar?: number;
  /** The organiser. */
  created_by: number | null;
  created_by_name: string;
  can_edit: boolean;
}

export interface RangeDay {
  date: string;
  jalali: [number, number, number];
  /** 0 = شنبه … 6 = جمعه */
  weekday: number;
  workday: boolean;
  /** Why it is not worked: the holiday's title or «تعطیل هفتگی». */
  off: string;
  /** The factory keeps its own week (it runs پنج‌شنبه). */
  factory_workday: boolean;
}

export interface CalendarRange {
  from: string;
  to: string;
  days: RangeDay[];
  workdays: number;
  events: CalendarEvent[];
}

export interface WorkWeek {
  /** The office's weekly days off, 0 = شنبه … 6 = جمعه. */
  days_off: number[];
  /** The factory's. */
  factory_days_off: number[];
  can_edit: boolean;
}

export interface HolidayRow {
  id: number;
  date: string;
  title: string;
  jalali: string;
}

export interface Share {
  user: number;
  name: string;
  level: Level;
}

export interface PriorityRule {
  minutes: number[];
  sms: boolean;
}

export interface SettingsPerson {
  id: number;
  name: string;
  /** Masked: 0912***4567. */
  phone: string;
  has_phone: boolean;
}

export interface CalendarSettings {
  office_managers: SettingsPerson[];
  /** The management team: who gets the day-before agenda and the SMS reminders. */
  sms_recipients: SettingsPerson[];
  digest_enabled: boolean;
  digest_time: string;
  priority_rules: Record<Priority, PriorityRule>;
  sms_attendees: boolean;
  sms_ready: boolean;
  sms_status: { ok: boolean; line: string; detail: string };
  can_edit: boolean;
  can_name_office: boolean;
  is_office_manager: boolean;
}

export const calendarApi = {
  async calendars(): Promise<CalendarRow[]> {
    return (await api.get("/office/calendar/calendars/")).data;
  },
  async calendar(id: number): Promise<{ id: number; name: string; color: string; shares: Share[] }> {
    return (await api.get(`/office/calendar/calendars/${id}/`)).data;
  },
  async saveCalendar(id: number, body: { name?: string; color?: string; shares?: { user: number; level: Level }[] }) {
    return (await api.patch(`/office/calendar/calendars/${id}/`, body)).data;
  },
  /** Days [from, to) with every occurrence in them. */
  async range(from: string, to: string): Promise<CalendarRange> {
    return (await api.get("/office/calendar/range/", { params: { from, to } })).data;
  },
  async search(q: string): Promise<CalendarEvent[]> {
    const { data } = await api.get("/office/calendar/events/", { params: { q, page_size: 50 } });
    return data.results ?? data;
  },
  async saveEvent(body: Partial<CalendarEvent>, id?: number): Promise<CalendarEvent> {
    const { data } = id
      ? await api.patch(`/office/calendar/events/${id}/`, body)
      : await api.post("/office/calendar/events/", body);
    return data;
  },
  async deleteEvent(id: number): Promise<void> {
    await api.delete(`/office/calendar/events/${id}/`);
  },
  async holidays(): Promise<HolidayRow[]> {
    const { data } = await api.get("/office/calendar/holidays/", { params: { page_size: 500 } });
    return data.results ?? data;
  },
  async addHoliday(date: string, title: string): Promise<HolidayRow> {
    return (await api.post("/office/calendar/holidays/", { date, title })).data;
  },
  async deleteHoliday(id: number): Promise<void> {
    await api.delete(`/office/calendar/holidays/${id}/`);
  },
  async workweek(): Promise<WorkWeek> {
    return (await api.get("/office/calendar/workweek/")).data;
  },
  async setWorkweek(body: Partial<Pick<WorkWeek, "days_off" | "factory_days_off">>): Promise<WorkWeek> {
    return (await api.put("/office/calendar/workweek/", body)).data;
  },
  async event(id: number): Promise<CalendarEvent> {
    return (await api.get(`/office/calendar/events/${id}/`)).data;
  },
  async respond(id: number, body: {
    status: RsvpStatus; note?: string; proposed_start?: string; proposed_end?: string; wait_until?: string;
  }): Promise<Rsvp> {
    return (await api.post(`/office/calendar/events/${id}/respond/`, body)).data;
  },
  async decideProposal(id: number, user: number, decision: "accept" | "reject"): Promise<CalendarEvent> {
    return (await api.post(`/office/calendar/events/${id}/proposals/`, { user, decision })).data;
  },
  async cancel(id: number, reason: string, occurrence?: string): Promise<CalendarEvent> {
    return (await api.post(`/office/calendar/events/${id}/cancel/`, { reason, occurrence })).data;
  },
  /** Change one occurrence of a series on its own. */
  async saveOccurrence(id: number, original_start: string, body: Partial<CalendarEvent>): Promise<CalendarEvent> {
    return (await api.post(`/office/calendar/events/${id}/occurrence/`, { ...body, original_start })).data;
  },
  async comments(id: number): Promise<EventComment[]> {
    return (await api.get(`/office/calendar/events/${id}/comments/`)).data;
  },
  async addComment(id: number, body: { body: string; parent?: number | null; mentions?: number[]; attachments?: NewFile[] }): Promise<EventComment[]> {
    return (await api.post(`/office/calendar/events/${id}/comments/`, body)).data;
  },
  async editComment(id: number, cid: number, body: string): Promise<EventComment[]> {
    return (await api.patch(`/office/calendar/events/${id}/comments/${cid}/`, { body })).data;
  },
  async deleteComment(id: number, cid: number): Promise<EventComment[]> {
    return (await api.delete(`/office/calendar/events/${id}/comments/${cid}/`)).data;
  },
  async commentVersions(id: number, cid: number): Promise<{ body: string; at: string }[]> {
    return (await api.get(`/office/calendar/events/${id}/comments/${cid}/versions/`)).data;
  },
  async addFile(id: number, file: NewFile): Promise<CalendarEvent> {
    return (await api.post(`/office/calendar/events/${id}/attachments/`, file)).data;
  },
  async file(id: number, aid: number): Promise<FileMeta & { content: string }> {
    return (await api.get(`/office/calendar/events/${id}/attachments/${aid}/`)).data;
  },
  async deleteFile(id: number, aid: number): Promise<void> {
    await api.delete(`/office/calendar/events/${id}/attachments/${aid}/`);
  },
  async saveMinutes(id: number, minutes: string, action_items: { title: string; assignee: number | null; due_on: string | null }[]): Promise<CalendarEvent> {
    return (await api.put(`/office/calendar/events/${id}/minutes/`, { minutes, action_items })).data;
  },
  async history(id: number): Promise<HistoryRow[]> {
    return (await api.get(`/office/calendar/events/${id}/history/`)).data;
  },
  async invitations(box: "received" | "sent"): Promise<CalendarEvent[]> {
    return (await api.get("/office/calendar/invitations/", { params: { box } })).data;
  },
  /** What the caller already has then, on their own calendar. */
  async conflicts(from: string, to: string, exclude?: number): Promise<Busy[]> {
    return (await api.get("/office/calendar/conflicts/", { params: { from, to, exclude } })).data;
  },
  async preferences(): Promise<{ share_free_busy: boolean }> {
    return (await api.get("/office/calendar/preferences/")).data;
  },
  async savePreferences(body: { share_free_busy: boolean }): Promise<{ share_free_busy: boolean }> {
    return (await api.put("/office/calendar/preferences/", body)).data;
  },
  async downloadIcs(id?: number): Promise<void> {
    const url = id ? `/office/calendar/events/${id}/ics/` : "/office/calendar/ics/";
    saveAsFile(await api.get(url, { responseType: "blob" }), id ? `event-${id}.ics` : "calendar.ics");
  },
  /** When each person is busy (never with what), ISO pairs; null — they keep it private. */
  async freebusy(users: number[], from: string, to: string, exclude?: number): Promise<Record<number, [string, string][] | null>> {
    const params: Record<string, string> = { users: users.join(","), from, to };
    if (exclude) params.exclude = String(exclude);
    return (await api.get("/office/calendar/freebusy/", { params })).data;
  },
  async settings(): Promise<CalendarSettings> {
    return (await api.get("/office/calendar/settings/")).data;
  },
  async saveSettings(body: Partial<Omit<CalendarSettings, "office_managers" | "sms_recipients">>
    & { office_managers?: number[]; sms_recipients?: number[] }) {
    return (await api.put("/office/calendar/settings/", body)).data as CalendarSettings;
  },
  async smsTest(user: number): Promise<{ ok: boolean; detail: string; code?: string }> {
    return (await api.post("/office/calendar/sms-test/", { user })).data;
  },
  async digestPreview(): Promise<string> {
    return (await api.get("/office/calendar/digest-preview/")).data.text;
  },
};

export const KIND_LABELS: Record<EventKind, string> = {
  meeting: "جلسه", event: "رویداد", task: "کار / پیگیری", reminder: "یادآوری",
};
export const PRIORITY_LABELS: Record<Priority, string> = { normal: "عادی", important: "مهم", urgent: "فوری" };
export const REPEAT_LABELS: Record<Repeat, string> = {
  "": "بدون تکرار", daily: "هر روز", weekdays: "روزهای کاری", weekly: "هر هفته",
  monthly: "هر ماه (شمسی)", yearly: "هر سال (شمسی)",
};
export const LEVEL_LABELS: Record<Level, string> = { read: "فقط مشاهده", write: "ثبت برنامه", manage: "مدیریت کامل" };

/** «۳۰ دقیقه قبل», «۱ روز قبل». */
export function leadLabel(min: number): string {
  const fa = (n: number) => n.toLocaleString("fa-IR");
  if (min === 0) return "هنگام شروع";
  if (min % 1440 === 0) return `${fa(min / 1440)} روز قبل`;
  if (min % 60 === 0) return `${fa(min / 60)} ساعت قبل`;
  return `${fa(min)} دقیقه قبل`;
}
export const LEAD_CHOICES = [0, 5, 10, 15, 30, 60, 120, 180, 1440, 2880, 10080];

export const RSVP_LABELS: Record<RsvpStatus, string> = {
  pending: "در انتظار پاسخ", accepted: "می‌آید", tentative: "شاید", declined: "نمی‌آید",
  more_time: "درخواست مهلت", proposed: "پیشنهاد زمان دیگر",
};

/** Read a picked file the way letters do: a data: URL the server stores as is. */
export function readFile(file: File): Promise<NewFile> {
  return new Promise((resolve, reject) => {
    if (file.size > 5 * 1024 * 1024) return reject(new Error(`حجم «${file.name}» بیش از ۵ مگابایت است.`));
    const r = new FileReader();
    r.onload = () => resolve({ name: file.name, mime: file.type, content: String(r.result) });
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

export function openFile(f: { name: string; content: string }): void {
  const a = document.createElement("a");
  a.href = f.content;
  a.download = f.name;
  a.click();
}
