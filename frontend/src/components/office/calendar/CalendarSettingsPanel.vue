<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  calendarApi, LEAD_CHOICES, leadLabel, LEVEL_LABELS, PRIORITY_LABELS,
  type CalendarRow, type CalendarSettings, type HolidayRow, type Level, type Priority, type Share,
} from "@/api/officeCalendar";
import type { Person } from "@/api/office";
import { apiError } from "@/components/crm/formError";
import { confirm, toast } from "@/composables/useUi";
import JalaliDateField from "@/components/JalaliDateField.vue";
import NavIcon from "@/components/NavIcon.vue";
import TimeField from "@/components/TimeField.vue";

/**
 * تنظیمات تقویم, in tabs:
 *  • یادآوری‌ها — who the SMS go to (the management team, picked by name),
 *    per priority how long before and whether by SMS, the day-before digest
 *    and its hour, and a test send. The executives and the office managers edit it.
 *  • مدیر دفتر — who runs the management team's calendars. An executive (or the admin) names them.
 *  • دسترسی‌ها — on each calendar the caller manages: who else reads / writes / manages it.
 *  • روزهای کاری — the office's and the factory's weekly days off, and the
 *    holidays. Everyone sees them; whoever sets the calendar changes them.
 */
const props = defineProps<{
  calendars: CalendarRow[];
  people: Person[];
  settings: CalendarSettings;
  isAdmin: boolean;
}>();
const emit = defineEmits<{ close: []; changed: [] }>();

const WEEKDAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"];
const managed = computed(() => props.calendars.filter((c) => c.level === "manage"));
const tabs = computed(() => [
  { id: "mine", label: "ترجیحات من" },
  { id: "reminders", label: "یادآوری و پیامک" },
  ...(props.settings.can_name_office ? [{ id: "office", label: "مدیر دفتر" }] : []),
  ...(managed.value.length ? [{ id: "access", label: "دسترسی‌ها" }] : []),
  { id: "holidays", label: "روزهای کاری و تعطیلات" },
]);
const tab = ref("mine");

// ---- my own: whether colleagues who invite me may see when I am busy ---------------
const prefs = reactive({ share_free_busy: false, loaded: false });
calendarApi.preferences().then((p) => Object.assign(prefs, p, { loaded: true })).catch(() => {});
async function saveShare(v: boolean) {
  try {
    Object.assign(prefs, await calendarApi.savePreferences({ share_free_busy: v }));
    toast.success(v ? "همکاران هنگام دعوت، زمان‌های مشغول شما را (بدون جزئیات) می‌بینند." : "زمان‌های مشغول شما دیگر نمایش داده نمی‌شود.");
  } catch (e) { toast.error(apiError(e)); }
}

// ---- reminders ---------------------------------------------------------------
const st = reactive(JSON.parse(JSON.stringify(props.settings)) as CalendarSettings);
const preview = ref("");
function toggleLead(p: Priority, m: number) {
  const r = st.priority_rules[p];
  r.minutes = r.minutes.includes(m) ? r.minutes.filter((x) => x !== m) : [...r.minutes, m].sort((a, b) => b - a);
}
async function saveReminders() {
  try {
    await calendarApi.saveSettings({
      digest_enabled: st.digest_enabled, digest_time: st.digest_time,
      priority_rules: st.priority_rules, sms_attendees: st.sms_attendees,
      sms_recipients: recipients.value,
    });
    toast.success("تنظیمات یادآوری ذخیره شد.");
    emit("changed");
  } catch (e) {
    toast.error(apiError(e));
  }
}
// Who the SMS go to — chosen by name, not by job title.
const recipients = ref<number[]>(props.settings.sms_recipients.map((u) => u.id));
const recipientPick = ref(0);
const known = computed(() => new Map([...props.settings.sms_recipients, ...props.settings.office_managers].map((u) => [u.id, u])));
function addRecipient() {
  if (recipientPick.value && !recipients.value.includes(recipientPick.value)) recipients.value.push(recipientPick.value);
  recipientPick.value = 0;
}
const testing = ref(0);
const testResult = ref<{ ok: boolean; detail: string } | null>(null);
async function sendTest(id: number) {
  testing.value = id;
  testResult.value = null;
  try {
    testResult.value = await calendarApi.smsTest(id);
  } catch (e) {
    testResult.value = { ok: false, detail: apiError(e) };
  } finally {
    testing.value = 0;
  }
}

async function showPreview() {
  preview.value = await calendarApi.digestPreview();
}

