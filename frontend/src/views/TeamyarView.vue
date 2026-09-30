<script setup lang="ts">
/**
 * استقرار تیمیار — the one page management opens to know where the rollout
 * stands: plan (گانت), dates (تقویم), meetings and how useful they were, and
 * the diary of every call, message, issue and decision along the way.
 */
import { computed, onMounted, ref } from "vue";
import {
  LOG_KINDS, localDay, teamyarApi,
  type LogEntry, type LogKind, type Meeting, type Overview, type Phase, type TeamyarTask,
} from "@/api/teamyar";
import { apiError } from "@/components/crm/formError";
import Skeleton from "@/components/Skeleton.vue";
import GanttChart from "@/components/teamyar/GanttChart.vue";
import TeamyarCalendar from "@/components/teamyar/TeamyarCalendar.vue";
import TaskForm from "@/components/teamyar/TaskForm.vue";
import MeetingForm from "@/components/teamyar/MeetingForm.vue";
import LogForm from "@/components/teamyar/LogForm.vue";
import { MONTH_NAMES, faDigits, isoToJalali, jalaliLabel } from "@/utils/jalali";

const TABS = [
  { key: "overview", label: "نمای کلی" },
  { key: "gantt", label: "گانت چارت" },
  { key: "calendar", label: "تقویم و ددلاین‌ها" },
  { key: "meetings", label: "جلسات" },
  { key: "timeline", label: "رویدادها و مکالمات" },
] as const;
type Tab = (typeof TABS)[number]["key"];

function initialTab(): Tab {
  try {
    const t = localStorage.getItem("teamyar.tab");
    if (t && TABS.some((x) => x.key === t)) return t as Tab;
  } catch { /* storage blocked */ }
  return "overview";
}
const tab = ref<Tab>(initialTab());
function setTab(t: Tab) {
  tab.value = t;
  try { localStorage.setItem("teamyar.tab", t); } catch { /* ignore */ }
}

const loading = ref(true);
const error = ref("");
const overview = ref<Overview | null>(null);
const phases = ref<Phase[]>([]);
const tasks = ref<TeamyarTask[]>([]);
const meetings = ref<Meeting[]>([]);
const logs = ref<LogEntry[]>([]);

