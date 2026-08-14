<script setup lang="ts">
/**
 * وظایف — the same list, read five ways.
 *
 * The first version was one flat list per tab and it made every task look
 * equally urgent, which is the failure mode of every task tool. Three things
 * carry the weight now:
 *
 * **Dates group the list.** «عقب‌افتاده / امروز / فردا / این هفته / بعداً» is
 * how people actually triage, and a heading costs nothing to read. A flat
 * list sorted by date makes you compute the same grouping in your head.
 *
 * **Priority is a colour on the left edge**, not a chip competing with the
 * title. Urgent is meant to be seen without being read.
 *
 * **انجام شده is grouped by day**, which is the whole reason `done_at` is a
 * timestamp rather than a flag.
 *
 * The calendar is a real month grid: a list sorted by due date answers «what
 * is next», and only a grid answers «which week is overloaded».
 */
import { computed, onMounted, ref, watch } from "vue";
import { workApi, type Task, type TaskBox } from "@/api/officeWork";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import TaskForm from "@/components/office/TaskForm.vue";
import QuickTaskForm from "@/components/office/QuickTaskForm.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

type Counts = { mine: number; today: number; overdue: number; others: number };

const TABS: { key: TaskBox; label: string; badge?: keyof Counts }[] = [
  { key: "mine", label: "کارهای من", badge: "mine" },
  { key: "today", label: "امروز و عقب‌افتاده", badge: "today" },
  { key: "others", label: "پیگیری از دیگران", badge: "others" },
  { key: "calendar", label: "تقویم" },
  { key: "done", label: "انجام شده" },
];

const box = ref<TaskBox>("mine");
const rows = ref<Task[]>([]);
const counts = ref<Counts>({ mine: 0, today: 0, overdue: 0, others: 0 });
const loading = ref(true);
const error = ref("");
const editing = ref<Task | null>(null);
const creating = ref(false);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const data = await workApi.taskBox(box.value);
    rows.value = data.rows;
    counts.value = data.counts;
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(box, load);

async function toggle(task: Task) {
  const was = task.done_at;
  // Optimistic: a checkbox that waits for the network feels broken. The
  // server is the only writer, so a failure just reloads the truth.
  task.done_at = was ? null : new Date().toISOString();
  try {
    await workApi.toggleTask(task.id);
    await load();
  } catch (e) {
    task.done_at = was;
    error.value = apiError(e);
  }
}

function onSaved() {
  creating.value = false;
  editing.value = null;
  load();
}

// -- grouping ----------------------------------------------------------
const DAY = 86_400_000;

function startOfDay(d: Date | string): number {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x.getTime();
}

/**
 * The five buckets people triage by. Ordered, and empty ones are dropped —
 * a heading with nothing under it is noise.
 */
const grouped = computed(() => {
  if (box.value === "done") return doneByDay.value;

  const today = startOfDay(new Date());
  const buckets: Record<string, Task[]> = {
    "عقب‌افتاده": [], "امروز": [], "فردا": [], "این هفته": [],
    "بعداً": [], "بدون مهلت": [],
  };
  for (const t of rows.value) {
    if (!t.due_on) { buckets["بدون مهلت"].push(t); continue; }
    const due = startOfDay(t.due_on);
    const days = Math.round((due - today) / DAY);
    if (days < 0) buckets["عقب‌افتاده"].push(t);
    else if (days === 0) buckets["امروز"].push(t);
    else if (days === 1) buckets["فردا"].push(t);
    else if (days <= 7) buckets["این هفته"].push(t);
    else buckets["بعداً"].push(t);
  }
  return Object.entries(buckets)
    .filter(([, list]) => list.length)
    .map(([label, list]) => ({ label, list, warn: label === "عقب‌افتاده" }));
});

/** انجام شده, by the day it was finished — what `done_at` exists for. */
const doneByDay = computed(() => {
  const map = new Map<string, Task[]>();
  for (const t of rows.value) {
    if (!t.done_at) continue;
    const key = faDate(t.done_at);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(t);
  }
  return [...map.entries()].map(([label, list]) => ({ label, list, warn: false }));
});

