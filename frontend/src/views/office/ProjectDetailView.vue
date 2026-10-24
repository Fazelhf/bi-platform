<script setup lang="ts">
/** یک پروژه: اعضا، پیشرفت، و وظایفش به تفکیک دسته. */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { workApi, type Project, type Task } from "@/api/officeWork";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import TaskForm from "@/components/office/TaskForm.vue";
import QuickTaskForm from "@/components/office/QuickTaskForm.vue";
import api from "@/api/client";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";
import NavIcon from "@/components/NavIcon.vue";
import { confirm, toast } from "@/composables/useUi";

const route = useRoute();
const router = useRouter();

const project = ref<Project | null>(null);
const groups = ref<{ id: number; name: string; tasks: Task[] }[]>([]);
const ungrouped = ref<Task[]>([]);
const loading = ref(true);
const error = ref("");
const editing = ref<Task | null>(null);
/** Which column has its inline composer open. 0 = «بدون دسته‌بندی». */
const addingTo = ref<number | null>(null);
const composing = ref(false);

/** Categories are made where they are needed, not in a settings page. */
const newGroup = ref("");
const savingGroup = ref(false);

async function addGroup() {
  const name = newGroup.value.trim();
  if (!name || !project.value) return;
  savingGroup.value = true;
  try {
    await api.post("/office/task-groups/", {
      project: project.value.id, name, order: groups.value.length,
    });
    newGroup.value = "";
    await load();
  } catch (e) {
    error.value = apiError(e);
  } finally {
    savingGroup.value = false;
  }
}

/**
 * Renaming happens in place. A browser `prompt()` would be a modal dialog
 * for a two-word edit, and it cannot be cancelled with Escape on every
 * platform — the heading itself becomes the input instead.
 */
const renamingId = ref<number | null>(null);
const renameText = ref("");

function startRename(id: number, current: string) {
  renamingId.value = id;
  renameText.value = current;
}

async function commitRename() {
  const id = renamingId.value;
  const next = renameText.value.trim();
  renamingId.value = null;
  if (!id || !next) return;
  await api.patch(`/office/task-groups/${id}/`, { name: next });
  await load();
}

async function removeGroup(id: number) {
  // Tasks survive: the FK is SET_NULL, so they fall back to «بدون دسته‌بندی»
  // rather than disappearing with the column.
  const ok = await confirm({
    title: "حذف دسته",
    message: "دسته حذف می‌شود؛ کارهایش به «بدون دسته‌بندی» می‌روند.",
    danger: true,
  });
  if (!ok) return;
  await api.delete(`/office/task-groups/${id}/`);
  await load();
}