// ---- office managers ---------------------------------------------------------
const office = ref<number[]>(props.settings.office_managers.map((u) => u.id));
const officePick = ref(0);
async function saveOffice() {
  try {
    await calendarApi.saveSettings({ office_managers: office.value });
    toast.success("مدیر دفتر ذخیره شد.");
    emit("changed");
  } catch (e) {
    toast.error(apiError(e));
  }
}
const nameOf = (id: number) => props.people.find((p) => p.id === id)?.name ?? props.settings.office_managers.find((u) => u.id === id)?.name ?? "؟";

// ---- access ------------------------------------------------------------------
const accessCal = ref<number>(managed.value[0]?.id ?? 0);
const shares = ref<Share[]>([]);
const calName = ref("");
const calColor = ref("#0ea5e9");
const sharePick = ref(0);
async function loadAccess() {
  if (!accessCal.value) return;
  const c = await calendarApi.calendar(accessCal.value);
  shares.value = c.shares;
  calName.value = c.name;
  calColor.value = c.color;
}
function addShare() {
  if (!sharePick.value || shares.value.some((s) => s.user === sharePick.value)) return;
  shares.value.push({ user: sharePick.value, name: nameOf(sharePick.value), level: "read" });
  sharePick.value = 0;
}
async function saveAccess() {
  try {
    await calendarApi.saveCalendar(accessCal.value, {
      name: calName.value, color: calColor.value, shares: shares.value.map((s) => ({ user: s.user, level: s.level as Level })),
    });
    toast.success("دسترسی‌ها ذخیره شد.");
    emit("changed");
  } catch (e) {
    toast.error(apiError(e));
  }
}

// ---- holidays ----------------------------------------------------------------
const holidays = ref<HolidayRow[]>([]);
const week = ref<{ days_off: number[]; factory_days_off: number[]; can_edit: boolean }>({ days_off: [], factory_days_off: [], can_edit: false });
const WEEKS = [
  { field: "days_off" as const, title: "شرکت (دفتر، تقویم، فروش)" },
  { field: "factory_days_off" as const, title: "کارخانه (تولید)" },
];
const offNames = (days: number[]) => (days.length ? days.map((d) => WEEKDAYS[d]).join(" و ") : "بدون تعطیلی هفتگی");
const newHoliday = reactive({ date: "", title: "" });
async function loadHolidays() {
  [holidays.value, week.value] = await Promise.all([calendarApi.holidays(), calendarApi.workweek()]);
}
async function addHoliday() {
  if (!newHoliday.date || !newHoliday.title.trim()) return toast.error("تاریخ و عنوان تعطیلی را وارد کنید.");
  try {
    await calendarApi.addHoliday(newHoliday.date.slice(0, 10), newHoliday.title.trim());
    Object.assign(newHoliday, { date: "", title: "" });
    await loadHolidays();
    emit("changed");
  } catch (e) {
    toast.error(apiError(e));
  }
}
async function removeHoliday(h: HolidayRow) {
  if (!(await confirm({ message: `تعطیلی «${h.title}» برداشته شود؟`, danger: true, okText: "برداشتن" }))) return;
  await calendarApi.deleteHoliday(h.id);
  await loadHolidays();
  emit("changed");
}
async function toggleDayOff(d: number, which: "days_off" | "factory_days_off") {
  const field = which;
  const cur = week.value[field];
  const next = cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d];
  week.value = await calendarApi.setWorkweek({ [field]: next });
  emit("changed");
}

onMounted(() => {
  if (managed.value.length) loadAccess();
  loadHolidays();
});
const field = "bg-slate-100 rounded-xl px-3 py-2 text-sm";
</script>