// -- calendar ----------------------------------------------------------
/**
 * A month of due dates. Built from the Gregorian dates the API returns and
 * labelled with the Jalali day, so the grid lines up with the week while the
 * numbers read the way everyone here reads dates.
 */
const monthOffset = ref(0);

const calendar = computed(() => {
  const base = new Date();
  base.setMonth(base.getMonth() + monthOffset.value);
  base.setDate(1);
  const first = new Date(base);
  // Persian week starts on Saturday; JS getDay() has Sunday at 0.
  const lead = (first.getDay() + 1) % 7;
  const start = new Date(first);
  start.setDate(start.getDate() - lead);

  const byDay = new Map<number, Task[]>();
  for (const t of rows.value) {
    if (!t.due_on) continue;
    const k = startOfDay(t.due_on);
    if (!byDay.has(k)) byDay.set(k, []);
    byDay.get(k)!.push(t);
  }

  const today = startOfDay(new Date());
  const cells = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    const key = startOfDay(d);
    cells.push({
      key,
      label: faDate(d.toISOString()).split("/").pop() ?? "",
      inMonth: d.getMonth() === base.getMonth(),
      isToday: key === today,
      tasks: byDay.get(key) ?? [],
    });
  }
  return { cells, title: faDate(base.toISOString()).split("/").slice(0, 2).join("/") };
});

const WEEKDAYS = ["ش", "ی", "د", "س", "چ", "پ", "ج"];

/** Priority as a left edge, seen without being read. */
const EDGE: Record<string, string> = {
  urgent: "#ef4444",
  high: "#f59e0b",
  normal: "transparent",
  low: "transparent",
};
</script>