/** Only the first load shows a skeleton; refreshes swap data in place. */
async function load() {
  if (!project.value) loading.value = true;
  try {
    const data = await workApi.board(Number(route.params.id));
    project.value = data.project;
    groups.value = data.groups;
    ungrouped.value = data.ungrouped;
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

/**
 * Tick in place: the box fills at once and the progress bar moves with it.
 * The board is refreshed quietly afterwards so derived numbers stay honest.
 */
async function toggle(task: Task) {
  const was = task.done_at;
  task.done_at = was ? null : new Date().toISOString();
  if (project.value) project.value.done_count += was ? -1 : 1;
  try {
    Object.assign(task, await workApi.toggleTask(task.id));
    load();
  } catch (e) {
    task.done_at = was;
    if (project.value) project.value.done_count += was ? 1 : -1;
    toast.error(apiError(e));
  }
}

// -- board ---------------------------------------------------------------
/**
 * Column colours. A board of identical grey columns reads as a spreadsheet;
 * a strong header per column is what lets you find «در انتظار تأیید» across
 * the room. Cycled by position — the stage, not the data, owns the colour.
 */
const COLUMN_HUES = [
  "22 163 74", "234 88 12", "37 99 235", "217 119 6",
  "13 148 136", "147 51 234", "219 39 119", "71 85 105",
];
const hue = (i: number) => COLUMN_HUES[i % COLUMN_HUES.length];

type Column = { id: number; name: string; tasks: Task[]; hue: string };

const columns = computed<Column[]>(() => {
  const cols: Column[] = groups.value.map((g, i) => ({ ...g, hue: hue(i) }));
  // Tasks with no category get their own column — first, and only when it
  // has something in it (or there are no categories at all yet).
  if (ungrouped.value.length || !groups.value.length) {
    cols.unshift({ id: 0, name: "بدون دسته‌بندی", tasks: ungrouped.value, hue: "100 116 139" });
  }
  return cols;
});

function doneShare(c: Column): number {
  if (!c.tasks.length) return 0;
  return Math.round((c.tasks.filter((t) => t.done_at).length / c.tasks.length) * 100);
}

/** Open first, finished at the bottom — the column reads as «what is left». */
function ordered(tasks: Task[]): Task[] {
  return [...tasks].sort((a, b) => Number(!!a.done_at) - Number(!!b.done_at));
}

// Drag a card onto another column = move it to that category. Native DnD:
// no library, and the move is one PATCH the server already accepts.
const dragging = ref<Task | null>(null);
const overCol = ref<number | null>(null);

function onDragStart(t: Task, e: DragEvent) {
  dragging.value = t;
  e.dataTransfer?.setData("text/plain", String(t.id));
  if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
}

async function onDrop(col: Column) {
  const t = dragging.value;
  dragging.value = null;
  overCol.value = null;
  if (!t || (t.group ?? 0) === col.id) return;
  // Move locally first, so the card lands where it was dropped.
  const from = columns.value.find((c) => c.tasks.includes(t));
  if (from) from.tasks.splice(from.tasks.indexOf(t), 1);
  col.tasks.push(t);
  const before = t.group;
  t.group = col.id || null;
  try {
    await workApi.saveTask({ group: col.id || null }, t.id);
    toast.success(`«${t.title}» به «${col.name}» رفت.`);
  } catch (e) {
    t.group = before;
    toast.error(apiError(e));
  }
  load();
}

function onSaved() {
  composing.value = false;
  addingTo.value = null;
  editing.value = null;
  load();
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-28 rounded-card" />
      <div class="flex gap-3">
        <Skeleton v-for="i in 4" :key="i" class="h-80 w-72 rounded-card shrink-0" />
      </div>
    </div>

    <p v-else-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3">
      {{ error }}
    </p>

    <template v-else-if="project">
      <!-- Header -->
      <section class="office-card p-4 sm:p-5">
        <div class="flex flex-wrap items-center gap-4">
          <span
            class="w-14 h-14 rounded-2xl grid place-items-center text-white text-xl font-bold shrink-0 shadow-soft"
            :style="{ background: project.color || 'rgb(var(--office-hue-projects))' }"
          >{{ project.name.trim().slice(0, 2) }}</span>
          <div class="min-w-0 flex-1">
            <h2 class="text-lg font-bold text-ink truncate">{{ project.name }}</h2>
            <p v-if="project.description" class="text-sm text-slate-500 mt-0.5 line-clamp-1">
              {{ project.description }}
            </p>
            <div class="flex flex-wrap items-center gap-3 mt-1.5 text-xs text-slate-400">
              <span v-if="project.due_on" class="flex items-center gap-1 ltr-nums">
                <NavIcon name="calendar" :size="12" /> مهلت {{ faDate(project.due_on) }}
              </span>
              <span v-if="project.overdue_count" class="flex items-center gap-1 text-amber-600 ltr-nums">
                <NavIcon name="clock" :size="12" /> {{ num(project.overdue_count) }} کار عقب‌افتاده
              </span>
            </div>
          </div>
          <div class="flex -space-x-2 space-x-reverse">
            <UserAvatar
              v-for="m in project.memberships.slice(0, 7)" :key="m.id"
              :user="m.user_detail" :size="32"
              class="ring-2 ring-surface rounded-full"
            />
          </div>
          <button class="office-btn-ghost shrink-0" @click="router.push({ name: 'office-projects' })">
            <NavIcon name="arrow-right" :size="15" /> پروژه‌ها
          </button>
        </div>

        <div class="mt-4">
          <div class="flex items-baseline justify-between text-xs mb-1.5">
            <span class="text-slate-500">وضعیت کل پروژه</span>
            <span class="text-ink font-semibold ltr-nums">
              {{ num(Math.round(project.progress_pct)) }}٪
              <span class="text-slate-400 font-normal">· {{ num(project.done_count) }} از {{ num(project.task_count) }}</span>
            </span>
          </div>
          <div class="h-2.5 bg-slate-100 rounded-full overflow-hidden">
            <div
              class="h-full rounded-full transition-all duration-500"
              :style="{
                width: `${Math.max(project.progress_pct, 1)}%`,
                background: project.progress_pct >= 100 ? '#10b981' : (project.color || 'rgb(var(--office-hue-projects))'),
              }"
            ></div>
          </div>
        </div>
      </section>

      <!-- Board -->
      <div class="flex gap-3 overflow-x-auto pb-3 snap-x items-start">
        <section
          v-for="col in columns" :key="col.id"
          class="w-[17.5rem] shrink-0 snap-start flex flex-col rounded-card bg-slate-100/70 transition-shadow"
          :class="overCol === col.id ? 'ring-2 ring-offset-2' : ''"
          :style="overCol === col.id ? { '--tw-ring-color': `rgb(${col.hue})` } : {}"
          @dragover.prevent="overCol = col.id"
          @drop.prevent="onDrop(col)"
        >
          <!-- The column's coloured header is its identity. -->
          <header
            class="rounded-t-card px-3 h-11 flex items-center gap-1.5 text-white"
            :style="{ background: `rgb(${col.hue})` }"
          >
            <input
              v-if="renamingId === col.id"
              v-model="renameText"
              class="flex-1 min-w-0 bg-white/20 rounded-lg px-2 h-7 text-sm text-white outline-none"
              autofocus
              @keydown.enter.prevent="commitRename"
              @keydown.esc="renamingId = null"
              @blur="commitRename"
            />
            <h3 v-else class="flex-1 min-w-0 truncate text-sm font-bold">
              {{ col.name }}
              <span class="font-normal opacity-80 ltr-nums">({{ num(col.tasks.length) }})</span>
            </h3>
            <template v-if="col.id">
              <button
                class="w-7 h-7 rounded-lg grid place-items-center hover:bg-white/20"
                aria-label="تغییر نام ستون" title="تغییر نام"
                @click="startRename(col.id, col.name)"
              ><NavIcon name="pencil" :size="14" /></button>
              <button
                class="w-7 h-7 rounded-lg grid place-items-center hover:bg-white/20"
                aria-label="حذف ستون" title="حذف ستون"
                @click="removeGroup(col.id)"
              ><NavIcon name="trash" :size="14" /></button>
            </template>
          </header>

          <!-- How much of this column is done. -->
          <div class="h-1.5 bg-black/5 overflow-hidden" :title="`${doneShare(col)}٪ انجام شده`">
            <div
              class="h-full transition-all duration-500"
              :style="{ width: `${doneShare(col)}%`, background: `rgb(${col.hue} / 0.6)` }"
            ></div>
          </div>

          <div class="p-2 space-y-2 min-h-[6rem] max-h-[calc(100dvh-20rem)] overflow-y-auto">
            <button
              v-if="addingTo !== col.id"
              class="w-full h-9 rounded-xl border border-dashed border-slate-300 text-xs text-slate-500
                     hover:bg-surface hover:text-ink hover:border-slate-400 flex items-center justify-center gap-1.5 transition-colors"
              @click="addingTo = col.id"
            ><NavIcon name="plus" :size="14" /> وظیفه جدید</button>
            <div v-else class="bg-surface rounded-xl p-2 shadow-soft">
              <QuickTaskForm
                :project-id="project.id"
                :group-id="col.id || null"
                @close="addingTo = null" @saved="onSaved"
              />
            </div>

            <article
              v-for="task in ordered(col.tasks)" :key="task.id"
              draggable="true"
              class="relative bg-surface rounded-xl shadow-soft p-3 cursor-grab active:cursor-grabbing
                     hover:shadow-pop hover:-translate-y-px transition-all border-r-[3px]"
              :class="[
                dragging?.id === task.id ? 'opacity-40 rotate-1' : '',
                task.done_at ? 'opacity-60' : '',
              ]"
              :style="{ borderRightColor: task.priority === 'urgent' ? '#ef4444' : task.priority === 'high' ? '#f59e0b' : 'transparent' }"
              @dragstart="onDragStart(task, $event)"
              @dragend="dragging = null; overCol = null"
              @click="editing = task"
            >
              <div class="flex items-start gap-2">
                <button
                  class="mt-0.5 w-[18px] h-[18px] rounded-md border-2 shrink-0 grid place-items-center transition-colors"
                  :class="task.done_at
                    ? 'bg-emerald-500 border-emerald-500 text-white'
                    : 'border-slate-300 hover:border-emerald-500 hover:bg-emerald-50'"
                  :aria-label="task.done_at ? 'بازکردن' : 'انجام شد'"
                  @click.stop="toggle(task)"
                ><NavIcon v-if="task.done_at" name="check" :size="12" /></button>
                <p
                  class="flex-1 min-w-0 text-sm font-medium leading-6"
                  :class="task.done_at ? 'text-slate-400 line-through' : 'text-ink'"
                >{{ task.title }}</p>
              </div>

              <p
                v-if="task.description"
                class="mt-1.5 text-xs text-slate-500 leading-5 line-clamp-3 whitespace-pre-line"
              >{{ task.description }}</p>

              <div v-if="task.tags_detail?.length" class="flex flex-wrap gap-1 mt-2">
                <span
                  v-for="tag in task.tags_detail" :key="tag.id"
                  class="text-[10px] rounded-full px-2 py-0.5"
                  :class="tag.color ? 'office-tag' : 'bg-slate-100 text-slate-500'"
                  :style="tag.color ? { '--tag': tag.color } : {}"
                >{{ tag.name_fa }}</span>
              </div>

              <footer class="flex items-center gap-2 mt-2.5 text-[11px] text-slate-400">
                <span
                  v-if="task.due_on"
                  class="flex items-center gap-1 rounded-md px-1.5 py-0.5 ltr-nums"
                  :class="task.is_overdue ? 'bg-red-50 text-red-600 font-medium' : 'bg-slate-50'"
                ><NavIcon name="clock" :size="11" /> {{ faDate(task.due_on) }}</span>
                <span v-if="task.comment_count" class="flex items-center gap-0.5 ltr-nums">
                  <NavIcon name="chat" :size="11" /> {{ num(task.comment_count) }}
                </span>
                <span class="flex-1"></span>
                <UserAvatar v-if="task.assignee_detail" :user="task.assignee_detail" :size="24" />
              </footer>
            </article>

            <p v-if="!col.tasks.length && addingTo !== col.id" class="text-center text-[11px] text-slate-400 py-4">
              کاری را اینجا بکشید
            </p>
          </div>
        </section>

        <!-- New column, at the end where a new column goes. -->
        <section class="w-[17.5rem] shrink-0 rounded-card border-2 border-dashed border-slate-200 p-3 space-y-2">
          <p class="text-xs font-medium text-slate-500 flex items-center gap-1.5">
            <NavIcon name="plus" :size="14" /> ستون تازه
          </p>
          <input
            v-model="newGroup"
            class="office-input"
            placeholder="مثلاً «در انتظار تأیید»"
            @keydown.enter.prevent="addGroup"
          />
          <button
            class="office-btn w-full"
            :disabled="savingGroup || !newGroup.trim()"
            @click="addGroup"
          >افزودن ستون</button>
        </section>
      </div>

      <TaskForm v-if="editing" :task="editing" @close="editing = null" @saved="onSaved" />
    </template>
  </div>
</template>
