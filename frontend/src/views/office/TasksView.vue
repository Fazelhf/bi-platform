<script setup lang="ts">
/**
 * وظایف — five readings of one list.
 *
 * «پیگیری از دیگران» is the one worth naming: tasks I created that somebody
 * else owns. It is a query, not a watch list, so it stays right when a task
 * is reassigned — and it is the tab a manager actually lives in.
 *
 * The tab counts come from the server. Counting the rows on screen would
 * only ever count the first page.
 */
import { onMounted, ref, watch } from "vue";
import { workApi, type Task, type TaskBox } from "@/api/officeWork";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import TaskForm from "@/components/office/TaskForm.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

const TABS: { key: TaskBox; label: string; badge?: keyof Counts }[] = [
  { key: "mine", label: "کارهای من", badge: "mine" },
  { key: "today", label: "امروز و عقب‌افتاده", badge: "today" },
  { key: "others", label: "پیگیری از دیگران", badge: "others" },
  { key: "calendar", label: "سررسیددار" },
  { key: "done", label: "انجام شده" },
];

interface Counts { mine: number; today: number; overdue: number; others: number }

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
  // Optimistic: ticking a box that waits for the network feels broken, and
  // the server is the only writer so a failure just reloads the truth.
  const was = task.done_at;
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

/** Overdue is the only thing that shouts. Everything else stays quiet. */
function dueClass(task: Task): string {
  if (task.is_done) return "text-slate-400";
  if (task.is_overdue) return "text-red-600";
  return "text-slate-400";
}

const PRIORITY_CLASS: Record<string, string> = {
  urgent: "bg-red-100 text-red-700",
  high: "bg-amber-100 text-amber-700",
  normal: "",
  low: "",
};
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-2 flex flex-wrap gap-1">
      <button
        v-for="t in TABS" :key="t.key"
        class="px-4 py-2 rounded-xl text-sm transition-colors flex items-center gap-2"
        :class="box === t.key ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
        @click="box = t.key"
      >
        {{ t.label }}
        <span
          v-if="t.badge && counts[t.badge]"
          class="text-[11px] rounded-full px-1.5 py-0.5 ltr-nums"
          :class="[
            box === t.key ? 'bg-white/20' : 'bg-slate-200 text-slate-600',
            t.key === 'today' && counts.overdue ? 'bg-red-500 text-white' : '',
          ]"
        >{{ num(counts[t.badge]) }}</span>
      </button>
    </div>

    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <button
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm"
        @click="creating = true"
      >+ وظیفه جدید</button>
      <span v-if="counts.overdue" class="text-xs text-red-600">
        {{ num(counts.overdue) }} کار عقب افتاده است
      </span>
    </div>

    <p
      v-if="error"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3"
    >{{ error }}</p>

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 6" :key="i" class="h-14 rounded-xl" />
    </div>

    <EmptyState
      v-else-if="!rows.length"
      :title="box === 'done' ? 'کاری در ۳۰ روز گذشته تمام نشده' : 'کاری اینجا نیست'"
      hint="با «وظیفه جدید» اولین کار را ثبت کنید."
    />

    <div v-else class="bg-surface rounded-card shadow-soft divide-y divide-slate-100 overflow-hidden">
      <div
        v-for="task in rows" :key="task.id"
        class="px-4 py-3 flex items-start gap-3 hover:bg-slate-50 transition-colors"
      >
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
            <span v-if="task.comment_count" class="ltr-nums">
              💬 {{ num(task.comment_count) }}
            </span>
            <span
              v-if="PRIORITY_CLASS[task.priority]"
              class="rounded-full px-2 py-0.5"
              :class="PRIORITY_CLASS[task.priority]"
            >{{ task.priority_label }}</span>
          </span>
        </button>

        <div class="flex items-center gap-3 shrink-0">
          <span v-if="task.due_on" class="text-xs ltr-nums" :class="dueClass(task)">
            {{ faDate(task.due_on) }}
            <span v-if="task.is_overdue"> · {{ num(task.days_late) }} روز</span>
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

    <TaskForm v-if="creating" @close="creating = false" @saved="onSaved" />
    <TaskForm v-if="editing" :task="editing" @close="editing = null" @saved="onSaved" />
  </div>
</template>
