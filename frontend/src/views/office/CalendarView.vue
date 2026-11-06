<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { calendarApi, type CalendarEvent, type CalendarMonth, type CalendarRow, type HolidayRow, type MonthDay } from "@/api/officeCalendar";
import { useAuthStore } from "@/stores/auth";
import { apiError } from "@/components/crm/formError";
import { toast } from "@/composables/useUi";
import JalaliDateField from "@/components/JalaliDateField.vue";

/**
 * تقویم کاری — the month as the company works it.
 *
 * Holidays and the weekly days off are shaded on every calendar; each calendar
 * (the company's, management's, each unit's) is a coloured layer that can be
 * hidden. A click on a day adds an event to a calendar the user may write to;
 * which ones that is, and who sees what, the server decides.
 */
const auth = useAuthStore();
const isAdmin = computed(() => auth.me?.role === "admin" || !!auth.me?.is_superuser);

const MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];
const WEEKDAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"];
const FA = new Intl.NumberFormat("fa-IR", { useGrouping: false });

const calendars = ref<CalendarRow[]>([]);
const hidden = ref<Set<number>>(new Set());
const month = ref<CalendarMonth | null>(null);
const jy = ref(0);
const jm = ref(0);
const loading = ref(true);

async function load() {
  loading.value = true;
  try {
    month.value = await calendarApi.month(jy.value, jm.value);
    jy.value = month.value.jy;
    jm.value = month.value.jm;
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  calendars.value = await calendarApi.calendars();
  await load();
  if (isAdmin.value) await loadAdmin();
});

function shift(by: number) {
  let m = jm.value + by, y = jy.value;
  if (m < 1) { m = 12; y -= 1; }
  if (m > 12) { m = 1; y += 1; }
  jy.value = y; jm.value = m;
  load();
}

const leading = computed(() => month.value?.days[0]?.weekday ?? 0);
const visibleEvents = computed(() => (month.value?.events ?? []).filter((e) => !hidden.value.has(e.calendar)));

/** Events touching a day (multi-day events show on each of their days). */
function eventsOn(d: MonthDay): CalendarEvent[] {
  return visibleEvents.value.filter((e) => e.start.slice(0, 10) <= d.date && e.end.slice(0, 10) >= d.date);
}
const time = (iso: string) => new Date(iso).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
const today = new Date().toISOString().slice(0, 10);

function toggle(id: number) {
  const next = new Set(hidden.value);
  next.has(id) ? next.delete(id) : next.add(id);
  hidden.value = next;
}

// ---- event form ------------------------------------------------------------
const writable = computed(() => calendars.value.filter((c) => c.can_write));
const editing = ref<CalendarEvent | null>(null);
const open = ref(false);
const saving = ref(false);
const form = reactive({ calendar: 0, title: "", date: "", from: "09:00", to: "10:00", all_day: false, location: "", description: "" });

function newEvent(d: MonthDay) {
  if (!writable.value.length) return;
  editing.value = null;
  Object.assign(form, { calendar: writable.value[0].id, title: "", date: d.date, from: "09:00", to: "10:00",
                        all_day: false, location: "", description: "" });
  open.value = true;
}

function showEvent(e: CalendarEvent) {
  editing.value = e;
  const hhmm = (iso: string) => new Date(iso).toTimeString().slice(0, 5);
  Object.assign(form, { calendar: e.calendar, title: e.title, date: e.start.slice(0, 10), from: hhmm(e.start),
                        to: hhmm(e.end), all_day: e.all_day, location: e.location, description: e.description });
  open.value = true;
}

async function save() {
  if (!form.title.trim()) return toast.error("عنوان را بنویسید.");
  saving.value = true;
  try {
    const at = (t: string) => `${form.date}T${form.all_day ? (t === form.from ? "00:00" : "23:59") : t}`;
    await calendarApi.saveEvent({
      calendar: form.calendar, title: form.title.trim(), start: at(form.from), end: at(form.to),
      all_day: form.all_day, location: form.location, description: form.description,
    }, editing.value?.id);
    open.value = false;
    await load();
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!editing.value || !window.confirm(`«${editing.value.title}» حذف شود؟`)) return;
  try {
    await calendarApi.deleteEvent(editing.value.id);
    open.value = false;
    await load();
  } catch (e) {
    toast.error(apiError(e));
  }
}

// ---- admin: holidays and the weekly days off ---------------------------------
const holidays = ref<HolidayRow[]>([]);
const daysOff = ref<number[]>([]);
const newHoliday = reactive({ date: "", title: "" });

