<script setup lang="ts">
/** یک پروژه: اعضا، پیشرفت، و وظایفش به تفکیک دسته. */
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { workApi, type Project, type Task } from "@/api/officeWork";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import TaskForm from "@/components/office/TaskForm.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";

const route = useRoute();
const router = useRouter();

const project = ref<Project | null>(null);
const groups = ref<{ id: number; name: string; tasks: Task[] }[]>([]);
const ungrouped = ref<Task[]>([]);
const loading = ref(true);
const error = ref("");
const creating = ref(false);
const editing = ref<Task | null>(null);

async function load() {
  loading.value = true;
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

async function toggle(task: Task) {
  try {
    await workApi.toggleTask(task.id);
    await load();
  } catch (e) {
    error.value = apiError(e);
  }
}

function onSaved() {
  creating.value = false;
  editing.value = null;
  load();
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-28 rounded-card" />
      <Skeleton class="h-64 rounded-card" />
    </div>

    <p v-else-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3">
      {{ error }}
    </p>

    <template v-else-if="project">
      <div class="bg-surface rounded-card shadow-soft p-4 sm:p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <h2 class="text-lg font-bold text-ink">{{ project.name }}</h2>
            <p v-if="project.description" class="text-sm text-slate-500 mt-1">
              {{ project.description }}
            </p>
          </div>
          <button
            class="text-sm text-slate-500 hover:text-ink px-2 py-2 shrink-0"
            @click="router.push({ name: 'office-projects' })"
          >← بازگشت</button>
        </div>

        <div class="mt-4">
          <div class="flex items-baseline justify-between text-xs mb-1">
            <span class="text-slate-500">وضعیت کل پروژه</span>
            <span class="text-ink ltr-nums">
              {{ num(project.progress_pct) }}٪ —
              {{ num(project.done_count) }} از {{ num(project.task_count) }}
            </span>
          </div>
          <div class="h-2.5 bg-slate-100 rounded-full overflow-hidden">
            <div
              class="h-full rounded-full bg-panel transition-all"
              :style="{ width: `${Math.max(project.progress_pct, 1)}%` }"
            ></div>
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-3 mt-4">
          <div class="flex -space-x-2 space-x-reverse">
            <UserAvatar
              v-for="m in project.memberships" :key="m.id"
              :user="m.user_detail as any" :size="28" :title="`${m.user_detail.name} — ${m.role_label}`"
              class="ring-2 ring-surface rounded-full"
            />
          </div>
          <span v-if="project.due_on" class="text-xs text-slate-400 ltr-nums">
            مهلت {{ faDate(project.due_on) }}
          </span>
          <span v-if="project.overdue_count" class="text-xs text-amber-600 ltr-nums">
            {{ num(project.overdue_count) }} کار عقب‌افتاده
          </span>
          <span class="flex-1"></span>
          <button
            class="bg-panel text-white rounded-xl px-4 py-2 text-sm"
            @click="creating = true"
          >+ وظیفه</button>
        </div>
      </div>

      <div
        v-for="section in [...groups, { id: 0, name: 'بدون دسته‌بندی', tasks: ungrouped }]"
        :key="section.id"
        v-show="section.tasks.length"
        class="bg-surface rounded-card shadow-soft overflow-hidden"
      >
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          {{ section.name }}
          <span class="text-slate-400 font-normal ltr-nums">
            ({{ num(section.tasks.length) }})
          </span>
        </h3>
        <div class="divide-y divide-slate-100">
          <div
            v-for="task in section.tasks" :key="task.id"
            class="px-4 py-2.5 flex items-center gap-3 hover:bg-slate-50"
          >
            <button
              class="w-5 h-5 rounded-md border-2 shrink-0 grid place-items-center"
              :class="task.done_at
                ? 'bg-emerald-500 border-emerald-500 text-white'
                : 'border-slate-300 hover:border-slate-400'"
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
            </button>
            <span
              v-if="task.due_on"
              class="text-xs ltr-nums shrink-0"
              :class="task.is_overdue ? 'text-red-600' : 'text-slate-400'"
            >{{ faDate(task.due_on) }}</span>
            <UserAvatar
              v-if="task.assignee_detail"
              :user="task.assignee_detail as any" :size="24"
              :title="task.assignee_detail.name" class="shrink-0"
            />
          </div>
        </div>
      </div>

      <p
        v-if="!groups.length && !ungrouped.length"
        class="text-sm text-slate-400 text-center py-8"
      >هنوز وظیفه‌ای در این پروژه نیست.</p>

      <TaskForm
        v-if="creating" :project-id="project.id"
        @close="creating = false" @saved="onSaved"
      />
      <TaskForm v-if="editing" :task="editing" @close="editing = null" @saved="onSaved" />
    </template>
  </div>
</template>
