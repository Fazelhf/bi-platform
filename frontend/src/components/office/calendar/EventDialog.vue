<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";
import {
  calendarApi, KIND_LABELS, LEAD_CHOICES, leadLabel, PRIORITY_LABELS, REPEAT_LABELS,
  type CalendarEvent, type CalendarRow, type CalendarSettings, type EventKind, type Priority, type Repeat,
} from "@/api/officeCalendar";
import type { Person } from "@/api/office";
import { apiError } from "@/components/crm/formError";
import { confirm, toast } from "@/composables/useUi";
import JalaliDateField from "@/components/JalaliDateField.vue";
import NavIcon from "@/components/NavIcon.vue";
import { jalaliLabel } from "@/utils/jalali";

/**
 * One event: a new one (from a click on a day or a time slot), or an existing
 * one — editable if the caller made it or manages its calendar, otherwise a
 * read-only card. A repeating event is edited as a whole series.
 */
const props = defineProps<{
  event: CalendarEvent | null;
  /** For a new event: where the click landed — "YYYY-MM-DD" or "YYYY-MM-DDTHH:mm". */
  at: string;
  calendars: CalendarRow[];
  people: Person[];
  settings: CalendarSettings | null;
  /** Editing one occurrence of a series on its own: that occurrence's start. */
  occurrence?: string;
}>();
const emit = defineEmits<{ close: []; saved: [] }>();

const writable = computed(() => props.calendars.filter((c) => c.can_write));
const editable = computed(() => !props.event || props.event.can_edit);
const PRIORITY_TONE: Record<Priority, string> = {
  normal: "bg-slate-100 text-slate-700", important: "bg-amber-100 text-amber-800", urgent: "bg-rose-100 text-rose-700",
};

