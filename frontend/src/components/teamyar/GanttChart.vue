<script setup lang="ts">
/**
 * گانت چارت تیمیار — drawn in HTML rather than ECharts.
 *
 * A Gantt is rows of text beside rows of bars; ECharts would draw the bars
 * well and the Persian labels badly, and RTL time (earlier on the right) is
 * one `right:` in CSS against a mirrored axis in a chart library.
 *
 * Every date is a day index from `origin` (UTC midnight), so a bar's position
 * is plain arithmetic and nothing depends on the viewer's timezone.
 */
import { computed, nextTick, onMounted, ref, watch } from "vue";
import type { Phase, TeamyarTask } from "@/api/teamyar";
import { MONTH_NAMES, faDigits, jalaliLabel, toJalali, todayIso } from "@/utils/jalali";

const props = defineProps<{ tasks: TeamyarTask[]; phases: Phase[] }>();
const emit = defineEmits<{ (e: "open", task: TeamyarTask): void }>();

const DAY = 86_400_000;
const toDay = (iso: string) => {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return Math.round(Date.UTC(y, m - 1, d) / DAY);
};

const ZOOMS = [
  { key: "week", label: "هفتگی", px: 28 },
  { key: "month", label: "ماهانه", px: 10 },
  { key: "quarter", label: "فصلی", px: 4 },
] as const;
const zoom = ref<(typeof ZOOMS)[number]["key"]>("month");
const dayPx = computed(() => ZOOMS.find((z) => z.key === zoom.value)!.px);

const today = toDay(todayIso());

/** The visible span: every bar, today, and a little air on both ends. */
const range = computed(() => {
  let lo = today - 14;
  let hi = today + 30;
  for (const t of props.tasks) {
    lo = Math.min(lo, toDay(t.start_on) - 7);
    hi = Math.max(hi, toDay(t.end_on) + 14);
  }
  return { lo, hi, days: hi - lo + 1 };
});

const width = computed(() => range.value.days * dayPx.value);
const pos = (day: number) => (day - range.value.lo) * dayPx.value;

/** Jalali months across the span, each with its pixel extent. */
const months = computed(() => {
  const out: { key: string; label: string; start: number; days: number }[] = [];
  for (let d = range.value.lo; d <= range.value.hi; d++) {
    const j = toJalali(new Date(d * DAY));
    const key = `${j.jy}-${j.jm}`;
    const last = out[out.length - 1];
    if (last && last.key === key) last.days++;
    else out.push({ key, label: `${MONTH_NAMES[j.jm - 1]} ${faDigits(j.jy % 100)}`, start: d, days: 1 });
  }
  return out;
});

/** Week ticks (Saturdays) for the weekly zoom, month starts otherwise. */
const ticks = computed(() => {
  if (zoom.value !== "week") return months.value.map((m) => ({ day: m.start, label: "" }));
  const out: { day: number; label: string }[] = [];
  for (let d = range.value.lo; d <= range.value.hi; d++) {
    // 1970-01-01 was a Thursday; Saturday is (d + 5) % 7 === 0 … d % 7 === 2.
    if (((d % 7) + 7) % 7 === 2) out.push({ day: d, label: faDigits(toJalali(new Date(d * DAY)).jd) });
  }
  return out;
});

interface Row {
  kind: "phase" | "task";
  key: string;
  title: string;
  color: string;
  start: number;
  end: number;
  progress: number;
  task?: TeamyarTask;
}

const STATUS_COLOR: Record<string, string> = {
  todo: "#94a3b8",
  doing: "#3b82f6",
  blocked: "#ef4444",
  done: "#10b981",
};