async function loadAdmin() {
  [holidays.value, daysOff.value] = await Promise.all([calendarApi.holidays(), calendarApi.workweek()]);
}
async function addHoliday() {
  if (!newHoliday.date || !newHoliday.title.trim()) return toast.error("تاریخ و عنوان تعطیلی را وارد کنید.");
  try {
    await calendarApi.addHoliday(newHoliday.date.slice(0, 10), newHoliday.title.trim());
    Object.assign(newHoliday, { date: "", title: "" });
    await Promise.all([loadAdmin(), load()]);
  } catch (e) {
    toast.error(apiError(e));
  }
}
async function removeHoliday(h: HolidayRow) {
  if (!window.confirm(`تعطیلی «${h.title}» برداشته شود؟`)) return;
  await calendarApi.deleteHoliday(h.id);
  await Promise.all([loadAdmin(), load()]);
}
async function toggleDayOff(d: number) {
  const next = daysOff.value.includes(d) ? daysOff.value.filter((x) => x !== d) : [...daysOff.value, d];
  daysOff.value = await calendarApi.setWorkweek(next);
  await load();
}
watch(isAdmin, (v) => { if (v) loadAdmin(); });
</script>

<template>
  <div class="space-y-4">
    <div class="office-card p-4 flex flex-wrap items-center gap-3">
      <button class="rounded-lg px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-sm" aria-label="ماه قبل" @click="shift(-1)">›</button>
      <h2 class="text-lg font-bold text-ink min-w-[140px] text-center">{{ MONTHS[jm - 1] }} {{ FA.format(jy) }}</h2>
      <button class="rounded-lg px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-sm" aria-label="ماه بعد" @click="shift(1)">‹</button>
      <span v-if="month" class="text-xs text-slate-500">{{ FA.format(month.workdays) }} روز کاری</span>
      <span class="flex-1"></span>
      <button
        v-for="c in calendars" :key="c.id"
        class="text-xs rounded-full px-2.5 py-1 border transition flex items-center gap-1.5"
        :class="hidden.has(c.id) ? 'border-slate-200 text-slate-400' : 'border-transparent bg-slate-100 text-ink'"
        :title="c.kind_display" @click="toggle(c.id)"
      >
        <span class="w-2.5 h-2.5 rounded-full" :style="{ background: hidden.has(c.id) ? '#cbd5e1' : c.color }"></span>{{ c.name }}
      </button>
    </div>

    <div class="office-card p-2 overflow-x-auto">
      <div class="grid grid-cols-7 sm:min-w-[700px] text-xs">
        <div v-for="w in WEEKDAYS" :key="w" class="text-center text-slate-400 py-2 truncate"><span class="sm:hidden">{{ w.charAt(0) }}</span><span class="hidden sm:inline">{{ w }}</span></div>
        <div v-for="i in leading" :key="`b${i}`"></div>
        <div
          v-for="d in month?.days ?? []" :key="d.date"
          class="min-h-[64px] sm:min-h-[96px] min-w-0 overflow-hidden border border-slate-100 rounded-lg m-px sm:m-0.5 p-1 sm:p-1.5 cursor-pointer hover:border-sky-300 transition"
          :class="[d.workday ? 'bg-surface' : 'bg-rose-50/70', d.date === today ? 'ring-2 ring-sky-400' : '']"
          @click="newEvent(d)"
        >
          <div class="flex items-center justify-between">
            <span class="font-semibold" :class="d.workday ? 'text-ink' : 'text-rose-600'">{{ FA.format(d.day) }}</span>
            <span v-if="d.off" class="hidden sm:inline text-[10px] text-rose-500 truncate max-w-[70%]" :title="d.off">{{ d.off }}</span>
          </div>
          <button
            v-for="e in eventsOn(d)" :key="`${e.id}-${d.date}`"
            class="block w-full text-right truncate rounded px-0.5 sm:px-1 py-0.5 mt-1 text-[10px] sm:text-[11px] text-white"
            :style="{ background: e.color }" :title="`${e.title} · ${e.calendar_name}`"
            @click.stop="showEvent(e)"
          >{{ e.all_day ? "" : time(e.start) + " " }}{{ e.title }}</button>
        </div>
      </div>
      <p v-if="loading" class="text-xs text-slate-400 p-2">در حال بارگذاری…</p>
      <p v-else-if="writable.length" class="text-[11px] text-slate-400 p-2">برای ثبت جلسه یا برنامه روی روز کلیک کنید.</p>
    </div>

    <!-- Admin: holidays and the weekly days off -->
    <div v-if="isAdmin" class="office-card p-4 space-y-3">
      <h3 class="font-semibold text-ink">تعطیلات (فقط ادمین)</h3>
      <div class="flex flex-wrap items-center gap-2 text-sm">
        <span class="text-slate-500">تعطیل هفتگی:</span>
        <label v-for="(w, i) in WEEKDAYS" :key="w" class="flex items-center gap-1 text-xs bg-slate-100 rounded-full px-2 py-1 cursor-pointer">
          <input type="checkbox" :checked="daysOff.includes(i)" @change="toggleDayOff(i)" />{{ w }}
        </label>
      </div>
      <form class="flex flex-wrap gap-2 items-end" @submit.prevent="addHoliday">
        <div class="w-full sm:w-44"><JalaliDateField v-model="newHoliday.date" placeholder="تاریخ" /></div>
        <input v-model="newHoliday.title" placeholder="عنوان تعطیلی، مثلاً «عید فطر»" class="flex-1 min-w-[180px] bg-slate-100 rounded-xl px-3 py-2 text-sm" />
        <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm">+ افزودن تعطیلی</button>
      </form>
      <ul class="grid sm:grid-cols-2 lg:grid-cols-3 gap-1.5 text-sm">
        <li v-for="h in holidays" :key="h.id" class="flex items-center justify-between bg-rose-50 rounded-lg px-3 py-1.5">
          <span><b class="ltr-nums">{{ h.jalali }}</b> · {{ h.title }}</span>
          <button class="text-xs text-red-500" @click="removeHoliday(h)">حذف</button>
        </li>
        <li v-if="!holidays.length" class="text-xs text-slate-400">هنوز تعطیلی‌ای ثبت نشده.</li>
      </ul>
    </div>

    <!-- Event form -->
    <div v-if="open" class="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" @click.self="open = false">
      <form class="bg-surface rounded-2xl shadow-pop w-full max-w-md max-h-[calc(100dvh-2rem)] overflow-y-auto p-5 space-y-3" role="dialog" @submit.prevent="save">
        <h3 class="font-bold text-ink">{{ editing ? (editing.can_edit ? "ویرایش برنامه" : editing.title) : "برنامه‌ی جدید" }}</h3>
        <template v-if="!editing || editing.can_edit">
          <select v-model="form.calendar" class="w-full bg-slate-100 rounded-xl px-3 py-2 text-sm" aria-label="تقویم">
            <option v-for="c in writable" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
          <input v-model="form.title" placeholder="عنوان (مثلاً جلسه‌ی فروش ماهانه)" class="w-full bg-slate-100 rounded-xl px-3 py-2 text-sm" />
          <JalaliDateField v-model="form.date" placeholder="تاریخ" />
          <label class="flex items-center gap-2 text-sm"><input v-model="form.all_day" type="checkbox" /> تمام روز</label>
          <div v-if="!form.all_day" class="flex gap-2 text-sm">
            <label class="flex-1 min-w-0">از <input v-model="form.from" type="time" class="w-full bg-slate-100 rounded-xl px-3 py-2" /></label>
            <label class="flex-1 min-w-0">تا <input v-model="form.to" type="time" class="w-full bg-slate-100 rounded-xl px-3 py-2" /></label>
          </div>
          <input v-model="form.location" placeholder="مکان" class="w-full bg-slate-100 rounded-xl px-3 py-2 text-sm" />
          <textarea v-model="form.description" rows="3" placeholder="توضیحات" class="w-full bg-slate-100 rounded-xl px-3 py-2 text-sm"></textarea>
          <div class="flex items-center gap-2">
            <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm disabled:opacity-50" :disabled="saving">ذخیره</button>
            <button type="button" class="text-sm text-slate-500 px-3" @click="open = false">انصراف</button>
            <span class="flex-1"></span>
            <button v-if="editing" type="button" class="text-sm text-red-500" @click="remove">حذف</button>
          </div>
        </template>
        <template v-else>
          <p class="text-sm text-slate-600">{{ editing.calendar_name }} · {{ editing.all_day ? "تمام روز" : `${time(editing.start)} تا ${time(editing.end)}` }}</p>
          <p v-if="editing.location" class="text-sm text-slate-600">مکان: {{ editing.location }}</p>
          <p v-if="editing.description" class="text-sm text-slate-600 whitespace-pre-line">{{ editing.description }}</p>
          <p class="text-xs text-slate-400">ثبت‌کننده: {{ editing.created_by_name }}</p>
          <button type="button" class="text-sm text-slate-500" @click="open = false">بستن</button>
        </template>
      </form>
    </div>
  </div>
</template>