<template>
  <div class="fixed inset-0 z-50 bg-black/30 flex items-start sm:items-center justify-center p-3 overflow-y-auto" @click.self="emit('close')">
    <div class="bg-surface rounded-2xl shadow-pop w-full max-w-3xl p-5 space-y-4" role="dialog" aria-label="تنظیمات تقویم">
      <div class="flex items-center gap-2">
        <h3 class="font-bold text-ink text-lg flex-1">تنظیمات تقویم</h3>
        <button class="text-slate-400 hover:text-ink" aria-label="بستن" @click="emit('close')"><NavIcon name="close" :size="18" /></button>
      </div>
      <div class="flex flex-wrap gap-1 border-b border-slate-100 pb-2">
        <button v-for="t in tabs" :key="t.id" class="text-sm rounded-lg px-3 py-1.5 transition"
                :class="tab === t.id ? 'bg-panel text-white' : 'text-slate-600 hover:bg-slate-100'" @click="tab = t.id">{{ t.label }}</button>
      </div>

      <!-- Mine -->
      <section v-if="tab === 'mine'" class="space-y-3">
        <div class="rounded-xl border border-slate-100 p-3 space-y-2">
          <label class="flex items-start gap-2 text-sm">
            <input type="checkbox" class="mt-1" :checked="prefs.share_free_busy" :disabled="!prefs.loaded" @change="saveShare(($event.target as HTMLInputElement).checked)" />
            <span>
              <b class="text-ink font-medium">نمایش زمان‌های مشغول من به همکاران هنگام دعوت به جلسه</b>
              <span class="block text-xs text-slate-500 mt-0.5 leading-5">فقط «از چه ساعتی تا چه ساعتی مشغول‌اید» دیده می‌شود — هرگز عنوان، شرکت‌کنندگان یا جزئیات برنامه‌ها. پیش‌فرض خاموش است.</span>
            </span>
          </label>
        </div>
        <div class="rounded-xl border border-slate-100 p-3 text-xs text-slate-500 leading-6 space-y-1">
          <p><b class="text-ink font-medium">حریم خصوصی تقویم:</b> تقویم شخصی شما فقط برای خودتان است؛ مدیران و ادمین هم آن را نمی‌بینند.</p>
          <p>برای سپردن مدیریت تقویمتان به کسی (مثلاً مدیر دفتر)، از تب «دسترسی‌ها» تقویم خودتان را انتخاب کنید و به او دسترسی بدهید.</p>
          <p>دعوت به یک جلسه فقط همان جلسه را به دعوت‌شده نشان می‌دهد، نه بقیه‌ی تقویم شما را.</p>
        </div>
      </section>

      <!-- Reminders -->
      <section v-else-if="tab === 'reminders'" class="space-y-4">
        <div class="text-xs rounded-lg px-3 py-2 flex items-start gap-2"
             :class="st.sms_status.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-800'">
          <NavIcon :name="st.sms_status.ok ? 'check' : 'alert'" :size="15" class="shrink-0 mt-px" />
          <span>
            <b>وضعیت سرویس پیامک:</b> {{ st.sms_status.detail }}
            <template v-if="!st.sms_status.ok"> تا رفع این مورد، یادآوری‌ها فقط داخل سامانه (زنگوله) می‌آیند.</template>
          </span>
        </div>

        <!-- Recipients -->
        <div class="rounded-xl border border-slate-100 p-3 space-y-2">
          <h4 class="text-sm font-medium text-ink">گیرندگان پیامک</h4>
          <p class="text-xs text-slate-500">برنامه‌ی فردا و یادآوری‌های پیامکی برای این افراد ارسال می‌شود (مثلاً اعضای هیئت‌مدیره). یادآوری جلسات تقویم مدیریت هم برای همه‌ی آن‌ها می‌رود و مدیر دفتر تقویم شخصی آن‌ها را مدیریت می‌کند.</p>
          <ul class="space-y-1.5">
            <li v-for="id in recipients" :key="id" class="flex items-center gap-2 bg-slate-50 rounded-xl px-3 py-2 text-sm">
              <span class="flex-1">{{ known.get(id)?.name ?? nameOf(id) }}</span>
              <span v-if="known.get(id)?.has_phone" class="text-xs text-slate-500 ltr-nums">{{ known.get(id)!.phone }}</span>
              <span v-else-if="known.get(id)" class="text-xs text-rose-600">شماره موبایل ثبت نشده</span>
              <button type="button" class="text-xs text-sky-600 hover:underline disabled:opacity-50" :disabled="testing === id || !known.get(id)"
                      :title="known.get(id) ? '' : 'ابتدا ذخیره کنید'" @click="sendTest(id)">{{ testing === id ? "در حال ارسال…" : "پیامک آزمایشی" }}</button>
              <button v-if="st.can_edit" type="button" class="text-slate-400 hover:text-red-500" :aria-label="`حذف ${nameOf(id)}`"
                      @click="recipients = recipients.filter((x) => x !== id)"><NavIcon name="close" :size="14" /></button>
            </li>
            <li v-if="!recipients.length" class="text-xs text-rose-600">هیچ گیرنده‌ای تعیین نشده؛ پیامکی ارسال نمی‌شود.</li>
          </ul>
          <p v-if="testResult" class="text-xs rounded-lg px-3 py-2" :class="testResult.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-rose-50 text-rose-700'">{{ testResult.detail }}</p>
          <div v-if="st.can_edit" class="flex gap-2">
            <select v-model="recipientPick" :class="field" class="flex-1">
              <option :value="0">افزودن همکار…</option>
              <option v-for="p in people.filter((p) => !recipients.includes(p.id))" :key="p.id" :value="p.id">{{ p.name }}{{ p.job_title_fa ? ` — ${p.job_title_fa}` : "" }}</option>
            </select>
            <button type="button" class="bg-slate-100 rounded-xl px-3 text-sm" @click="addRecipient">افزودن</button>
          </div>
          <p class="text-[11px] text-slate-400">شماره موبایل هر نفر از پروفایل کاربری او خوانده می‌شود.</p>
        </div>

        <fieldset :disabled="!st.can_edit" class="space-y-4">
          <div class="rounded-xl border border-slate-100 p-3 space-y-2">
            <label class="flex items-center gap-2 font-medium text-ink"><input v-model="st.digest_enabled" type="checkbox" /> پیامک برنامه‌ی فردا برای گیرندگان</label>
            <div class="flex flex-wrap items-center gap-3 text-sm">
              <label class="flex items-center gap-2">ساعت ارسال <TimeField v-model="st.digest_time" class="w-28" aria-label="ساعت ارسال" /></label>
              <button type="button" class="text-xs text-sky-600 hover:underline" @click="showPreview">پیش‌نمایش پیامک فردا</button>
            </div>
            <pre v-if="preview" class="text-xs bg-slate-50 rounded-lg p-2 whitespace-pre-wrap font-sans">{{ preview }}</pre>
          </div>

          <div class="space-y-2">
            <h4 class="text-sm font-medium text-ink">یادآوری پیش‌فرض بر اساس فوریت</h4>
            <div v-for="(label, p) in PRIORITY_LABELS" :key="p" class="rounded-xl border border-slate-100 p-3 space-y-2">
              <div class="flex items-center gap-2">
                <b class="text-sm">{{ label }}</b>
                <label class="flex items-center gap-1 text-xs text-slate-600 mr-auto"><input v-model="st.priority_rules[p].sms" type="checkbox" /> با پیامک</label>
              </div>
              <div class="flex flex-wrap gap-1.5">
                <button v-for="m in LEAD_CHOICES" :key="m" type="button"
                        class="text-xs rounded-full px-2.5 py-1 border transition"
                        :class="st.priority_rules[p].minutes.includes(m) ? 'bg-sky-500 text-white border-transparent' : 'border-slate-200 text-slate-600'"
                        @click="toggleLead(p, m)">{{ leadLabel(m) }}</button>
              </div>
            </div>
          </div>
          <label class="flex items-center gap-2 text-sm"><input v-model="st.sms_attendees" type="checkbox" /> پیامک یادآوری برای سایر شرکت‌کنندگان جلسه هم ارسال شود (نه فقط گیرندگان بالا)</label>
        </fieldset>
        <div class="flex items-center gap-2">
          <button v-if="st.can_edit" class="bg-panel text-white rounded-xl px-5 py-2 text-sm" @click="saveReminders">ذخیره</button>
          <p v-else class="text-xs text-slate-400">تنظیم یادآوری‌ها با مدیران ارشد و مدیر دفتر است.</p>
        </div>
      </section>

      <!-- Office managers -->
      <section v-else-if="tab === 'office'" class="space-y-3">
        <p class="text-sm text-slate-600">مدیر دفتر تقویم شخصی گیرندگان پیامک (اعضای مدیریت)، تقویم مدیریت و تقویم شرکت را کامل مدیریت می‌کند و تنظیمات یادآوری را تغییر می‌دهد.</p>
        <div class="flex flex-wrap gap-1.5">
          <span v-for="id in office" :key="id" class="flex items-center gap-1 text-sm bg-sky-50 text-sky-800 rounded-full pl-1 pr-3 py-1">
            {{ nameOf(id) }}
            <button class="w-5 h-5 rounded-full hover:bg-sky-200 flex items-center justify-center" :aria-label="`حذف ${nameOf(id)}`" @click="office = office.filter((x) => x !== id)"><NavIcon name="close" :size="11" /></button>
          </span>
          <span v-if="!office.length" class="text-xs text-slate-400">هنوز مدیر دفتری تعیین نشده.</span>
        </div>
        <div class="flex gap-2">
          <select v-model="officePick" :class="field" class="flex-1">
            <option :value="0">انتخاب همکار…</option>
            <option v-for="p in people.filter((p) => !office.includes(p.id))" :key="p.id" :value="p.id">{{ p.name }} {{ p.job_title_fa ? `— ${p.job_title_fa}` : "" }}</option>
          </select>
          <button class="bg-slate-100 rounded-xl px-3 text-sm" @click="officePick && (office.push(officePick), (officePick = 0))">+ افزودن</button>
        </div>
        <button class="bg-panel text-white rounded-xl px-5 py-2 text-sm" @click="saveOffice">ذخیره</button>
      </section>

      <!-- Access -->
      <section v-else-if="tab === 'access'" class="space-y-3">
        <div class="flex flex-wrap gap-2 items-center">
          <select v-model="accessCal" :class="field" @change="loadAccess">
            <option v-for="c in managed" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
          <input v-model="calName" :class="field" class="flex-1 min-w-[160px]" aria-label="نام تقویم" />
          <input v-model="calColor" type="color" class="w-10 h-9 rounded-lg" aria-label="رنگ تقویم" />
        </div>
        <p class="text-xs text-slate-500">دسترسی پایه از نوع تقویم می‌آید (مثلاً اعضای واحد). اینجا به افراد دیگر دسترسی بیشتر بدهید.</p>
        <ul class="space-y-1.5">
          <li v-for="s in shares" :key="s.user" class="flex items-center gap-2 bg-slate-50 rounded-xl px-3 py-2 text-sm">
            <span class="flex-1">{{ s.name }}</span>
            <select v-model="s.level" class="bg-surface rounded-lg px-2 py-1 text-xs">
              <option v-for="(label, l) in LEVEL_LABELS" :key="l" :value="l">{{ label }}</option>
            </select>
            <button class="text-xs text-red-500" @click="shares = shares.filter((x) => x.user !== s.user)">حذف</button>
          </li>
          <li v-if="!shares.length" class="text-xs text-slate-400">دسترسی اضافه‌ای ثبت نشده.</li>
        </ul>
        <div class="flex gap-2">
          <select v-model="sharePick" :class="field" class="flex-1">
            <option :value="0">افزودن همکار…</option>
            <option v-for="p in people.filter((p) => !shares.some((s) => s.user === p.id))" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
          <button class="bg-slate-100 rounded-xl px-3 text-sm" @click="addShare">+ افزودن</button>
        </div>
        <button class="bg-panel text-white rounded-xl px-5 py-2 text-sm" @click="saveAccess">ذخیره</button>
      </section>

      <!-- Holidays -->
      <section v-else-if="tab === 'holidays'" class="space-y-3">
        <div v-for="w in WEEKS" :key="w.field" class="rounded-xl border border-slate-100 p-3 space-y-2">
          <div class="flex flex-wrap items-center gap-2">
            <b class="text-sm text-ink">{{ w.title }}</b>
            <span class="text-xs text-slate-500">تعطیل هفتگی: {{ offNames(week[w.field]) }}</span>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <label v-for="(d, i) in WEEKDAYS" :key="d" class="flex items-center gap-1 text-xs rounded-full px-2.5 py-1"
                   :class="[week[w.field].includes(i) ? 'bg-rose-50 text-rose-700' : 'bg-slate-100 text-slate-600', week.can_edit ? 'cursor-pointer' : '']">
              <input type="checkbox" :checked="week[w.field].includes(i)" :disabled="!week.can_edit" @change="toggleDayOff(i, w.field)" />{{ d }}
            </label>
          </div>
        </div>
        <p v-if="!week.can_edit" class="text-xs text-slate-400">تعیین روزهای تعطیل با ادمین، مدیران ارشد و مدیر دفتر است.</p>
        <h4 class="text-sm font-medium text-ink pt-1">تعطیلات رسمی و مناسبت‌ها (برای شرکت و کارخانه)</h4>
        <form v-if="week.can_edit" class="flex flex-wrap gap-2 items-end" @submit.prevent="addHoliday">
          <div class="w-44"><JalaliDateField v-model="newHoliday.date" placeholder="تاریخ" /></div>
          <input v-model="newHoliday.title" placeholder="عنوان تعطیلی، مثلاً «عید فطر»" :class="field" class="flex-1 min-w-[180px]" />
          <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm">+ افزودن تعطیلی</button>
        </form>
        <ul class="grid sm:grid-cols-2 gap-1.5 text-sm max-h-72 overflow-y-auto">
          <li v-for="h in holidays" :key="h.id" class="flex items-center justify-between bg-rose-50 rounded-lg px-3 py-1.5">
            <span><b class="ltr-nums">{{ h.jalali }}</b> · {{ h.title }}</span>
            <button v-if="week.can_edit" class="text-xs text-red-500" @click="removeHoliday(h)">حذف</button>
          </li>
          <li v-if="!holidays.length" class="text-xs text-slate-400">هنوز تعطیلی‌ای ثبت نشده.</li>
        </ul>
      </section>
    </div>
  </div>
</template>
