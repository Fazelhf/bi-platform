<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  calendarApi, KIND_LABELS, PRIORITY_LABELS, RSVP_LABELS,
  type CalendarEvent, type CalendarRange, type CalendarRow, type CalendarSettings, type RangeDay,
} from "@/api/officeCalendar";
import { officeApi, type Person } from "@/api/office";
import { useAuthStore } from "@/stores/auth";
import { store } from "@/lib/storage";
import { apiError } from "@/components/crm/formError";
import { confirm, toast } from "@/composables/useUi";
import NavIcon from "@/components/NavIcon.vue";
import { MONTH_NAMES, faDigits, isoToJalali, jalaliToIso, monthLength, todayIso } from "@/utils/jalali";
import EventDialog from "@/components/office/calendar/EventDialog.vue";
import CalendarSettingsPanel from "@/components/office/calendar/CalendarSettingsPanel.vue";
import EventPreview from "@/components/office/calendar/EventPreview.vue";

/**
 * تقویم — the company's calendars, read the way Google Calendar reads them.
 *
 * One person sees only their own calendars by default (theirs, the
 * company's, their unit's; management's for managers; the CEO's for the
 * office manager). Everything else they may see waits under «سایر تقویم‌ها»
 * until switched on, so a manager is not handed seven units' meetings at once.
 * Day / week / month / year / agenda views share one fetched window.
 */
type View = "day" | "week" | "month" | "year" | "agenda" | "invites";
const VIEWS: { id: View; label: string; key: string }[] = [
  { id: "day", label: "روز", key: "d" }, { id: "week", label: "هفته", key: "w" },
  { id: "month", label: "ماه", key: "m" }, { id: "year", label: "سال", key: "y" },
  { id: "agenda", label: "برنامه‌ها", key: "a" },
  { id: "invites", label: "دعوت‌نامه‌ها", key: "i" },
];
const WEEKDAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"];
const WEEKDAYS_SHORT = ["ش", "ی", "د", "س", "چ", "پ", "ج"];
const HOUR_PX = 48;

const auth = useAuthStore();
const isAdmin = computed(() => auth.me?.role === "admin" || !!auth.me?.is_superuser);