async function load() {
  error.value = "";
  try {
    const [o, p, t, m, l] = await Promise.all([
      teamyarApi.overview(), teamyarApi.phases.list(), teamyarApi.tasks.list(),
      teamyarApi.meetings.list(), teamyarApi.logs.list(),
    ]);
    overview.value = o; phases.value = p; tasks.value = t; meetings.value = m; logs.value = l;
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

// -- forms -------------------------------------------------------------
const editingTask = ref<TeamyarTask | null | undefined>(undefined);
const editingMeeting = ref<Meeting | null | undefined>(undefined);
const editingLog = ref<LogEntry | null | undefined>(undefined);
function saved() {
  editingTask.value = editingMeeting.value = editingLog.value = undefined;
  load();
}

// -- phases, made where they are needed --------------------------------
const PHASE_COLORS = ["#6366f1", "#0ea5e9", "#f59e0b", "#10b981", "#ec4899", "#8b5cf6", "#14b8a6"];
const newPhase = ref("");
async function addPhase() {
  const title = newPhase.value.trim();
  if (!title) return;
  await teamyarApi.phases.create({
    title, order: phases.value.length, color: PHASE_COLORS[phases.value.length % PHASE_COLORS.length],
  });
  newPhase.value = "";
  load();
}
async function renamePhase(p: Phase) {
  const title = prompt("نام فاز", p.title);
  if (title === null || !title.trim() || title.trim() === p.title) return;
  await teamyarApi.phases.update(p.id, { title: title.trim() });
  load();
}
async function deletePhase(p: Phase) {
  const n = tasks.value.filter((t) => t.phase === p.id).length;
  const note = n ? `
${faDigits(n)} فعالیتِ این فاز حذف نمی‌شوند و «بدون فاز» می‌مانند.` : "";
  if (!confirm(`فاز «${p.title}» حذف شود؟${note}`)) return;
  try {
    await teamyarApi.phases.remove(p.id);
  } catch (e) {
    alert(apiError(e));
  }
  load();
}

// -- overview helpers --------------------------------------------------
const fa = (n: number | null | undefined) => faDigits(n ?? 0);
const gap = computed(() =>
  overview.value ? Math.round(overview.value.progress - overview.value.planned_progress) : 0,
);
const recent = computed(() => logs.value.slice(0, 8));

function dayWord(t: TeamyarTask) {
  if (t.days_left === 0) return "امروز";
  if (t.days_left < 0) return `${fa(-t.days_left)} روز تاخیر`;
  return `${fa(t.days_left)} روز مانده`;
}

function when(iso: string) {
  const d = new Date(iso);
  return `${jalaliLabel(localDay(iso))} · ${faDigits(d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }))}`;
}


// -- meetings ----------------------------------------------------------
const meetingFilter = ref<"all" | "held" | "planned" | "cancelled">("all");
const shownMeetings = computed(() =>
  meetingFilter.value === "all" ? meetings.value : meetings.value.filter((m) => m.status === meetingFilter.value),
);
/** Held meetings per Jalali month — bucketed here, where the calendar lives. */
const byMonth = computed(() => {
  const map = new Map<string, { label: string; count: number; sum: number; rated: number }>();
  for (const m of meetings.value) {
    if (m.status !== "held") continue;
    const j = isoToJalali(localDay(m.held_at))!;
    const key = `${j.jy}-${String(j.jm).padStart(2, "0")}`;
    const b = map.get(key) ?? { label: MONTH_NAMES[j.jm - 1], count: 0, sum: 0, rated: 0 };
    b.count++;
    if (m.rating) { b.sum += m.rating; b.rated++; }
    map.set(key, b);
  }
  return [...map.entries()].sort(([a], [b]) => a.localeCompare(b)).slice(-8).map(([key, b]) => ({
    key, label: b.label, count: b.count,
    avg: b.rated ? Math.round((b.sum / b.rated) * 10) / 10 : null,
  }));
});
const maxMonthCount = computed(() => Math.max(1, ...byMonth.value.map((b) => b.count)));

// -- timeline ----------------------------------------------------------
const logKind = ref<"" | LogKind | "meeting">("");
const q = ref("");
interface Entry { key: string; at: string; kind: string; label: string; title: string; who: string; body: string; author: string; open: () => void; resolved?: boolean; isIssue?: boolean }
const timeline = computed(() => {
  const items: Entry[] = [];
  if (!logKind.value || logKind.value !== "meeting") {
    for (const l of logs.value) {
      if (logKind.value && l.kind !== logKind.value) continue;
      items.push({
        key: `l${l.id}`, at: l.happened_at, kind: l.kind, label: l.kind_label, title: l.subject,
        who: l.counterpart, body: l.body, author: l.author_name,
        resolved: l.resolved, isIssue: l.kind === "issue",
        open: () => { if (l.kind !== "system") editingLog.value = l; },
      });
    }
  }
  if (!logKind.value || logKind.value === "meeting") {
    for (const m of meetings.value) {
      items.push({
        key: `m${m.id}`, at: m.held_at, kind: "meeting", label: `جلسه · ${m.status_label}`,
        title: m.title, who: m.attendees, body: [m.summary, m.decisions && `مصوبات:\n${m.decisions}`].filter(Boolean).join("\n\n"),
        author: "", open: () => { editingMeeting.value = m; },
      });
    }
  }
  const term = q.value.trim();
  const filtered = term
    ? items.filter((i) => `${i.title} ${i.who} ${i.body}`.includes(term))
    : items;
  filtered.sort((a, b) => b.at.localeCompare(a.at));
  const groups: { day: string; items: Entry[] }[] = [];
  for (const i of filtered) {
    const d = localDay(i.at);
    const g = groups[groups.length - 1];
    if (g && g.day === d) g.items.push(i);
    else groups.push({ day: d, items: [i] });
  }
  return groups;
});

const KIND_DOT: Record<string, string> = {
  call: "bg-sky-500", message: "bg-cyan-500", email: "bg-indigo-500", visit: "bg-teal-500",
  issue: "bg-red-500", decision: "bg-amber-500", note: "bg-slate-400", system: "bg-slate-300",
  meeting: "bg-violet-500",
};

const STATUS_CHIP: Record<string, string> = {
  todo: "bg-slate-100 text-slate-500",
  doing: "bg-blue-500/15 text-blue-600",
  blocked: "bg-red-500/15 text-red-600",
  done: "bg-emerald-500/15 text-emerald-600",
};

const STATUS_BAR: Record<string, string> = {
  todo: "bg-slate-400", doing: "bg-blue-500", blocked: "bg-red-500", done: "bg-emerald-500",
};

// -- «فعالیت‌ها» box: every task, in plan order, filterable by status --
const taskFilter = ref<"" | TeamyarTask["status"]>("");
const TASK_FILTERS = [
  { key: "", label: "همه" },
  { key: "todo", label: "شروع نشده" },
  { key: "doing", label: "در حال انجام" },
  { key: "blocked", label: "متوقف" },
  { key: "done", label: "انجام شده" },
] as const;
const phaseOrder = computed(() => new Map(phases.value.map((p) => [p.id, p.order])));
const allTasks = computed(() =>
  tasks.value
    .filter((t) => !taskFilter.value || t.status === taskFilter.value)
    .sort((a, b) =>
      (phaseOrder.value.get(a.phase ?? -1) ?? 999) - (phaseOrder.value.get(b.phase ?? -1) ?? 999)
      || a.start_on.localeCompare(b.start_on)
      || a.id - b.id),
);
function countOf(key: string) {
  return key ? tasks.value.filter((t) => t.status === key).length : tasks.value.length;
}
</script>

<template>
  <div class="space-y-4">
    <!-- Header -->
    <div class="bg-surface rounded-card shadow-soft p-4 sm:p-5">
      <div class="flex flex-wrap items-start gap-3">
        <div class="min-w-0 flex-1">
          <h2 class="text-lg font-bold text-ink">استقرار تیمیار</h2>
          <p class="text-sm text-slate-500 mt-1">برنامه، ددلاین‌ها، جلسات و تمام رویدادهای پروژه — از صفر تا صد</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-ink hover:bg-slate-200" @click="editingLog = null">+ رویداد / مکالمه</button>
          <button class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-ink hover:bg-slate-200" @click="editingMeeting = null">+ جلسه</button>
          <button class="rounded-xl px-4 py-2 text-sm bg-panel text-white" @click="editingTask = null">+ فعالیت</button>
        </div>
      </div>

      <div v-if="overview" class="mt-4">
        <div class="flex items-baseline justify-between text-xs mb-1">
          <span class="text-slate-500">پیشرفت کل (وزن‌دهی بر اساس مدت)</span>
          <span class="text-ink">
            واقعی {{ fa(overview.progress) }}٪ · طبق برنامه {{ fa(overview.planned_progress) }}٪
            <span :class="gap < 0 ? 'text-red-500' : 'text-emerald-600'" class="font-bold">
              ({{ gap < 0 ? "عقب" : "جلو" }} {{ fa(Math.abs(gap)) }}٪)
            </span>
          </span>
        </div>
        <div class="relative h-3 bg-slate-100 rounded-full overflow-hidden">
          <div class="h-full rounded-full bg-emerald-500 transition-all" :style="{ width: `${overview.progress}%` }"></div>
          <div class="absolute top-0 bottom-0 w-0.5 bg-ink/60" :style="{ right: `${overview.planned_progress}%` }" title="جایی که طبق برنامه باید باشیم"></div>
        </div>
      </div>

      <nav class="flex gap-1 mt-4 overflow-x-auto -mx-1 px-1">
        <button
          v-for="t in TABS" :key="t.key"
          class="px-3 py-1.5 text-sm rounded-xl whitespace-nowrap"
          :class="tab === t.key ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
          @click="setTab(t.key)"
        >{{ t.label }}</button>
      </nav>
    </div>

    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-28 rounded-card" />
      <Skeleton class="h-64 rounded-card" />
    </div>
    <p v-else-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3">{{ error }}</p>

    <template v-else-if="overview">
      <!-- ============ OVERVIEW ============ -->
      <template v-if="tab === 'overview'">
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-500">فعالیت‌ها</p>
            <p class="text-2xl font-bold text-ink mt-1">{{ fa(overview.task_count) }}</p>
            <p class="text-[11px] text-slate-400 mt-1">
              {{ fa(overview.by_status.done) }} انجام · {{ fa(overview.by_status.doing) }} در جریان ·
              {{ fa(overview.by_status.blocked) }} متوقف
            </p>
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-500">ددلاین عقب‌افتاده</p>
            <p class="text-2xl font-bold mt-1" :class="overview.overdue.length ? 'text-red-500' : 'text-emerald-600'">
              {{ fa(overview.overdue.length) }}
            </p>
            <p class="text-[11px] text-slate-400 mt-1">{{ fa(overview.upcoming.length) }} ددلاین در ۱۴ روز آینده</p>
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-500">جلسات برگزار شده</p>
            <p class="text-2xl font-bold text-ink mt-1">{{ fa(overview.meetings.held) }}</p>
            <p class="text-[11px] text-slate-400 mt-1">
              اثربخشی {{ fa(overview.meetings.avg_rating) }} از ۵ · {{ fa(overview.meetings.planned) }} در برنامه
            </p>
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-500">مشکلات باز</p>
            <p class="text-2xl font-bold mt-1" :class="overview.open_issues ? 'text-amber-500' : 'text-emerald-600'">
              {{ fa(overview.open_issues) }}
            </p>
            <p class="text-[11px] text-slate-400 mt-1">{{ fa(overview.log_count) }} رویداد ثبت شده</p>
          </div>
        </div>

        <div class="grid md:grid-cols-2 xl:grid-cols-4 gap-4">
          <section class="bg-surface rounded-card shadow-soft p-4 flex flex-col">
            <div class="flex items-center gap-2 mb-2">
              <h3 class="font-bold text-ink text-sm flex-1">📋 فعالیت‌ها</h3>
              <button class="text-xs text-slate-500 hover:text-ink" @click="editingTask = null">+ فعالیت</button>
            </div>
            <div class="flex flex-wrap gap-1 mb-2">
              <button
                v-for="f in TASK_FILTERS" :key="f.key"
                class="text-[11px] rounded-full px-2 py-0.5"
                :class="taskFilter === f.key ? 'bg-panel text-white' : 'bg-slate-100 text-slate-500 hover:text-ink'"
                @click="taskFilter = f.key"
              >{{ f.label }} {{ fa(countOf(f.key)) }}</button>
            </div>
            <p v-if="!allTasks.length" class="text-sm text-slate-400">
              {{ tasks.length ? "فعالیتی با این وضعیت نیست." : "هنوز فعالیتی تعریف نشده." }}
            </p>
            <div class="max-h-[420px] overflow-y-auto -mx-1 px-1">
              <button
                v-for="t in allTasks" :key="t.id"
                class="w-full text-right py-2 border-b border-slate-50 last:border-0"
                @click="editingTask = t"
              >
                <div class="flex items-center gap-2">
                  <span class="flex-1 text-sm text-ink truncate" :class="t.status === 'done' ? 'line-through text-slate-400' : ''">
                    {{ t.is_milestone ? "◆ " : "" }}{{ t.title }}
                  </span>
                  <span class="text-[10px] rounded px-1.5 shrink-0" :class="STATUS_CHIP[t.status]">{{ t.status_label }}</span>
                </div>
                <div class="flex items-center gap-2 mt-1">
                  <div class="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div class="h-full" :class="STATUS_BAR[t.status]" :style="{ width: `${t.progress}%` }"></div>
                  </div>
                  <span class="text-[11px] text-slate-400">{{ fa(t.progress) }}٪</span>
                </div>
                <p class="text-[11px] text-slate-400 mt-0.5 truncate">
                  <span v-if="t.phase_title">{{ t.phase_title }} · </span>
                  {{ jalaliLabel(t.start_on) }} تا {{ jalaliLabel(t.end_on) }}
                  <span v-if="t.is_overdue" class="text-red-500"> · عقب</span>
                </p>
              </button>
            </div>
            <button class="text-xs text-slate-500 hover:text-ink mt-2 self-start" @click="setTab('gantt')">نمای گانت ←</button>
          </section>

          <section class="bg-surface rounded-card shadow-soft p-4">
            <h3 class="font-bold text-ink text-sm mb-2">🔄 در حال انجام</h3>
            <p v-if="!overview.in_progress.length" class="text-sm text-slate-400">کاری در جریان نیست.</p>
            <button
              v-for="t in overview.in_progress" :key="t.id"
              class="w-full text-right py-2 border-b border-slate-50 last:border-0"
              @click="editingTask = tasks.find((x) => x.id === t.id)"
            >
              <div class="flex items-center gap-2">
                <span class="flex-1 text-sm text-ink truncate">{{ t.title }}</span>
                <span class="text-[10px] rounded px-1.5" :class="STATUS_CHIP[t.status]">{{ t.status_label }}</span>
              </div>
              <div class="flex items-center gap-2 mt-1">
                <div class="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div class="h-full bg-blue-500" :style="{ width: `${t.progress}%` }"></div>
                </div>
                <span class="text-[11px] text-slate-400">{{ fa(t.progress) }}٪</span>
              </div>
              <p class="text-[11px] text-slate-400 mt-0.5">{{ t.owner || "بدون مسئول" }} · {{ dayWord(t) }}</p>
            </button>
          </section>

          <section class="bg-surface rounded-card shadow-soft p-4">
            <h3 class="font-bold text-ink text-sm mb-2">⏰ ددلاین‌ها</h3>
            <p v-if="!overview.overdue.length && !overview.upcoming.length" class="text-sm text-slate-400">
              ددلاین نزدیکی نیست.
            </p>
            <button
              v-for="t in [...overview.overdue, ...overview.upcoming]" :key="t.id"
              class="w-full text-right flex items-center gap-2 py-2 border-b border-slate-50 last:border-0"
              @click="editingTask = tasks.find((x) => x.id === t.id)"
            >
              <i class="w-2 h-2 rounded-full shrink-0" :class="t.is_overdue ? 'bg-red-500' : t.days_left <= 3 ? 'bg-amber-500' : 'bg-sky-500'"></i>
              <span class="flex-1 min-w-0">
                <span class="block text-sm text-ink truncate">{{ t.is_milestone ? "◆ " : "" }}{{ t.title }}</span>
                <span class="block text-[11px] text-slate-400">{{ jalaliLabel(t.end_on) }}</span>
              </span>
              <span class="text-[11px] shrink-0" :class="t.is_overdue ? 'text-red-500' : 'text-slate-500'">{{ dayWord(t) }}</span>
            </button>
          </section>

          <section class="bg-surface rounded-card shadow-soft p-4">
            <h3 class="font-bold text-ink text-sm mb-2">📅 جلسه‌ی بعدی</h3>
            <button
              v-if="overview.meetings.next"
              class="w-full text-right rounded-xl bg-violet-500/10 p-3"
              @click="editingMeeting = meetings.find((m) => m.id === overview!.meetings.next!.id)"
            >
              <p class="text-sm font-bold text-ink">{{ overview.meetings.next.title }}</p>
              <p class="text-[11px] text-violet-600 mt-1">{{ when(overview.meetings.next.held_at) }}</p>
              <p v-if="overview.meetings.next.agenda" class="text-xs text-slate-500 mt-1 line-clamp-3 whitespace-pre-line">
                {{ overview.meetings.next.agenda }}
              </p>
            </button>
            <p v-else class="text-sm text-slate-400">جلسه‌ای برنامه‌ریزی نشده.</p>

            <h3 class="font-bold text-ink text-sm mt-4 mb-2">🕘 آخرین رویدادها</h3>
            <p v-if="!recent.length" class="text-sm text-slate-400">هنوز چیزی ثبت نشده.</p>
            <div v-for="l in recent" :key="l.id" class="flex gap-2 py-1.5 text-sm">
              <i class="w-2 h-2 rounded-full mt-1.5 shrink-0" :class="KIND_DOT[l.kind]"></i>
              <div class="min-w-0">
                <p class="text-ink truncate">{{ l.subject }}</p>
                <p class="text-[11px] text-slate-400">{{ l.kind_label }} · {{ when(l.happened_at) }}</p>
              </div>
            </div>
            <button class="text-xs text-slate-500 hover:text-ink mt-1" @click="setTab('timeline')">همه‌ی رویدادها ←</button>
          </section>
        </div>
      </template>

      <!-- ============ GANTT ============ -->
      <template v-else-if="tab === 'gantt'">
        <div class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-center gap-2">
          <span class="text-sm text-slate-500">فازها:</span>
          <span
            v-for="p in phases" :key="p.id"
            class="inline-flex items-center text-xs rounded-full text-white overflow-hidden"
            :style="{ background: p.color || '#6366f1' }"
          >
            <button class="pr-3 pl-1.5 py-1 hover:bg-black/10" title="تغییر نام" @click="renamePhase(p)">{{ p.title }}</button>
            <button
              class="px-2 py-1 border-r border-white/30 hover:bg-black/20 leading-none"
              :title="`حذف فاز «${p.title}»`" :aria-label="`حذف فاز ${p.title}`"
              @click="deletePhase(p)"
            >×</button>
          </span>
          <input
            v-model="newPhase"
            class="bg-slate-100 rounded-xl px-3 py-1.5 text-sm text-ink outline-none w-40"
            placeholder="فاز جدید…" @keydown.enter="addPhase"
          />
          <button class="text-sm text-slate-500 hover:text-ink" @click="addPhase">افزودن</button>
        </div>
        <GanttChart :tasks="tasks" :phases="phases" @open="(t) => (editingTask = t)" />
      </template>

      <!-- ============ CALENDAR ============ -->
      <TeamyarCalendar
        v-else-if="tab === 'calendar'"
        :tasks="tasks" :meetings="meetings" :logs="logs"
        @open-task="(t) => (editingTask = t)"
        @open-meeting="(m) => (editingMeeting = m)"
      />

      <!-- ============ MEETINGS ============ -->
      <template v-else-if="tab === 'meetings'">
        <div class="grid lg:grid-cols-[1fr_1.2fr] gap-4">
          <section class="bg-surface rounded-card shadow-soft p-4">
            <h3 class="font-bold text-ink text-sm mb-3">عملکرد جلسات</h3>
            <div class="grid grid-cols-3 gap-2 text-center">
              <div class="rounded-xl bg-slate-50 p-2">
                <p class="text-xl font-bold text-ink">{{ fa(overview.meetings.held) }}</p>
                <p class="text-[11px] text-slate-500">برگزار شده</p>
              </div>
              <div class="rounded-xl bg-slate-50 p-2">
                <p class="text-xl font-bold text-amber-500">{{ fa(overview.meetings.avg_rating) }}<span class="text-xs text-slate-400">/۵</span></p>
                <p class="text-[11px] text-slate-500">میانگین اثربخشی</p>
              </div>
              <div class="rounded-xl bg-slate-50 p-2">
                <p class="text-xl font-bold text-ink">{{ fa(Math.round(overview.meetings.total_minutes / 60 * 10) / 10) }}</p>
                <p class="text-[11px] text-slate-500">ساعت جلسه</p>
              </div>
              <div class="rounded-xl bg-slate-50 p-2">
                <p class="text-xl font-bold text-emerald-600">
                  {{ fa(overview.meetings.held ? Math.round(overview.meetings.with_decisions / overview.meetings.held * 100) : 0) }}٪
                </p>
                <p class="text-[11px] text-slate-500">با مصوبه</p>
              </div>
              <div class="rounded-xl bg-slate-50 p-2">
                <p class="text-xl font-bold text-violet-600">{{ fa(overview.meetings.planned) }}</p>
                <p class="text-[11px] text-slate-500">در برنامه</p>
              </div>
              <div class="rounded-xl bg-slate-50 p-2">
                <p class="text-xl font-bold text-red-500">{{ fa(overview.meetings.cancelled) }}</p>
                <p class="text-[11px] text-slate-500">لغو شده</p>
              </div>
            </div>

            <h4 class="text-xs text-slate-500 mt-5 mb-2">تعداد جلسات و اثربخشی به تفکیک ماه</h4>
            <p v-if="!byMonth.length" class="text-sm text-slate-400">هنوز جلسه‌ای برگزار نشده.</p>
            <div v-else class="flex items-end gap-3 h-36 border-b border-slate-100 pb-1">
              <div v-for="b in byMonth" :key="b.key" class="flex-1 flex flex-col items-center justify-end h-full gap-1">
                <span class="text-[10px] text-amber-500">{{ b.avg ? `★${fa(b.avg)}` : "" }}</span>
                <span class="text-[11px] text-ink">{{ fa(b.count) }}</span>
                <div class="w-full max-w-[36px] rounded-t-md bg-violet-500" :style="{ height: `${(b.count / maxMonthCount) * 70}%` }"></div>
                <span class="text-[10px] text-slate-400">{{ b.label }}</span>
              </div>
            </div>
          </section>

          <section class="bg-surface rounded-card shadow-soft p-4">
            <div class="flex items-center gap-2 mb-3">
              <h3 class="font-bold text-ink text-sm flex-1">فهرست جلسات</h3>
              <select v-model="meetingFilter" class="bg-slate-100 rounded-lg px-2 py-1 text-xs text-ink outline-none">
                <option value="all">همه</option>
                <option value="held">برگزار شده</option>
                <option value="planned">در برنامه</option>
                <option value="cancelled">لغو شده</option>
              </select>
            </div>
            <p v-if="!shownMeetings.length" class="text-sm text-slate-400">جلسه‌ای نیست.</p>
            <div class="space-y-2 max-h-[560px] overflow-y-auto">
              <button
                v-for="m in shownMeetings" :key="m.id"
                class="w-full text-right rounded-xl border border-slate-100 p-3 hover:bg-slate-50"
                @click="editingMeeting = m"
              >
                <div class="flex items-center gap-2">
                  <span class="flex-1 text-sm font-bold text-ink truncate">{{ m.title }}</span>
                  <span v-if="m.rating" class="text-xs text-amber-400" dir="ltr">{{ "★".repeat(m.rating) }}</span>
                  <span
                    class="text-[10px] rounded px-1.5"
                    :class="{ held: 'bg-emerald-500/15 text-emerald-600', planned: 'bg-violet-500/15 text-violet-600', cancelled: 'bg-red-500/15 text-red-500' }[m.status]"
                  >{{ m.status_label }}</span>
                </div>
                <p class="text-[11px] text-slate-400 mt-1">
                  {{ when(m.held_at) }} · {{ m.kind_label }} · {{ fa(m.duration_min) }} دقیقه
                </p>
                <p v-if="m.attendees" class="text-[11px] text-slate-500 mt-1 truncate">👥 {{ m.attendees }}</p>
                <p v-if="m.decisions" class="text-xs text-ink mt-2 whitespace-pre-line line-clamp-4 bg-emerald-500/5 rounded-lg p-2">
                  ✅ {{ m.decisions }}
                </p>
              </button>
            </div>
          </section>
        </div>
      </template>

      <!-- ============ TIMELINE ============ -->
      <template v-else-if="tab === 'timeline'">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <div class="flex flex-wrap items-center gap-2 mb-4">
            <input
              v-model="q"
              class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none flex-1 min-w-[180px]"
              placeholder="جستجو در موضوع، شرح، اشخاص…"
            />
            <select v-model="logKind" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
              <option value="">همه‌ی رویدادها</option>
              <option value="meeting">جلسات</option>
              <option v-for="(label, k) in LOG_KINDS" :key="k" :value="k">{{ label }}</option>
              <option value="system">تغییر وضعیت‌ها</option>
            </select>
          </div>

          <p v-if="!timeline.length" class="text-sm text-slate-400 text-center py-8">رویدادی پیدا نشد.</p>
          <div v-for="g in timeline" :key="g.day" class="mb-4">
            <h4 class="text-xs font-bold text-slate-500 mb-2 sticky top-0 bg-surface py-1">{{ jalaliLabel(g.day) }}</h4>
            <div class="border-r-2 border-slate-100 pr-4 space-y-3">
              <button
                v-for="i in g.items" :key="i.key"
                class="relative w-full text-right block"
                :class="i.kind === 'system' ? 'cursor-default' : ''"
                @click="i.open()"
              >
                <i class="absolute -right-[23px] top-1.5 w-3 h-3 rounded-full ring-4 ring-surface" :class="KIND_DOT[i.kind]"></i>
                <div class="flex flex-wrap items-center gap-2">
                  <span class="text-[11px] text-slate-400 ltr-nums">
                    {{ faDigits(new Date(i.at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })) }}
                  </span>
                  <span class="text-[10px] bg-slate-100 text-slate-500 rounded px-1.5">{{ i.label }}</span>
                  <span class="text-sm text-ink" :class="i.kind === 'system' ? 'text-slate-500' : 'font-medium'">{{ i.title }}</span>
                  <span v-if="i.isIssue" class="text-[10px] rounded px-1.5" :class="i.resolved ? 'bg-emerald-500/15 text-emerald-600' : 'bg-red-500/15 text-red-500'">
                    {{ i.resolved ? "برطرف شد" : "باز" }}
                  </span>
                </div>
                <p v-if="i.who" class="text-[11px] text-slate-500 mt-0.5">{{ i.kind === "meeting" ? "👥" : "با" }} {{ i.who }}</p>
                <p v-if="i.body" class="text-xs text-slate-600 mt-1 whitespace-pre-line">{{ i.body }}</p>
                <p v-if="i.author" class="text-[10px] text-slate-400 mt-0.5">ثبت: {{ i.author }}</p>
              </button>
            </div>
          </div>
        </div>
      </template>
    </template>

    <TaskForm
      v-if="editingTask !== undefined"
      :task="editingTask" :phases="phases" :tasks="tasks"
      @close="editingTask = undefined" @saved="saved"
    />
    <MeetingForm
      v-if="editingMeeting !== undefined"
      :meeting="editingMeeting" :tasks="tasks"
      @close="editingMeeting = undefined" @saved="saved"
    />
    <LogForm
      v-if="editingLog !== undefined"
      :entry="editingLog" :tasks="tasks"
      @close="editingLog = undefined" @saved="saved"
    />
  </div>
</template>
