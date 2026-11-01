import api from "./client";

/** تقویم کاری — the shared calendars, holidays and the weekly days off. */
export interface CalendarRow {
  id: number;
  name: string;
  kind: "company" | "management" | "unit";
  kind_display: string;
  department: string;
  color: string;
  can_write: boolean;
}

export interface CalendarEvent {
  id: number;
  calendar: number;
  calendar_name: string;
  color: string;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  location: string;
  description: string;
  attendees: number[];
  created_by_name: string;
  can_edit: boolean;
}

export interface MonthDay {
  date: string;
  day: number;
  /** 0 = شنبه … 6 = جمعه */
  weekday: number;
  workday: boolean;
  /** Why it is not worked: the holiday's title or «تعطیل هفتگی». */
  off: string;
}

export interface CalendarMonth {
  jy: number;
  jm: number;
  days: MonthDay[];
  workdays: number;
  events: CalendarEvent[];
}

export interface HolidayRow {
  id: number;
  date: string;
  title: string;
  jalali: string;
}

export const calendarApi = {
  async calendars(): Promise<CalendarRow[]> {
    return (await api.get("/office/calendar/calendars/")).data;
  },
  async month(jy: number, jm: number): Promise<CalendarMonth> {
    return (await api.get("/office/calendar/month/", { params: { jy, jm } })).data;
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
};