const rows = computed<Row[]>(() => {
  const out: Row[] = [];
  const groups: { phase: Phase | null; tasks: TeamyarTask[] }[] = props.phases.map((p) => ({
    phase: p,
    tasks: props.tasks.filter((t) => t.phase === p.id),
  }));
  const loose = props.tasks.filter((t) => !t.phase || !props.phases.some((p) => p.id === t.phase));
  if (loose.length) groups.push({ phase: null, tasks: loose });

  for (const g of groups) {
    if (g.phase) {
      const ts = g.tasks;
      const start = ts.length ? Math.min(...ts.map((t) => toDay(t.start_on))) : today;
      const end = ts.length ? Math.max(...ts.map((t) => toDay(t.end_on))) : today;
      const w = ts.reduce((a, t) => a + Math.max(toDay(t.end_on) - toDay(t.start_on), 1), 0);
      const p = w
        ? ts.reduce((a, t) => a + Math.max(toDay(t.end_on) - toDay(t.start_on), 1) * t.progress, 0) / w
        : 0;
      out.push({
        kind: "phase", key: `p${g.phase.id}`, title: g.phase.title,
        color: g.phase.color || "#6366f1", start, end, progress: Math.round(p),
      });
    } else if (groups.length > 1) {
      out.push({
        kind: "phase", key: "p0", title: "بدون فاز", color: "#94a3b8",
        start: today, end: today, progress: 0,
      });
    }
    for (const t of g.tasks) {
      out.push({
        kind: "task", key: `t${t.id}`, title: t.title,
        color: STATUS_COLOR[t.status], start: toDay(t.start_on), end: toDay(t.end_on),
        progress: t.progress, task: t,
      });
    }
  }
  return out;
});

const byId = computed(() => new Map(props.tasks.map((t) => [t.id, t])));

function tip(t: TeamyarTask): string {
  const dep = t.depends_on ? byId.value.get(t.depends_on) : null;
  return [
    t.title,
    `${jalaliLabel(t.start_on)} تا ${jalaliLabel(t.end_on)}`,
    `${t.status_label} · ${faDigits(t.progress)}٪`,
    t.owner ? `مسئول: ${t.owner}` : "",
    dep ? `وابسته به: ${dep.title}` : "",
  ].filter(Boolean).join("\n");
}

/** Open scrolled to today, not to the start of the project. */
const scroller = ref<HTMLElement | null>(null);
function scrollToToday() {
  const el = scroller.value;
  if (!el) return;
  // RTL scroll: 0 is the right edge, going negative to the left.
  el.scrollLeft = -Math.max(pos(today) - el.clientWidth / 3, 0);
}
onMounted(() => nextTick(scrollToToday));
watch(zoom, () => nextTick(scrollToToday));

