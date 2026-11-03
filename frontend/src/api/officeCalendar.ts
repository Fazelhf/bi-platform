import api from "./client";

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
  /** The caller is an attendee. */
  invited?: boolean;
  /** Invited to an event on someone else's calendar: it shows on this one, the caller's own. */
  home_calendar?: number;
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
}

export interface CalendarRange {
  from: string;
  to: string;
  days: RangeDay[];
  workdays: number;
  events: CalendarEvent[];
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
  async workweek(): Promise<number[]> {
    return (await api.get("/office/calendar/workweek/")).data.days_off;
  },
  async setWorkweek(days_off: number[]): Promise<number[]> {
    return (await api.put("/office/calendar/workweek/", { days_off })).data.days_off;
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