<template>
  <div class="space-y-4">
    <!-- Tabs + the one action, together -->
    <div class="bg-surface rounded-card shadow-soft p-2 flex flex-wrap items-center gap-1">
      <button
        v-for="t in TABS" :key="t.key"
        class="office-tab px-3.5 py-2 rounded-xl text-sm flex items-center gap-2"
        :class="box === t.key ? 'is-active' : 'text-slate-500'"
        @click="box = t.key"
      >
        {{ t.label }}
        <span
          v-if="t.badge && counts[t.badge]"
          class="text-[11px] rounded-full px-1.5 py-0.5 ltr-nums"
          :class="box === t.key
            ? 'bg-white/25'
            : (t.key === 'today' && counts.overdue ? 'bg-red-500 text-white' : 'bg-slate-100 text-slate-600')"
        >{{ num(counts[t.badge]) }}</span>
      </button>

      <span class="flex-1"></span>

      <button
        class="office-btn rounded-xl px-4 py-2 text-sm"
        @click="creating = true"
      >+ وظیفه جدید</button>
    </div>

    <!-- Capture is inline: a modal to write down «فردا با انبار تماس بگیر»
         is a context switch for a one-line thought. -->
    <QuickTaskForm v-if="creating" @close="creating = false" @saved="onSaved" />

    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3">
      {{ error }}
    </p>

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 6" :key="i" class="h-14 rounded-xl" />
    </div>

    <!-- ===== Calendar ===== -->
    <div v-else-if="box === 'calendar'" class="bg-surface rounded-card shadow-soft p-3 sm:p-4">
      <div class="flex items-center justify-between mb-3">
        <button class="text-slate-400 hover:text-ink px-2 py-1" @click="monthOffset--">
          ‹ ماه قبل
        </button>
        <span class="text-sm font-bold text-ink ltr-nums">{{ calendar.title }}</span>
        <button class="text-slate-400 hover:text-ink px-2 py-1" @click="monthOffset++">
          ماه بعد ›
        </button>
      </div>

      <div class="grid grid-cols-7 gap-1 text-center text-[11px] text-slate-400 mb-1">
        <span v-for="d in WEEKDAYS" :key="d">{{ d }}</span>
      </div>
      <div class="grid grid-cols-7 gap-1">
        <div
          v-for="c in calendar.cells" :key="c.key"
          class="min-h-[4.5rem] rounded-xl p-1.5 text-right transition-colors"
          :class="[
            c.inMonth ? 'bg-slate-50' : 'bg-transparent opacity-40',
            c.isToday ? 'ring-2' : '',
          ]"
          :style="c.isToday ? { '--tw-ring-color': 'var(--sec-solid)' } : {}"
        >
          <span class="text-[11px] ltr-nums" :class="c.isToday ? 'font-bold text-ink' : 'text-slate-400'">
            {{ c.label }}
          </span>
          <button
            v-for="t in c.tasks.slice(0, 3)" :key="t.id"
            class="block w-full text-right text-[10px] leading-tight truncate rounded px-1 py-0.5 mt-0.5"
            :class="t.is_overdue ? 'bg-red-100 text-red-700' : 'bg-white text-ink'"
            :title="t.title"
            @click="editing = t"
          >{{ t.title }}</button>
          <span v-if="c.tasks.length > 3" class="block text-[10px] text-slate-400 ltr-nums mt-0.5">
            +{{ num(c.tasks.length - 3) }}
          </span>
        </div>
      </div>
    </div>

    <!-- ===== Grouped list ===== -->
    <EmptyState
      v-else-if="!rows.length"
      :title="box === 'done' ? 'کاری در ۳۰ روز گذشته تمام نشده' : 'کاری اینجا نیست'"
      hint="با «وظیفه جدید» اولین کار را ثبت کنید."
    />

    <div v-else class="space-y-4">
      <div
        v-for="group in grouped" :key="group.label"
        class="bg-surface rounded-card shadow-soft overflow-hidden"
      >
        <div class="px-4 py-2.5 border-b border-slate-100 flex items-center gap-2">
          <h3 class="text-sm font-bold" :class="group.warn ? 'text-red-600' : 'text-ink'">
            {{ group.label }}
          </h3>
          <span class="text-xs text-slate-400 ltr-nums">{{ num(group.list.length) }}</span>
        </div>

        <div class="divide-y divide-slate-100">
          <div
            v-for="task in group.list" :key="task.id"
            class="flex items-start gap-3 pl-4 pr-0 py-3 hover:bg-slate-50 transition-colors"
          >
            <span
              class="w-1 self-stretch rounded-l-full shrink-0"
              :style="{ background: EDGE[task.priority] }"
            ></span>

            <button
              class="mt-0.5 w-5 h-5 rounded-md border-2 shrink-0 grid place-items-center transition-colors"
              :class="task.done_at
                ? 'bg-emerald-500 border-emerald-500 text-white'
                : 'border-slate-300 hover:border-slate-400'"
              :aria-label="task.done_at ? 'بازکردن' : 'انجام شد'"
              @click="toggle(task)"
            >
              <svg v-if="task.done_at" class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <path d="M20 6 9 17l-5-5" />
              </svg>
            </button>

            <button class="min-w-0 flex-1 text-right" @click="editing = task">
              <span
                class="block text-sm truncate"
                :class="task.done_at ? 'text-slate-400 line-through' : 'text-ink'"
              >{{ task.title }}</span>
              <span class="flex flex-wrap items-center gap-2 text-xs text-slate-400 mt-0.5">
                <span v-if="task.project_name">{{ task.project_name }}</span>
                <span
                  v-for="tag in task.tags_detail" :key="tag.id"
                  class="rounded-full px-2 py-0.5 bg-slate-100 text-slate-500"
                >{{ tag.name_fa }}</span>
                <span v-if="task.comment_count" class="ltr-nums">
                  💬 {{ num(task.comment_count) }}
                </span>
              </span>
            </button>

            <div class="flex items-center gap-3 shrink-0">
              <span
                v-if="task.due_on && box !== 'done'"
                class="text-xs ltr-nums"
                :class="task.is_overdue ? 'text-red-600 font-medium' : 'text-slate-400'"
              >
                {{ faDate(task.due_on) }}
                <template v-if="task.is_overdue"> · {{ num(task.days_late) }} روز</template>
              </span>
              <UserAvatar
                v-if="task.assignee_detail"
                :user="task.assignee_detail as any"
                :size="26"
                :title="task.assignee_detail.name"
              />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Editing keeps the full form: reviewing every field is a different
         act from capturing a thought. -->
    <TaskForm v-if="editing" :task="editing" @close="editing = null" @saved="onSaved" />
  </div>
</template>