const ROW_H = 36;
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <div class="flex flex-wrap items-center gap-2 mb-3">
      <h3 class="font-bold text-ink">گانت چارت</h3>
      <span class="flex-1"></span>
      <div class="flex items-center gap-3 text-[11px] text-slate-500 ml-2">
        <span v-for="(c, k) in STATUS_COLOR" :key="k" class="flex items-center gap-1">
          <i class="w-2.5 h-2.5 rounded-sm inline-block" :style="{ background: c }"></i>
          {{ { todo: "شروع نشده", doing: "در حال انجام", blocked: "متوقف", done: "انجام شده" }[k] }}
        </span>
      </div>
      <div class="flex bg-slate-100 rounded-xl p-0.5">
        <button
          v-for="z in ZOOMS" :key="z.key"
          class="px-3 py-1 text-xs rounded-lg"
          :class="zoom === z.key ? 'bg-surface text-ink shadow-soft' : 'text-slate-500'"
          @click="zoom = z.key"
        >{{ z.label }}</button>
      </div>
      <button class="text-xs text-slate-500 hover:text-ink px-2" @click="scrollToToday">امروز</button>
    </div>

    <p v-if="!tasks.length" class="text-sm text-slate-400 text-center py-10">
      هنوز فعالیتی تعریف نشده. با «+ فعالیت» اولین مرحله را بسازید.
    </p>

    <div v-else class="flex border border-slate-100 rounded-xl overflow-hidden">
      <!-- Names column (right, in RTL) -->
      <div class="w-44 sm:w-60 shrink-0 border-l border-slate-100 bg-surface z-10">
        <div class="h-12 border-b border-slate-100 flex items-end px-3 pb-1 text-[11px] text-slate-400">فعالیت</div>
        <div
          v-for="r in rows" :key="r.key"
          class="flex items-center gap-2 px-3 border-b border-slate-50 text-sm truncate"
          :class="r.kind === 'phase' ? 'font-bold text-ink bg-slate-50' : 'text-slate-600 cursor-pointer hover:bg-slate-50'"
          :style="{ height: `${ROW_H}px` }"
          :title="r.task ? tip(r.task) : r.title"
          @click="r.task && emit('open', r.task)"
        >
          <i v-if="r.kind === 'phase'" class="w-2 h-2 rounded-full shrink-0" :style="{ background: r.color }"></i>
          <span v-else-if="r.task?.is_milestone" class="text-amber-500 shrink-0">◆</span>
          <span class="truncate">{{ r.title }}</span>
          <span v-if="r.task?.is_overdue" class="text-[10px] text-red-500 shrink-0">عقب</span>
        </div>
      </div>

      <!-- Timeline -->
      <div ref="scroller" class="flex-1 overflow-x-auto">
        <div class="relative" :style="{ width: `${width}px` }">
          <!-- Month header -->
          <div class="h-12 border-b border-slate-100 relative">
            <div
              v-for="m in months" :key="m.key"
              class="absolute top-0 h-6 border-l border-slate-100 text-[11px] text-slate-500 px-1 truncate"
              :style="{ right: `${pos(m.start)}px`, width: `${m.days * dayPx}px` }"
            >{{ m.label }}</div>
            <div
              v-for="t in ticks" :key="t.day"
              class="absolute top-6 h-6 text-[10px] text-slate-400 border-l border-slate-100 px-0.5"
              :style="{ right: `${pos(t.day)}px` }"
            >{{ t.label }}</div>
          </div>

          <!-- Grid lines + today -->
          <div class="absolute inset-x-0 top-12 bottom-0 pointer-events-none">
            <div
              v-for="t in ticks" :key="t.day"
              class="absolute top-0 bottom-0 border-l border-slate-50"
              :style="{ right: `${pos(t.day)}px` }"
            ></div>
            <div
              class="absolute top-0 bottom-0 w-px bg-red-400/70"
              :style="{ right: `${pos(today) + dayPx / 2}px` }"
            ></div>
          </div>

          <!-- Bars -->
          <div
            v-for="r in rows" :key="r.key"
            class="relative border-b border-slate-50"
            :class="r.kind === 'phase' ? 'bg-slate-50/60' : ''"
            :style="{ height: `${ROW_H}px` }"
          >
            <template v-if="r.kind === 'phase'">
              <div
                v-if="r.end > r.start"
                class="absolute top-1/2 -translate-y-1/2 h-2 rounded-full opacity-80"
                :style="{ right: `${pos(r.start)}px`, width: `${(r.end - r.start + 1) * dayPx}px`, background: r.color }"
              ></div>
            </template>
            <template v-else-if="r.task">
              <button
                v-if="r.task.is_milestone"
                class="absolute top-1/2 w-4 h-4 rotate-45 -translate-y-1/2 border-2"
                :style="{
                  right: `${pos(r.end) + dayPx / 2 - 8}px`,
                  background: r.task.status === 'done' ? '#10b981' : '#f59e0b',
                  borderColor: r.task.is_overdue ? '#ef4444' : 'transparent',
                }"
                :title="tip(r.task)"
                @click="emit('open', r.task)"
              ></button>
              <button
                v-else
                class="absolute top-1.5 bottom-1.5 rounded-md overflow-hidden text-right"
                :class="r.task.is_overdue ? 'ring-2 ring-red-400' : ''"
                :style="{
                  right: `${pos(r.start)}px`,
                  width: `${Math.max((r.end - r.start + 1) * dayPx, 6)}px`,
                  background: `${r.color}33`,
                }"
                :title="tip(r.task)"
                @click="emit('open', r.task)"
              >
                <div class="absolute inset-y-0 right-0" :style="{ width: `${r.progress}%`, background: r.color }"></div>
                <span
                  v-if="(r.end - r.start + 1) * dayPx > 60"
                  class="relative px-1.5 text-[10px] text-ink leading-[24px] whitespace-nowrap"
                >{{ faDigits(r.progress) }}٪</span>
              </button>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