// ---- dates (ISO "YYYY-MM-DD", local wall-clock days) ---------------------------
const pad = (n: number) => String(n).padStart(2, "0");
const toIso = (d: Date) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
const fromIso = (iso: string) => new Date(Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)));
const addDays = (iso: string, n: number) => toIso(new Date(fromIso(iso).getTime() + n * 86_400_000));
const weekdayOf = (iso: string) => (fromIso(iso).getUTCDay() + 1) % 7; // 0 = شنبه
const localDay = (iso: string) => {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
const minutesOf = (iso: string) => { const d = new Date(iso); return d.getHours() * 60 + d.getMinutes(); };
const timeOf = (iso: string) => new Date(iso).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const jFirst = (iso: string) => { const j = isoToJalali(iso)!; return jalaliToIso({ jy: j.jy, jm: j.jm, jd: 1 }); };

const today = ref(todayIso());
const cursor = ref(today.value);
const view = ref<View>((store.get("calendar.view") as View) || "week");
watch(view, (v) => store.set("calendar.view", v));

/** The window the current view draws, [from, to). */
const window_ = computed(() => {
  const c = cursor.value;
  if (view.value === "day") return { from: c, to: addDays(c, 1) };
  if (view.value === "week") { const s = addDays(c, -weekdayOf(c)); return { from: s, to: addDays(s, 7) }; }
  if (view.value === "agenda") return { from: c, to: addDays(c, 30) };
  if (view.value === "year") {
    const j = isoToJalali(c)!;
    return { from: jalaliToIso({ jy: j.jy, jm: 1, jd: 1 }), to: jalaliToIso({ jy: j.jy + 1, jm: 1, jd: 1 }) };
  }
  const first = jFirst(c);
  const j = isoToJalali(c)!;
  const s = addDays(first, -weekdayOf(first));
  const end = addDays(first, monthLength(j.jy, j.jm));
  return { from: s, to: addDays(end, (7 - weekdayOf(end)) % 7) };
});

const title = computed(() => {
  const j = isoToJalali(cursor.value)!;
  const y = faDigits(j.jy);
  if (view.value === "year") return y;
  if (view.value === "day") return `${WEEKDAYS[weekdayOf(cursor.value)]} ${faDigits(j.jd)} ${MONTH_NAMES[j.jm - 1]} ${y}`;
  if (view.value === "week" || view.value === "agenda") {
    const a = isoToJalali(window_.value.from)!, b = isoToJalali(addDays(window_.value.to, -1))!;
    return a.jm === b.jm ? `${MONTH_NAMES[a.jm - 1]} ${faDigits(a.jy)}`
      : `${MONTH_NAMES[a.jm - 1]} – ${MONTH_NAMES[b.jm - 1]} ${faDigits(b.jy)}`;
  }
  return `${MONTH_NAMES[j.jm - 1]} ${y}`;
});

function shift(by: number) {
  const c = cursor.value;
  if (view.value === "day") cursor.value = addDays(c, by);
  else if (view.value === "week") cursor.value = addDays(c, 7 * by);
  else if (view.value === "agenda") cursor.value = addDays(c, 30 * by);
  else {
    const j = isoToJalali(c)!;
    const months = view.value === "year" ? 12 * by : by;
    const total = j.jy * 12 + (j.jm - 1) + months;
    const jy = Math.floor(total / 12), jm = (total % 12) + 1;
    cursor.value = jalaliToIso({ jy, jm, jd: Math.min(j.jd, monthLength(jy, jm)) });
  }
}
function goDay(iso: string) { cursor.value = iso; view.value = "day"; }

// ---- data --------------------------------------------------------------------
const calendars = ref<CalendarRow[]>([]);
const data = ref<CalendarRange | null>(null);
const people = ref<Person[]>([]);
const settings = ref<CalendarSettings | null>(null);
const loading = ref(true);

/** Which calendars are drawn: remembered per browser; first visit = the person's own. */
const shown = ref<Set<number>>(new Set());
function initShown() {
  const saved = store.getJSON<number[] | null>("calendar.shown", null);
  const ids = new Set(calendars.value.map((c) => c.id));
  shown.value = new Set(saved ? saved.filter((id) => ids.has(id)) : calendars.value.filter((c) => c.mine).map((c) => c.id));
}
function toggleCal(id: number) {
  const next = new Set(shown.value);
  next.has(id) ? next.delete(id) : next.add(id);
  shown.value = next;
  store.set("calendar.shown", JSON.stringify([...next]));
}
function only(id: number) {
  shown.value = new Set([id]);
  store.set("calendar.shown", JSON.stringify([id]));
}
const mine = computed(() => calendars.value.filter((c) => c.mine));
const others = computed(() => calendars.value.filter((c) => !c.mine));
const othersOpen = ref(false);

let seq = 0;
async function load() {
  const n = ++seq;
  loading.value = true;
  try {
    const r = await calendarApi.range(window_.value.from, window_.value.to);
    if (n === seq) data.value = r;
  } finally {
    if (n === seq) loading.value = false;
  }
}
watch(window_, load, { deep: true });

async function loadMeta() {
  [calendars.value, settings.value] = await Promise.all([calendarApi.calendars(), calendarApi.settings()]);
}

onMounted(async () => {
  await loadMeta();
  initShown();
  await load();
  officeApi.people().then((r) => (people.value = r.people)).catch(() => {});
  window.addEventListener("keydown", onKey);
  tick = window.setInterval(() => { now.value = new Date(); today.value = todayIso(); }, 60_000);
  scrollToMorning();
  openFromRoute();
});
onBeforeUnmount(() => { window.removeEventListener("keydown", onKey); clearInterval(tick); });

const events = computed(() => (data.value?.events ?? []).filter(
  (e) => shown.value.has(e.calendar) || (!!e.home_calendar && shown.value.has(e.home_calendar)),
));
const dayInfo = computed(() => new Map((data.value?.days ?? []).map((d) => [d.date, d])));
/**
 * Working days in what the title names: the month in month view — not the
 * spill-over days from the months either side that fill its grid — the week,
 * the year, or the agenda's 30 days.
 */
const workdayCount = computed(() => {
  const days = data.value?.days ?? [];
  if (view.value !== "month") return days.filter((d) => d.workday).length;
  const j = isoToJalali(cursor.value)!;
  return days.filter((d) => d.workday && d.jalali[0] === j.jy && d.jalali[1] === j.jm).length;
});
const workdayHint = "روزهای کاری شرکت؛ تعطیلی‌های هفتگی و رسمی کسر شده است";

/** Occurrences by the local days they touch. */
const byDay = computed(() => {
  const m = new Map<string, CalendarEvent[]>();
  for (const e of events.value) {
    let d = localDay(e.start);
    const last = localDay(new Date(new Date(e.end).getTime() - (e.all_day ? 0 : 1)).toISOString());
    for (let i = 0; d <= last && i < 400; i++, d = addDays(d, 1)) {
      if (!m.has(d)) m.set(d, []);
      m.get(d)!.push(e);
    }
  }
  return m;
});
const on = (iso: string) => byDay.value.get(iso) ?? [];

// ---- day / week time grid --------------------------------------------------------
const gridDays = computed(() => {
  const out: string[] = [];
  for (let d = window_.value.from; d < window_.value.to; d = addDays(d, 1)) out.push(d);
  return out;
});
const isTimed = (e: CalendarEvent) => !e.all_day && localDay(e.start) === localDay(new Date(new Date(e.end).getTime() - 1).toISOString());

/** Timed events of one day, placed in side-by-side lanes where they overlap. */
function placed(iso: string) {
  const list = on(iso).filter(isTimed).sort((a, b) => a.start.localeCompare(b.start) || b.end.localeCompare(a.end));
  const out: { e: CalendarEvent; top: number; height: number; lane: number; lanes: number }[] = [];
  let cluster: typeof out = [];
  let clusterEnd = -1;
  const flush = () => { const n = Math.max(1, ...cluster.map((c) => c.lane + 1)); cluster.forEach((c) => (c.lanes = n)); cluster = []; };
  const laneEnds: number[] = [];
  for (const e of list) {
    const s = minutesOf(e.start), en = Math.max(s + 20, minutesOf(e.end) || 24 * 60);
    if (s >= clusterEnd) { flush(); laneEnds.length = 0; }
    let lane = laneEnds.findIndex((x) => x <= s);
    if (lane < 0) { lane = laneEnds.length; laneEnds.push(en); } else laneEnds[lane] = en;
    const item = { e, top: (s / 60) * HOUR_PX, height: ((en - s) / 60) * HOUR_PX - 2, lane, lanes: 1 };
    out.push(item); cluster.push(item);
    clusterEnd = Math.max(clusterEnd, en);
  }
  flush();
  return out;
}
const allDayOf = (iso: string) => on(iso).filter((e) => !isTimed(e));

const now = ref(new Date());
let tick = 0;
const nowTop = computed(() => ((now.value.getHours() * 60 + now.value.getMinutes()) / 60) * HOUR_PX);
const scroller = ref<HTMLElement | null>(null);
async function scrollToMorning() {
  await nextTick();
  if (scroller.value) scroller.value.scrollTop = 7 * HOUR_PX;
}
watch(view, (v) => { if (v === "day" || v === "week") scrollToMorning(); });

// ---- month / year -------------------------------------------------------------
const monthCells = computed(() => gridDays.value);
const curMonth = computed(() => isoToJalali(cursor.value)!.jm);
const yearMonths = computed(() => {
  const jy = isoToJalali(cursor.value)!.jy;
  return Array.from({ length: 12 }, (_, i) => {
    const first = jalaliToIso({ jy, jm: i + 1, jd: 1 });
    const days = Array.from({ length: monthLength(jy, i + 1) }, (_, k) => addDays(first, k));
    return { jm: i + 1, lead: weekdayOf(first), days };
  });
});
const dayNum = (iso: string) => faDigits(isoToJalali(iso)!.jd);
const info = (iso: string): RangeDay | undefined => dayInfo.value.get(iso);
const isOff = (iso: string) => info(iso) ? !info(iso)!.workday : weekdayOf(iso) === 6;

// ---- agenda -------------------------------------------------------------------
const agenda = computed(() => gridDays.value.map((d) => ({ d, list: on(d) })).filter((x) => x.list.length));

// ---- mini month (sidebar) --------------------------------------------------------
const mini = ref(jFirst(cursor.value));
watch(cursor, (c) => (mini.value = jFirst(c)));
const miniCells = computed(() => {
  const j = isoToJalali(mini.value)!;
  const lead = weekdayOf(mini.value);
  return [...Array(lead).fill(""), ...Array.from({ length: monthLength(j.jy, j.jm) }, (_, k) => addDays(mini.value, k))];
});
function miniShift(by: number) {
  const j = isoToJalali(mini.value)!;
  const total = j.jy * 12 + (j.jm - 1) + by;
  mini.value = jalaliToIso({ jy: Math.floor(total / 12), jm: (total % 12) + 1, jd: 1 });
}
const inWindow = (iso: string) => iso >= window_.value.from && iso < window_.value.to && view.value !== "year";

// ---- the dialogs -------------------------------------------------------------------
const dialog = ref<{ event: CalendarEvent | null; at: string; occurrence?: string } | null>(null);
const canWrite = computed(() => calendars.value.some((c) => c.can_write));
function create(at: string) { if (canWrite.value) dialog.value = { event: null, at }; }
/** A click shows the event (the invitation, its answers, its discussion); editing is a button there. */
const preview = ref<CalendarEvent | null>(null);
function openEvent(e: CalendarEvent) { preview.value = e; }
/** A notification links here as ?event=<id>: go to its day and open it. */
const route = useRoute();
const router = useRouter();
async function openFromRoute() {
  const id = Number(route.query.event);
  if (!id) return;
  try {
    const e = await calendarApi.event(id);
    cursor.value = localDay(e.start);
    preview.value = { ...e, key: `${e.id}@link` };
  } catch {
    toast.error("این برنامه پیدا نشد؛ ممکن است حذف شده باشد یا به آن دسترسی نداشته باشید.");
  }
  router.replace({ query: { ...route.query, event: undefined } });
}
watch(() => route.query.event, (v) => { if (v) openFromRoute(); });

function editEvent(e: CalendarEvent, scope: "series" | "occurrence") {
  preview.value = null;
  dialog.value = { event: e, at: "", occurrence: scope === "occurrence" ? e.start : undefined };
}

// ---- the invitation inbox ------------------------------------------------------------
const box = ref<"received" | "sent">("received");
const boxFilter = ref<string>("");
const boxRows = ref<CalendarEvent[]>([]);
const boxLoading = ref(false);
async function loadBox() {
  boxLoading.value = true;
  try { boxRows.value = await calendarApi.invitations(box.value); } finally { boxLoading.value = false; }
}
watch([view, box], () => { if (view.value === "invites") loadBox(); });
const boxShown = computed(() => boxRows.value.filter((e) => {
  if (!boxFilter.value) return true;
  if (box.value === "received") return (e.my_response?.status ?? "") === boxFilter.value;
  return e.responses.some((r) => r.status === boxFilter.value);
}));
const tally = (e: CalendarEvent) => {
  const c: Record<string, number> = {};
  for (const r of e.responses) c[r.status] = (c[r.status] ?? 0) + 1;
  return c;
};
async function exportIcs() {
  try { await calendarApi.downloadIcs(); } catch (err) { toast.error(apiError(err)); }
}
function slotClick(iso: string, ev: MouseEvent) {
  const rect = (ev.currentTarget as HTMLElement).getBoundingClientRect();
  const min = Math.floor(((ev.clientY - rect.top) / HOUR_PX) * 2) * 30;
  create(`${iso}T${pad(Math.floor(min / 60))}:${pad(min % 60)}`);
}
async function saved() { dialog.value = null; await load(); }

// ---- drag to move / resize -----------------------------------------------------
/**
 * Time grid: drag an event to another hour or day; drag its lower edge to
 * change when it ends (15-minute steps). Month view and the all-day row:
 * drop it on another day. A plain click (no movement) still opens it.
 * A repeating event moves as a whole series.
 */
const SNAP = 15;
const drag = ref<{
  e: CalendarEvent; mode: "move" | "resize"; x: number; y: number; day: string;
  dy: number; dx: number; days: number; moved: boolean;
} | null>(null);
const dragKey = computed(() => drag.value?.moved ? drag.value.e.key : "");

function startDrag(ev: PointerEvent, e: CalendarEvent, mode: "move" | "resize", day: string) {
  if (ev.button !== 0) return;
  drag.value = { e, mode, x: ev.clientX, y: ev.clientY, day, dy: 0, dx: 0, days: 0, moved: false };
  window.addEventListener("pointermove", onDragMove);
  window.addEventListener("pointerup", onDragEnd, { once: true });
}
function onDragMove(ev: PointerEvent) {
  const d = drag.value;
  if (!d) return;
  if (!d.moved && Math.hypot(ev.clientX - d.x, ev.clientY - d.y) < 5) return;
  if (!d.e.can_edit) return;
  d.moved = true;
  const step = (SNAP / 60) * HOUR_PX;
  d.dy = Math.round((ev.clientY - d.y) / step) * step;
  if (d.mode === "move") {
    // By x alone: the card under the pointer is still a child of the column it left.
    const col = [...document.querySelectorAll<HTMLElement>("[data-day]")].find((c) => {
      const r = c.getBoundingClientRect();
      return ev.clientX >= r.left && ev.clientX < r.right;
    });
    const from = document.querySelector<HTMLElement>(`[data-day="${d.day}"]`);
    if (col && from) {
      d.days = Math.round((fromIso(col.dataset.day!).getTime() - fromIso(d.day).getTime()) / 86_400_000);
      d.dx = col.getBoundingClientRect().left - from.getBoundingClientRect().left;
    }
  }
}
async function onDragEnd() {
  window.removeEventListener("pointermove", onDragMove);
  const d = drag.value;
  drag.value = null;
  if (!d) return;
  if (!d.moved) return openEvent(d.e);
  const minutes = Math.round((d.dy / HOUR_PX) * 60);
  if (d.mode === "move" && !minutes && !d.days) return;
  await moveEvent(d.e, d.mode === "move" ? d.days : 0, minutes, d.mode === "resize");
}

async function moveEvent(e: CalendarEvent, days: number, minutes: number, resize = false) {
  if (!e.can_edit) return;
  const shiftMs = days * 86_400_000 + minutes * 60_000;
  const first = new Date(e.series_start ?? e.start).getTime();
  const length = new Date(e.end).getTime() - new Date(e.start).getTime();
  const start = resize ? first : first + shiftMs;
  const end = Math.max(start + SNAP * 60_000, first + length + shiftMs);
  // A drag is a change of time like any other: say what it becomes, and ask.
  const occStart = new Date(e.start).getTime() + (resize ? 0 : shiftMs);
  const occEnd = Math.max(occStart + SNAP * 60_000, new Date(e.end).getTime() + shiftMs);
  const label = (ms: number) => { const d = new Date(ms); return `${faDigits(isoToJalali(localDay(d.toISOString()))!.jd)} ${MONTH_NAMES[isoToJalali(localDay(d.toISOString()))!.jm - 1]} ${timeOf(d.toISOString())}`; };
  const lines = [`زمان «${e.title}» به ${label(occStart)} تا ${timeOf(new Date(occEnd).toISOString())} تغییر کند؟`];
  if (e.repeat) lines.push("این برنامه تکراری است؛ همه‌ی تکرارهایش جابه‌جا می‌شوند.");
  if (e.attendees.length) lines.push("به دعوت‌شدگان اطلاع داده می‌شود و از آن‌ها دوباره پاسخ خواسته می‌شود.");
  if (!(await confirm({ title: resize ? "تغییر ساعت پایان" : "جابه‌جایی برنامه", message: lines.join("\n"), okText: "بله، تغییر بده" }))) {
    await load(); // Snap the card back to where it was.
    return;
  }
  try {
    await calendarApi.saveEvent({ start: new Date(start).toISOString(), end: new Date(end).toISOString() }, e.id);
    toast.success(resize ? "زمان پایان تغییر کرد." : "برنامه جابه‌جا شد.");
  } catch (err) {
    toast.error(apiError(err));
  }
  await load();
}

/** Month view / all-day row: native drag and drop between days. */
const dayDrag = ref<{ e: CalendarEvent; from: string } | null>(null);
const dropDay = ref("");
function onDayDragStart(ev: DragEvent, e: CalendarEvent, from: string) {
  if (!e.can_edit) return ev.preventDefault();
  dayDrag.value = { e, from };
  ev.dataTransfer?.setData("text/plain", e.key ?? String(e.id));
  if (ev.dataTransfer) ev.dataTransfer.effectAllowed = "move";
}
async function onDayDrop(to: string) {
  const d = dayDrag.value;
  dayDrag.value = null;
  dropDay.value = "";
  if (!d || d.from === to) return;
  await moveEvent(d.e, Math.round((fromIso(to).getTime() - fromIso(d.from).getTime()) / 86_400_000), 0);
}

const showSettings = ref(false);
async function settingsChanged() { await loadMeta(); await load(); }

// ---- search ----------------------------------------------------------------------
const q = ref("");
const results = ref<CalendarEvent[]>([]);
let qTimer = 0;
watch(q, (v) => {
  clearTimeout(qTimer);
  if (!v.trim()) { results.value = []; return; }
  qTimer = window.setTimeout(async () => { results.value = await calendarApi.search(v.trim()); }, 300);
});
function pick(e: CalendarEvent) { q.value = ""; results.value = []; cursor.value = localDay(e.start); if (view.value === "year") view.value = "week"; openEvent(e); }

// ---- keyboard ------------------------------------------------------------------
function onKey(e: KeyboardEvent) {
  const t = e.target as HTMLElement;
  if (dialog.value || preview.value || showSettings.value || e.ctrlKey || e.metaKey || e.altKey
      || /INPUT|TEXTAREA|SELECT/.test(t.tagName) || t.isContentEditable) return;
  const v = VIEWS.find((x) => x.key === e.key.toLowerCase());
  if (v) view.value = v.id;
  else if (e.key === "t" || e.key === "T") cursor.value = today.value;
  else if (e.key === "n" || e.key === "c") create(cursor.value);
  else if (e.key === "ArrowLeft" || e.key === "j") shift(1);
  else if (e.key === "ArrowRight" || e.key === "k") shift(-1);
  else return;
  // Handled: the key is a command, not text for the form it may just have opened.
  e.preventDefault();
}

const PRIORITY_RING: Record<string, string> = { normal: "", important: "ring-2 ring-amber-300", urgent: "ring-2 ring-rose-400" };

/**
 * How an invitation looks on the caller's calendar, as organisation calendars
 * draw it: unanswered — outlined, not filled; «شاید» — paler; declined —
 * faded and struck through. Events the caller is not invited to: solid.
 */
const rsvp = (e: CalendarEvent) => (e.cancelled_at ? "declined" : e.my_response?.status ?? "");
function chipStyle(e: CalendarEvent): Record<string, string> {
  const st = rsvp(e);
  if (st === "pending" || st === "more_time" || st === "proposed") return { background: "var(--color-surface, #fff)", color: e.color, border: `1.5px dashed ${e.color}` };
  if (st === "tentative") return { background: `${e.color}99` };
  if (st === "declined") return { background: `${e.color}40`, color: "#64748b" };
  return { background: e.color };
}
const chipClass = (e: CalendarEvent) =>
  rsvp(e) === "declined" ? "line-through" : ["pending", "more_time", "proposed"].includes(rsvp(e)) ? "" : "text-white";

/** Invitations waiting for the caller's answer, soonest first (within the drawn window). */
const pendingInvites = computed(() => {
  const seen = new Set<number>();
  return (data.value?.events ?? []).filter((e) => {
    if (!["pending", "more_time"].includes(e.my_response?.status ?? "") || e.cancelled_at || seen.has(e.id) || new Date(e.end) < now.value) return false;
    seen.add(e.id);
    return true;
  });
});
const chipTitle = (e: CalendarEvent) =>
  `${e.title} · ${e.calendar_name} · ${KIND_LABELS[e.kind]} · ${PRIORITY_LABELS[e.priority]}${e.location ? " · " + e.location : ""}`;
</script>

<template>
  <div class="flex gap-4 items-start">
    <!-- Sidebar -->
    <aside class="hidden lg:flex flex-col gap-4 w-64 shrink-0 sticky top-4">
      <button v-if="canWrite" class="office-card flex items-center gap-2 px-5 py-3 rounded-2xl text-sm font-semibold text-ink hover:shadow-pop transition self-start"
              @click="create(cursor)">
        <NavIcon name="plus" :size="20" class="text-sky-500" /> ایجاد برنامه
      </button>

      <div class="office-card p-3">
        <div class="flex items-center justify-between mb-2 text-sm">
          <b class="text-ink">{{ MONTH_NAMES[isoToJalali(mini)!.jm - 1] }} {{ faDigits(isoToJalali(mini)!.jy) }}</b>
          <span class="flex gap-1">
            <button class="w-7 h-7 rounded-full hover:bg-slate-100 flex items-center justify-center" aria-label="ماه قبل" @click="miniShift(-1)"><NavIcon name="chevron" :size="15" class="rotate-180" /></button>
            <button class="w-7 h-7 rounded-full hover:bg-slate-100 flex items-center justify-center" aria-label="ماه بعد" @click="miniShift(1)"><NavIcon name="chevron" :size="15" /></button>
          </span>
        </div>
        <div class="grid grid-cols-7 text-center text-[11px] gap-y-0.5">
          <span v-for="w in WEEKDAYS_SHORT" :key="w" class="text-slate-400 py-1">{{ w }}</span>
          <template v-for="(d, i) in miniCells" :key="i">
            <span v-if="!d"></span>
            <button v-else class="w-7 h-7 mx-auto rounded-full transition"
                    :class="[d === today ? 'bg-sky-500 text-white font-bold' : d === cursor ? 'bg-sky-100 text-sky-800 font-semibold' : inWindow(d) ? 'bg-slate-100' : 'hover:bg-slate-100',
                             weekdayOf(d) === 6 && d !== today ? 'text-rose-500' : '']"
                    @click="cursor = d">{{ dayNum(d) }}</button>
          </template>
        </div>
      </div>

      <div v-if="pendingInvites.length" class="office-card p-3 space-y-1.5 text-sm">
        <h4 class="text-xs font-semibold text-slate-500 flex items-center gap-1.5">
          <NavIcon name="inbox" :size="14" /> دعوت‌های منتظر پاسخ شما
          <span class="mr-auto rounded-full bg-sky-500 text-white text-[10px] px-1.5">{{ faDigits(pendingInvites.length) }}</span>
        </h4>
        <button v-for="e in pendingInvites.slice(0, 6)" :key="e.key" class="w-full text-right rounded-lg px-2 py-1.5 hover:bg-slate-50 border-r-2" :style="{ borderColor: e.color }" @click="openEvent(e)">
          <div class="truncate text-ink">{{ e.title }}</div>
          <div class="text-[11px] text-slate-500">{{ faDigits(isoToJalali(localDay(e.start))!.jd) }} {{ MONTH_NAMES[isoToJalali(localDay(e.start))!.jm - 1] }} · {{ e.all_day ? "تمام روز" : timeOf(e.start) }} · {{ e.created_by_name }}</div>
        </button>
      </div>

      <div class="office-card p-3 space-y-1 text-sm">
        <h4 class="text-xs font-semibold text-slate-500 mb-1">تقویم‌های من</h4>
        <div v-for="c in mine" :key="c.id" class="group flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-slate-50">
          <button class="flex-1 flex items-center gap-2 text-right min-w-0" :aria-pressed="shown.has(c.id)" @click="toggleCal(c.id)">
            <span class="w-4 h-4 rounded border-2 flex items-center justify-center text-[10px] text-white shrink-0"
                  :style="{ borderColor: c.color, background: shown.has(c.id) ? c.color : 'transparent' }"><NavIcon v-if="shown.has(c.id)" name="check" :size="11" /></span>
            <span class="truncate">{{ c.name }}</span>
          </button>
          <button class="opacity-0 group-hover:opacity-100 text-[10px] text-slate-400 hover:text-sky-600" title="فقط همین" @click="only(c.id)">فقط</button>
        </div>
        <button v-if="others.length" class="w-full flex items-center justify-between text-xs font-semibold text-slate-500 pt-2" @click="othersOpen = !othersOpen">
          <span>سایر تقویم‌ها ({{ faDigits(others.length) }})</span><NavIcon name="chevron" :size="14" class="transition" :class="othersOpen ? 'rotate-90' : '-rotate-90'" />
        </button>
        <template v-if="othersOpen">
          <div v-for="c in others" :key="c.id" class="group flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-slate-50">
            <button class="flex-1 flex items-center gap-2 text-right min-w-0" :aria-pressed="shown.has(c.id)" @click="toggleCal(c.id)">
              <span class="w-4 h-4 rounded border-2 flex items-center justify-center text-[10px] text-white shrink-0"
                    :style="{ borderColor: c.color, background: shown.has(c.id) ? c.color : 'transparent' }"><NavIcon v-if="shown.has(c.id)" name="check" :size="11" /></span>
              <span class="truncate">{{ c.name }}</span>
            </button>
            <button class="opacity-0 group-hover:opacity-100 text-[10px] text-slate-400 hover:text-sky-600" title="فقط همین" @click="only(c.id)">فقط</button>
          </div>
        </template>
      </div>
      <p class="text-[11px] text-slate-400 px-1 leading-5">برنامه‌ها را با کشیدن جابه‌جا کنید؛ لبه‌ی پایین برای تغییر ساعت پایان.<br />میان‌بر: <b>t</b> امروز · <b>d/w/m/y/a</b> نما · <b>n</b> برنامه‌ی جدید · ←/→ قبل/بعد</p>
    </aside>

    <!-- Main -->
    <section class="flex-1 min-w-0 space-y-3">
      <div class="office-card p-3 flex flex-wrap items-center gap-2">
        <button class="rounded-lg px-3 py-1.5 border border-slate-200 hover:bg-slate-50 text-sm" @click="cursor = today">امروز</button>
        <button class="w-8 h-8 rounded-full hover:bg-slate-100 flex items-center justify-center" aria-label="قبلی" @click="shift(-1)"><NavIcon name="chevron" :size="18" class="rotate-180" /></button>
        <button class="w-8 h-8 rounded-full hover:bg-slate-100 flex items-center justify-center" aria-label="بعدی" @click="shift(1)"><NavIcon name="chevron" :size="18" /></button>
        <h2 class="text-lg font-bold text-ink">{{ title }}</h2>
        <span v-if="data && view !== 'day' && view !== 'invites'" class="text-xs text-slate-500" :title="workdayHint">{{ faDigits(workdayCount) }} روز کاری</span>
        <span v-if="loading" class="text-xs text-slate-400">…</span>
        <span class="flex-1"></span>
        <div class="relative">
          <NavIcon name="search" :size="15" class="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
          <input v-model="q" placeholder="جستجوی برنامه" class="bg-slate-100 rounded-xl pr-8 pl-3 py-1.5 text-sm w-44 focus:w-60 transition-all focus:outline-none" />
          <ul v-if="results.length" class="absolute z-30 left-0 mt-1 w-72 bg-surface rounded-xl shadow-pop max-h-80 overflow-y-auto text-sm">
            <li v-for="e in results" :key="e.id">
              <button class="w-full text-right px-3 py-2 hover:bg-slate-50 flex gap-2 items-center" @click="pick(e)">
                <span class="w-2.5 h-2.5 rounded-full shrink-0" :style="{ background: e.color }"></span>
                <span class="flex-1 truncate">{{ e.title }}</span>
                <span class="text-xs text-slate-400">{{ faDigits(isoToJalali(localDay(e.start))!.jd) }} {{ MONTH_NAMES[isoToJalali(localDay(e.start))!.jm - 1] }}</span>
              </button>
            </li>
          </ul>
        </div>
        <div class="flex rounded-xl bg-slate-100 p-0.5 text-sm">
          <button v-for="v in VIEWS" :key="v.id" class="rounded-lg px-3 py-1 transition"
                  :class="view === v.id ? 'bg-surface shadow text-ink font-semibold' : 'text-slate-500'" @click="view = v.id">{{ v.label }}</button>
        </div>
        <button class="w-9 h-9 rounded-full hover:bg-slate-100 text-slate-600 flex items-center justify-center" aria-label="دریافت ICS" title="خروجی تقویم من (ICS) برای Outlook / Google" @click="exportIcs"><NavIcon name="download" :size="18" /></button>
        <button class="w-9 h-9 rounded-full hover:bg-slate-100 text-slate-600 flex items-center justify-center" aria-label="تنظیمات تقویم" title="تنظیمات تقویم" @click="showSettings = true"><NavIcon name="settings" :size="19" /></button>
        <button v-if="canWrite" class="lg:hidden bg-panel text-white rounded-xl px-3 py-1.5 text-sm" @click="create(cursor)">+ برنامه</button>
      </div>

      <!-- Mobile calendar filter -->
      <div class="lg:hidden flex gap-1.5 overflow-x-auto pb-1">
        <button v-for="c in calendars" :key="c.id" class="text-xs rounded-full px-2.5 py-1 border flex items-center gap-1.5 shrink-0"
                :class="shown.has(c.id) ? 'border-transparent bg-slate-100 text-ink' : 'border-slate-200 text-slate-400'" @click="toggleCal(c.id)">
          <span class="w-2.5 h-2.5 rounded-full" :style="{ background: shown.has(c.id) ? c.color : '#cbd5e1' }"></span>{{ c.name }}
        </button>
      </div>

      <!-- Day / week -->
      <div v-if="view === 'day' || view === 'week'" class="office-card overflow-hidden">
        <div class="overflow-x-auto">
          <div :class="view === 'week' ? 'min-w-[760px]' : ''">
            <div class="flex border-b border-slate-100">
              <div class="w-14 shrink-0"></div>
              <div v-for="d in gridDays" :key="d" class="flex-1 text-center py-2 border-r border-slate-100" :class="isOff(d) ? 'bg-rose-50/50' : ''">
                <div class="text-[11px]" :class="d === today ? 'text-sky-600' : 'text-slate-500'">{{ WEEKDAYS[weekdayOf(d)] }}</div>
                <button class="w-9 h-9 rounded-full text-lg font-semibold transition"
                        :class="d === today ? 'bg-sky-500 text-white' : isOff(d) ? 'text-rose-600 hover:bg-rose-100' : 'text-ink hover:bg-slate-100'"
                        @click="goDay(d)">{{ dayNum(d) }}</button>
                <div v-if="info(d)?.off" class="text-[10px] text-rose-500 truncate px-1" :title="info(d)!.off">{{ info(d)!.off }}</div>
                <div v-if="info(d) && !info(d)!.workday && info(d)!.factory_workday" class="text-[10px] text-slate-500 truncate px-1">کارخانه باز است</div>
              </div>
            </div>
            <!-- All-day row -->
            <div class="flex border-b border-slate-100 min-h-[28px]">
              <div class="w-14 shrink-0 text-[10px] text-slate-400 text-center pt-1">تمام روز</div>
              <div v-for="d in gridDays" :key="d" class="flex-1 border-r border-slate-100 p-0.5 space-y-0.5 cursor-pointer"
                   :class="dropDay === d ? 'bg-sky-50' : ''" @click="create(d)"
                   @dragover.prevent="dropDay = d" @dragleave="dropDay === d && (dropDay = '')" @drop.prevent="onDayDrop(d)">
                <button v-for="e in allDayOf(d)" :key="`${e.key}-${d}`" class="block w-full text-right truncate rounded px-1.5 py-0.5 text-[11px]"
                        :class="[PRIORITY_RING[e.priority], chipClass(e)]" :style="chipStyle(e)" :title="chipTitle(e)" :draggable="e.can_edit"
                        @dragstart="onDayDragStart($event, e, d)" @click.stop="openEvent(e)">{{ e.title }}</button>
              </div>
            </div>
            <!-- Hours -->
            <div ref="scroller" class="overflow-y-auto" style="height: 62vh">
              <div class="flex relative" :style="{ height: `${24 * HOUR_PX}px` }">
                <div class="w-14 shrink-0 relative">
                  <span v-for="h in 23" :key="h" class="absolute left-1 right-1 text-[10px] text-slate-400 text-center -translate-y-1/2" :style="{ top: `${h * HOUR_PX}px` }">{{ faDigits(pad(h)) }}:۰۰</span>
                </div>
                <div v-for="d in gridDays" :key="d" :data-day="d" class="flex-1 relative border-r border-slate-100 cursor-pointer" :class="isOff(d) ? 'bg-rose-50/30' : ''" @click="slotClick(d, $event)">
                  <div v-for="h in 24" :key="h" class="border-b border-slate-100" :style="{ height: `${HOUR_PX}px` }"></div>
                  <div v-for="p in placed(d)" :key="p.e.key" role="button" tabindex="0"
                       class="absolute rounded-md px-1.5 py-0.5 text-right text-[11px] overflow-hidden shadow-sm hover:z-10 hover:shadow-md select-none touch-none"
                       :class="[PRIORITY_RING[p.e.priority], chipClass(p.e), p.e.can_edit ? 'cursor-grab' : 'cursor-pointer',
                                dragKey === p.e.key ? 'z-30 opacity-90 shadow-lg cursor-grabbing' : 'transition']"
                       :style="{ ...chipStyle(p.e), top: `${p.top}px`, right: `calc(${(p.lane / p.lanes) * 100}% + 2px)`,
                                 width: dragKey === p.e.key && drag!.mode === 'move' ? 'calc(100% - 4px)' : `calc(${100 / p.lanes}% - 4px)`,
                                 height: `${Math.max(16, p.height + (dragKey === p.e.key && drag!.mode === 'resize' ? drag!.dy : 0))}px`,
                                 transform: dragKey === p.e.key && drag!.mode === 'move' ? `translate(${drag!.dx}px, ${drag!.dy}px)` : '' }"
                       :title="chipTitle(p.e)" @click.stop @keydown.enter="openEvent(p.e)"
                       @pointerdown.stop="startDrag($event, p.e, 'move', d)">
                    <div class="font-semibold truncate">{{ p.e.title }}</div>
                    <div class="opacity-90 truncate">{{ timeOf(p.e.start) }} – {{ timeOf(p.e.end) }}<span v-if="p.e.location"> · {{ p.e.location }}</span></div>
                    <div v-if="p.e.can_edit" class="absolute bottom-0 inset-x-0 h-2 cursor-ns-resize" @pointerdown.stop="startDrag($event, p.e, 'resize', d)"></div>
                  </div>
                  <div v-if="d === today" class="absolute left-0 right-0 h-0.5 bg-rose-500 pointer-events-none z-20" :style="{ top: `${nowTop}px` }">
                    <span class="absolute -right-1 -top-1 w-2.5 h-2.5 rounded-full bg-rose-500"></span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Month -->
      <div v-else-if="view === 'month'" class="office-card p-2 overflow-x-auto">
        <div class="grid grid-cols-7 min-w-[700px] text-xs">
          <div v-for="w in WEEKDAYS" :key="w" class="text-center text-slate-400 py-2">{{ w }}</div>
          <div v-for="d in monthCells" :key="d"
               class="min-h-[110px] border border-slate-100 -mt-px -mr-px p-1 cursor-pointer hover:bg-slate-50/60 transition"
               :class="[dropDay === d ? 'bg-sky-50 ring-2 ring-sky-300 ring-inset' : isOff(d) ? 'bg-rose-50/60' : 'bg-surface', isoToJalali(d)!.jm !== curMonth ? 'opacity-45' : '']"
               @click="create(d)" @dragover.prevent="dropDay = d" @dragleave="dropDay === d && (dropDay = '')" @drop.prevent="onDayDrop(d)">
            <div class="flex items-center justify-between">
              <button class="w-6 h-6 rounded-full font-semibold" :class="d === today ? 'bg-sky-500 text-white' : isOff(d) ? 'text-rose-600' : 'text-ink'" @click.stop="goDay(d)">{{ dayNum(d) }}</button>
              <span v-if="info(d)?.off && info(d)!.off !== 'تعطیل هفتگی'" class="text-[10px] text-rose-500 truncate max-w-[70%]" :title="info(d)!.off">{{ info(d)!.off }}</span>
            </div>
            <button v-for="e in on(d).slice(0, 3)" :key="`${e.key}-${d}`"
                    class="flex items-center gap-1 w-full text-right truncate rounded px-1 py-0.5 mt-0.5 text-[11px]"
                    :class="[e.all_day || !isTimed(e) ? chipClass(e) : 'text-ink hover:bg-slate-100', rsvp(e) === 'declined' ? 'line-through opacity-60' : '', rsvp(e) === 'pending' && isTimed(e) ? 'italic' : '']"
                    :style="e.all_day || !isTimed(e) ? chipStyle(e) : {}" :title="chipTitle(e)" :draggable="e.can_edit"
                    @dragstart="onDayDragStart($event, e, d)" @click.stop="openEvent(e)">
              <span v-if="isTimed(e)" class="w-2 h-2 rounded-full shrink-0" :style="{ background: e.color }"></span>
              <span v-if="isTimed(e)" class="text-slate-500">{{ timeOf(e.start) }}</span>
              <span class="truncate">{{ e.title }}</span>
              <span v-if="e.priority === 'urgent'" class="w-1.5 h-1.5 rounded-full bg-rose-500 shrink-0" title="فوری"></span>
            </button>
            <button v-if="on(d).length > 3" class="text-[11px] text-slate-500 hover:text-sky-600 mt-0.5 px-1" @click.stop="goDay(d)">+{{ faDigits(on(d).length - 3) }} مورد دیگر</button>
          </div>
        </div>
      </div>

      <!-- Year -->
      <div v-else-if="view === 'year'" class="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        <div v-for="m in yearMonths" :key="m.jm" class="office-card p-3">
          <button class="font-semibold text-ink text-sm mb-2 hover:text-sky-600" @click="cursor = m.days[0]; view = 'month'">{{ MONTH_NAMES[m.jm - 1] }}</button>
          <div class="grid grid-cols-7 text-center text-[11px] gap-y-0.5">
            <span v-for="w in WEEKDAYS_SHORT" :key="w" class="text-slate-400">{{ w }}</span>
            <span v-for="i in m.lead" :key="`l${i}`"></span>
            <button v-for="d in m.days" :key="d" class="relative w-7 h-7 mx-auto rounded-full transition"
                    :class="d === today ? 'bg-sky-500 text-white font-bold' : isOff(d) ? 'text-rose-500 hover:bg-rose-50' : 'hover:bg-slate-100'"
                    :title="info(d)?.off || (on(d).length ? `${faDigits(on(d).length)} برنامه` : '')" @click="goDay(d)">
              {{ dayNum(d) }}
              <span v-if="on(d).length" class="absolute bottom-0.5 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full" :style="{ background: on(d)[0].color }"></span>
            </button>
          </div>
        </div>
      </div>

      <!-- Invitations -->
      <div v-else-if="view === 'invites'" class="office-card">
        <div class="flex flex-wrap items-center gap-2 p-3 border-b border-slate-100">
          <div class="flex rounded-xl bg-slate-100 p-0.5 text-sm">
            <button v-for="b in (['received', 'sent'] as const)" :key="b" class="rounded-lg px-3 py-1 transition"
                    :class="box === b ? 'bg-surface shadow text-ink font-semibold' : 'text-slate-500'" @click="box = b; boxFilter = ''">{{ b === "received" ? "دریافتی" : "ارسالی" }}</button>
          </div>
          <select v-model="boxFilter" class="bg-slate-100 rounded-lg px-2 py-1.5 text-sm" aria-label="فیلتر وضعیت">
            <option value="">همه‌ی وضعیت‌ها</option>
            <option v-for="(label, st) in RSVP_LABELS" :key="st" :value="st">{{ label }}</option>
          </select>
          <span v-if="boxLoading" class="text-xs text-slate-400">…</span>
        </div>
        <div class="divide-y divide-slate-100">
          <button v-for="e in boxShown" :key="e.id" class="w-full flex items-center gap-3 text-right px-4 py-3 hover:bg-slate-50 text-sm"
                  @click="openEvent({ ...e, key: `${e.id}@inbox` })">
            <span class="w-1 self-stretch rounded-full shrink-0" :style="{ background: e.color }"></span>
            <div class="flex-1 min-w-0">
              <div class="truncate text-ink" :class="e.cancelled_at ? 'line-through text-slate-400' : ''">{{ e.title }}</div>
              <div class="text-xs text-slate-500">
                {{ faDigits(isoToJalali(localDay(e.start))!.jd) }} {{ MONTH_NAMES[isoToJalali(localDay(e.start))!.jm - 1] }}
                · {{ e.all_day ? "تمام روز" : timeOf(e.start) }}
                <template v-if="box === 'received'"> · از {{ e.created_by_name }}</template>
                <template v-if="e.respond_by"> · مهلت پاسخ {{ faDigits(isoToJalali(localDay(e.respond_by))!.jd) }} {{ MONTH_NAMES[isoToJalali(localDay(e.respond_by))!.jm - 1] }}</template>
              </div>
            </div>
            <span v-if="e.cancelled_at" class="text-[11px] rounded-full px-2 py-0.5 bg-rose-50 text-rose-700">لغو شد</span>
            <span v-else-if="box === 'received' && e.my_response" class="text-[11px] rounded-full px-2 py-0.5 bg-slate-100 text-slate-600">{{ RSVP_LABELS[e.my_response.status] }}</span>
            <span v-else class="text-[11px] text-slate-500 flex flex-wrap gap-x-2 justify-end max-w-[45%]">
              <span v-for="(n, st) in tally(e)" :key="st">{{ RSVP_LABELS[st as keyof typeof RSVP_LABELS] }} {{ faDigits(n) }}</span>
            </span>
          </button>
          <p v-if="!boxShown.length && !boxLoading" class="p-6 text-center text-sm text-slate-400">دعوت‌نامه‌ای نیست.</p>
        </div>
      </div>

      <!-- Agenda -->
      <div v-else class="office-card divide-y divide-slate-100">
        <div v-for="g in agenda" :key="g.d" class="flex gap-4 p-3">
          <button class="w-20 shrink-0 text-right" @click="goDay(g.d)">
            <div class="text-2xl font-bold" :class="g.d === today ? 'text-sky-600' : 'text-ink'">{{ dayNum(g.d) }}</div>
            <div class="text-xs text-slate-500">{{ MONTH_NAMES[isoToJalali(g.d)!.jm - 1] }} · {{ WEEKDAYS[weekdayOf(g.d)] }}</div>
          </button>
          <div class="flex-1 space-y-1.5">
            <button v-for="e in g.list" :key="`${e.key}-${g.d}`" class="w-full flex items-center gap-3 text-right rounded-lg px-2 py-1.5 hover:bg-slate-50 text-sm" @click="openEvent(e)">
              <span class="w-3 h-3 rounded-full shrink-0" :style="{ background: e.color }"></span>
              <span class="w-28 shrink-0 text-xs text-slate-500">{{ isTimed(e) ? `${timeOf(e.start)} – ${timeOf(e.end)}` : "تمام روز" }}</span>
              <span class="flex-1 truncate">{{ e.title }}<span v-if="e.location" class="text-slate-400"> · {{ e.location }}</span></span>
              <span v-if="e.priority !== 'normal'" class="text-[11px] rounded-full px-2 py-0.5" :class="e.priority === 'urgent' ? 'bg-rose-100 text-rose-700' : 'bg-amber-100 text-amber-800'">{{ PRIORITY_LABELS[e.priority] }}</span>
              <span class="text-[11px] text-slate-400 hidden sm:inline">{{ e.calendar_name }}</span>
            </button>
          </div>
        </div>
        <p v-if="!agenda.length && !loading" class="p-6 text-center text-sm text-slate-400">در این ۳۰ روز برنامه‌ای در تقویم‌های انتخاب‌شده نیست.</p>
      </div>
    </section>

    <EventPreview v-if="preview" :event="preview" :people="people" @close="preview = null" @edit="(s) => editEvent(preview!, s)"
                  @changed="load(); if (view === 'invites') loadBox()" />
    <EventDialog v-if="dialog" :event="dialog.event" :at="dialog.at" :occurrence="dialog.occurrence" :calendars="calendars" :people="people" :settings="settings"
                 @close="dialog = null" @saved="saved" />
    <CalendarSettingsPanel v-if="showSettings && settings" :calendars="calendars" :people="people" :settings="settings" :is-admin="isAdmin"
                           @close="showSettings = false" @changed="settingsChanged" />
  </div>
</template>