const pad = (n: number) => String(n).padStart(2, "0");
const localParts = (iso: string) => {
  const d = new Date(iso);
  return { date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`, time: `${pad(d.getHours())}:${pad(d.getMinutes())}` };
};

const form = reactive({
  calendar: 0, title: "", kind: "meeting" as EventKind, priority: "normal" as Priority,
  startDate: "", startTime: "09:00", endDate: "", endTime: "10:00", all_day: false,
  repeat: "" as Repeat, repeat_until: "", respond_by: "", customReminders: false, reminders: [] as number[],
  attendees: [] as number[], guests: [] as string[], location: "", online_link: "", description: "",
});

function reset() {
  const e = props.event;
  if (e) {
    // The whole series is edited from its first occurrence, so it does not
    // move; one occurrence on its own, from that occurrence.
    const from = props.occurrence ? e.start : e.series_start ?? e.start;
    const s = localParts(from);
    const length = new Date(e.end).getTime() - new Date(e.start).getTime();
    const en = localParts(new Date(new Date(from).getTime() + length).toISOString());
    Object.assign(form, {
      calendar: e.calendar, title: e.title, kind: e.kind, priority: e.priority,
      startDate: s.date, startTime: s.time, endDate: en.date, endTime: en.time, all_day: e.all_day,
      repeat: e.repeat, repeat_until: e.repeat_until ?? "", respond_by: e.respond_by ? localStamp(e.respond_by) : "",
      customReminders: e.reminders !== null,
      reminders: [...(e.reminders ?? [])], attendees: [...e.attendees], guests: [...(e.guests ?? [])], location: e.location, online_link: e.online_link ?? "",
      description: e.description,
    });
    if (props.occurrence) form.repeat = "";
    return;
  }
  const [date, time] = props.at.split("T");
  const startTime = time ?? "09:00";
  const [h, m] = startTime.split(":").map(Number);
  const endTime = `${pad(Math.min(h + 1, 23))}:${pad(m)}`;
  const own = writable.value.find((c) => c.kind === "personal" && c.mine) ?? writable.value.find((c) => c.mine) ?? writable.value[0];
  Object.assign(form, {
    calendar: own?.id ?? 0, title: "", kind: "meeting", priority: "normal",
    startDate: date, startTime, endDate: date, endTime, all_day: false,
    repeat: "", repeat_until: "", respond_by: "", customReminders: false, reminders: [], attendees: [], guests: [], location: "", online_link: "", description: "",
  });
}
watch(() => [props.event, props.at], reset, { immediate: true });
const titleEl = ref<HTMLInputElement | null>(null);
onMounted(() => nextTick(() => titleEl.value?.focus()));
watch(() => form.startDate, (d, old) => { if (!form.endDate || form.endDate === old || form.endDate < d) form.endDate = d; });

const defaultLeads = computed(() => props.settings?.priority_rules?.[form.priority]?.minutes ?? []);
const defaultSms = computed(() => !!props.settings?.priority_rules?.[form.priority]?.sms);
function toggleLead(m: number) {
  form.reminders = form.reminders.includes(m) ? form.reminders.filter((x) => x !== m) : [...form.reminders, m].sort((a, b) => b - a);
}

// ---- attendees: company members (the event lands on their calendar) and outside guests
const peopleById = computed(() => new Map(props.people.map((p) => [p.id, p])));
const memberPick = ref(0);
const available = computed(() => props.people.filter((p) => !form.attendees.includes(p.id)));
watch(memberPick, (id) => { if (id) { form.attendees.push(id); memberPick.value = 0; } });
const guest = ref("");
function addGuest() {
  const g = guest.value.trim();
  if (g && !form.guests.includes(g)) form.guests.push(g);
  guest.value = "";
}

// ---- save --------------------------------------------------------------------
const saving = ref(false);
async function save() {
  if (!form.title.trim()) return toast.error("عنوان را بنویسید.");
  if (!form.calendar) return toast.error("تقویمی برای ثبت ندارید.");
  const start = `${form.startDate}T${form.all_day ? "00:00" : form.startTime}`;
  const end = `${form.endDate || form.startDate}T${form.all_day ? "23:59" : form.endTime}`;
  if (end < start) return toast.error("پایان پیش از شروع است.");
  saving.value = true;
  try {
    const body = {
      calendar: form.calendar, title: form.title.trim(), kind: form.kind, priority: form.priority,
      start, end, all_day: form.all_day, repeat: form.repeat, repeat_until: form.repeat ? form.repeat_until || null : null,
      reminders: form.customReminders ? form.reminders : null, attendees: form.attendees,
      guests: [...form.guests, ...(guest.value.trim() ? [guest.value.trim()] : [])],
      respond_by: form.attendees.length && form.respond_by ? form.respond_by : null,
      location: form.location, online_link: form.online_link.trim(), description: form.description,
    };
    if (props.event && props.occurrence) {
      const { repeat: _r, repeat_until: _u, ...one } = body;
      await calendarApi.saveOccurrence(props.event.series ?? props.event.id, props.occurrence, one);
    } else {
      await calendarApi.saveEvent(body, props.event?.id);
    }
    toast.success(props.event ? "برنامه ویرایش شد." : "برنامه ثبت شد.");
    emit("saved");
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    saving.value = false;
  }
}

async function remove() {
  const e = props.event;
  if (!e) return;
  const msg = e.repeat ? `«${e.title}» و همه‌ی تکرارهایش حذف شود؟` : `«${e.title}» حذف شود؟`;
  if (!(await confirm({ message: msg, danger: true, okText: "حذف" }))) return;
  try {
    await calendarApi.deleteEvent(e.id);
    emit("saved");
  } catch (err) {
    toast.error(apiError(err));
  }
}

const timeOf = (iso: string) => new Date(iso).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
const field = "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-300";

function localStamp(iso: string) {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ---- who is busy then: when, never with what -----------------------------------------
/** Invitees who keep their time private (they did not opt in to free/busy). */
const unknown = ref<string[]>([]);
/** The organiser's own clashes, read from their own calendar only. */
const mine = ref<string[]>([]);
const busy = ref<string[]>([]);
let fbTimer = 0;
watch(() => [form.attendees.slice(), form.startDate, form.startTime, form.endDate, form.endTime, form.all_day], () => {
  clearTimeout(fbTimer);
  fbTimer = window.setTimeout(async () => {
    if (!form.startDate) { busy.value = mine.value = unknown.value = []; return; }
    const from = new Date(`${form.startDate}T${form.all_day ? "00:00" : form.startTime}`);
    const to = new Date(`${form.endDate || form.startDate}T${form.all_day ? "23:59" : form.endTime}`);
    if (!(to > from) || form.all_day) { busy.value = mine.value = unknown.value = []; return; }
    try {
      const own = await calendarApi.conflicts(from.toISOString(), to.toISOString(), props.event?.id);
      mine.value = own.map((c) => c.title);
    } catch { mine.value = []; }
    if (!form.attendees.length) { busy.value = unknown.value = []; return; }
    try {
      const fb = await calendarApi.freebusy(form.attendees, from.toISOString(), to.toISOString(), props.event?.id);
      const name = (id: number) => peopleById.value.get(id)?.name ?? "؟";
      busy.value = form.attendees.filter((id) => (fb[id] ?? []).length).map(name);
      unknown.value = form.attendees.filter((id) => fb[id] === null).map(name);
    } catch { busy.value = unknown.value = []; }
  }, 400);
}, { immediate: true });
</script>

<template>
  <div class="fixed inset-0 z-50 bg-black/30 flex items-start sm:items-center justify-center p-3 overflow-y-auto" @click.self="emit('close')">
    <!-- Read-only card -->
    <div v-if="event && !editable" class="bg-surface rounded-2xl shadow-pop w-full max-w-md p-5 space-y-3" role="dialog">
      <div class="flex items-start gap-3">
        <span class="w-3 h-3 rounded mt-1.5 shrink-0" :style="{ background: event.color }"></span>
        <div class="flex-1 min-w-0">
          <h3 class="font-bold text-ink text-lg">{{ event.title }}</h3>
          <p class="text-sm text-slate-600">
            {{ jalaliLabel(localParts(event.start).date) }} ·
            {{ event.all_day ? "تمام روز" : `${timeOf(event.start)} تا ${timeOf(event.end)}` }}
          </p>
          <p v-if="event.repeat" class="text-xs text-slate-500 flex items-center gap-1"><NavIcon name="refresh" :size="13" /> {{ REPEAT_LABELS[event.repeat] }}</p>
        </div>
        <button class="text-slate-400 hover:text-ink" aria-label="بستن" @click="emit('close')"><NavIcon name="close" :size="18" /></button>
      </div>
      <div class="flex flex-wrap gap-1.5 text-xs">
        <span class="rounded-full px-2 py-0.5 bg-slate-100">{{ KIND_LABELS[event.kind] }}</span>
        <span class="rounded-full px-2 py-0.5" :class="PRIORITY_TONE[event.priority]">{{ PRIORITY_LABELS[event.priority] }}</span>
        <span class="rounded-full px-2 py-0.5 bg-slate-100">{{ event.calendar_name }}</span>
      </div>
      <p v-if="event.location" class="text-sm text-slate-600 flex items-center gap-1.5"><NavIcon name="pin" :size="15" class="text-slate-400" /> {{ event.location }}</p>
      <p v-if="event.attendee_names.length" class="text-sm text-slate-600 flex items-start gap-1.5"><NavIcon name="users" :size="15" class="text-slate-400 mt-0.5" /> {{ event.attendee_names.join("، ") }}</p>
      <p v-if="event.guests?.length" class="text-sm text-slate-600 flex items-start gap-1.5"><NavIcon name="contact" :size="15" class="text-slate-400 mt-0.5" /> مهمان: {{ event.guests.join("، ") }}</p>
      <p v-if="event.description" class="text-sm text-slate-600 whitespace-pre-line">{{ event.description }}</p>
      <p class="text-xs text-slate-400">ثبت‌کننده: {{ event.created_by_name }}</p>
    </div>

    <!-- Form -->
    <form v-else class="bg-surface rounded-2xl shadow-pop w-full max-w-2xl p-5 space-y-4" role="dialog" @submit.prevent="save">
      <div class="flex items-center gap-2">
        <input ref="titleEl" v-model="form.title" placeholder="عنوان — مثلاً جلسه‌ی هیئت‌مدیره" class="flex-1 text-lg font-semibold bg-transparent border-b-2 border-slate-200 focus:border-sky-400 focus:outline-none py-1" />
        <button type="button" class="text-slate-400 hover:text-ink px-1" aria-label="بستن" @click="emit('close')"><NavIcon name="close" :size="18" /></button>
      </div>

      <div class="flex flex-wrap gap-1.5">
        <button v-for="(label, k) in KIND_LABELS" :key="k" type="button"
                class="text-xs rounded-full px-3 py-1.5 border transition"
                :class="form.kind === k ? 'bg-panel text-white border-transparent' : 'border-slate-200 text-slate-600 hover:bg-slate-50'"
                @click="form.kind = k">{{ label }}</button>
      </div>

      <div class="grid sm:grid-cols-2 gap-3">
        <div class="space-y-2">
          <span class="text-xs text-slate-500">شروع</span>
          <JalaliDateField v-model="form.startDate" placeholder="تاریخ شروع" />
          <input v-if="!form.all_day" v-model="form.startTime" type="time" :class="field" aria-label="ساعت شروع" />
        </div>
        <div class="space-y-2">
          <span class="text-xs text-slate-500">پایان</span>
          <JalaliDateField v-model="form.endDate" placeholder="تاریخ پایان" />
          <input v-if="!form.all_day" v-model="form.endTime" type="time" :class="field" aria-label="ساعت پایان" />
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-4 text-sm">
        <label class="flex items-center gap-2"><input v-model="form.all_day" type="checkbox" /> تمام روز</label>
        <label class="flex items-center gap-2">تکرار
          <select v-model="form.repeat" class="bg-slate-100 rounded-lg px-2 py-1 text-sm">
            <option v-for="(label, k) in REPEAT_LABELS" :key="k" :value="k">{{ label }}</option>
          </select>
        </label>
        <div v-if="form.repeat" class="flex items-center gap-2"><span class="text-slate-500">تا</span>
          <div class="w-40"><JalaliDateField v-model="form.repeat_until" placeholder="بدون پایان" clearable /></div>
        </div>
      </div>
      <p v-if="event?.repeat" class="text-[11px] text-amber-700 bg-amber-50 rounded-lg px-2 py-1">تغییرات روی همه‌ی تکرارهای این برنامه اعمال می‌شود.</p>

      <div class="grid sm:grid-cols-2 gap-3">
        <label class="text-xs text-slate-500 space-y-1 block">تقویم
          <select v-model="form.calendar" :class="field">
            <option v-for="c in writable" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </label>
        <div class="text-xs text-slate-500 space-y-1">فوریت
          <div class="flex gap-1.5">
            <button v-for="(label, p) in PRIORITY_LABELS" :key="p" type="button"
                    class="flex-1 rounded-xl py-2 text-sm transition border-2"
                    :class="[PRIORITY_TONE[p], form.priority === p ? 'border-current font-semibold' : 'border-transparent opacity-70']"
                    @click="form.priority = p">{{ label }}</button>
          </div>
        </div>
      </div>

      <!-- Reminders -->
      <div class="rounded-xl bg-slate-50 p-3 space-y-2 text-sm">
        <div class="flex items-center gap-2">
          <span class="font-medium text-ink flex items-center gap-1.5"><NavIcon name="bell" :size="15" class="text-slate-500" /> یادآوری</span>
          <label class="flex items-center gap-1 text-xs text-slate-500 mr-auto"><input v-model="form.customReminders" type="checkbox" /> تنظیم دستی</label>
        </div>
        <p v-if="!form.customReminders" class="text-xs text-slate-500">
          پیش‌فرض «{{ PRIORITY_LABELS[form.priority] }}»:
          {{ defaultLeads.length ? defaultLeads.map(leadLabel).join("، ") : "بدون یادآوری" }}
          <span v-if="defaultSms && defaultLeads.length"> · با پیامک به گیرندگان پیامک</span>
        </p>
        <div v-else class="flex flex-wrap gap-1.5">
          <button v-for="m in LEAD_CHOICES" :key="m" type="button"
                  class="text-xs rounded-full px-2.5 py-1 border transition"
                  :class="form.reminders.includes(m) ? 'bg-sky-500 text-white border-transparent' : 'border-slate-200 text-slate-600 bg-surface'"
                  @click="toggleLead(m)">{{ leadLabel(m) }}</button>
        </div>
      </div>

      <!-- Attendees -->
      <div class="grid sm:grid-cols-2 gap-3">
        <div class="space-y-2">
          <span class="text-xs text-slate-500 flex items-center gap-1"><NavIcon name="users" :size="14" /> شرکت‌کنندگان از همکاران</span>
          <select v-model="memberPick" :class="field" aria-label="افزودن همکار">
            <option :value="0">انتخاب همکار…</option>
            <option v-for="p in available" :key="p.id" :value="p.id">{{ p.name }}{{ p.job_title_fa ? ` — ${p.job_title_fa}` : "" }}</option>
          </select>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="id in form.attendees" :key="id" class="flex items-center gap-1 text-xs bg-sky-50 text-sky-800 rounded-full pl-1 pr-2.5 py-1">
              {{ peopleById.get(id)?.name ?? "؟" }}
              <button type="button" class="w-4 h-4 rounded-full hover:bg-sky-200 flex items-center justify-center" :aria-label="`حذف ${peopleById.get(id)?.name}`" @click="form.attendees = form.attendees.filter((x) => x !== id)"><NavIcon name="close" :size="10" /></button>
            </span>
          </div>
          <p v-if="form.attendees.length" class="text-[11px] text-slate-400">این برنامه در تقویم شخصی همکاران انتخاب‌شده هم نمایش داده می‌شود.</p>
        </div>
        <div class="space-y-2">
          <span class="text-xs text-slate-500 flex items-center gap-1"><NavIcon name="contact" :size="14" /> مهمانان خارج از شرکت</span>
          <div class="flex gap-1.5">
            <input v-model="guest" placeholder="نام و سمت / شرکت" :class="field" @keydown.enter.prevent="addGuest" />
            <button type="button" class="bg-slate-100 hover:bg-slate-200 rounded-xl px-3 text-slate-600" aria-label="افزودن مهمان" @click="addGuest"><NavIcon name="plus" :size="16" /></button>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="g in form.guests" :key="g" class="flex items-center gap-1 text-xs bg-slate-100 text-slate-700 rounded-full pl-1 pr-2.5 py-1">
              {{ g }}
              <button type="button" class="w-4 h-4 rounded-full hover:bg-slate-200 flex items-center justify-center" :aria-label="`حذف ${g}`" @click="form.guests = form.guests.filter((x) => x !== g)"><NavIcon name="close" :size="10" /></button>
            </span>
          </div>
        </div>
      </div>

      <p v-if="mine.length" class="text-xs bg-amber-50 text-amber-800 rounded-lg px-3 py-2 flex items-start gap-1.5">
        <NavIcon name="alert" :size="14" class="shrink-0 mt-px" />
        <span>در تقویم خودتان در این زمان این‌ها را دارید: {{ mine.join("، ") }}</span>
      </p>
      <p v-if="busy.length" class="text-xs bg-amber-50 text-amber-800 rounded-lg px-3 py-2 flex items-start gap-1.5">
        <NavIcon name="alert" :size="14" class="shrink-0 mt-px" />
        <span>در این زمان مشغول‌اند: {{ busy.join("، ") }}</span>
      </p>
      <p v-if="unknown.length" class="text-[11px] text-slate-400">زمان آزاد این افراد نمایش داده نمی‌شود (خودشان نخواسته‌اند): {{ unknown.join("، ") }}</p>
      <div v-if="form.attendees.length" class="flex flex-wrap items-center gap-2 text-sm">
        <span class="text-xs text-slate-500 flex items-center gap-1"><NavIcon name="clock" :size="14" /> مهلت پاسخ به دعوت</span>
        <div class="w-56"><JalaliDateField v-model="form.respond_by" with-time placeholder="بدون مهلت" clearable /></div>
      </div>

      <div class="grid sm:grid-cols-2 gap-3">
        <input v-model="form.location" placeholder="مکان (اتاق جلسه، آدرس)" :class="field" />
        <input v-model="form.online_link" placeholder="لینک جلسه‌ی آنلاین (اختیاری)" :class="field" dir="ltr" class="text-left" />
      </div>
      <textarea v-model="form.description" rows="3" placeholder="دستور جلسه — موضوع‌ها و آنچه باید آماده شود" :class="field"></textarea>

      <div class="flex items-center gap-2">
        <button class="bg-panel text-white rounded-xl px-5 py-2 text-sm disabled:opacity-50" :disabled="saving">{{ saving ? "در حال ذخیره…" : "ذخیره" }}</button>
        <button type="button" class="text-sm text-slate-500 px-3" @click="emit('close')">انصراف</button>
        <span class="flex-1"></span>
        <span v-if="event" class="text-xs text-slate-400">ثبت‌کننده: {{ event.created_by_name }}</span>
        <button v-if="event" type="button" class="text-sm text-red-500 px-2" @click="remove">حذف</button>
      </div>
    </form>
  </div>
</template>
