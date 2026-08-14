<script setup lang="ts">
/**
 * میزکار — the first page of اتوماسیون اداری.
 *
 * It answers «حالا چه کنم», which is a different question from «چطور پیش
 * رفتیم» and needs a different page. The five tiles are counts you can act
 * on, and under them the two lists a person actually works from: what is
 * mine, and what I am waiting on from somebody else.
 *
 * Unlike the CRM workbench that was removed, this one has live data behind
 * it: tasks and letters are created here, today, by the people looking at it
 * — not imported from a sixteen-month-old export where every row is equally
 * late.
 */
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { workApi, type Workbench } from "@/api/officeWork";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import TaskForm from "@/components/office/TaskForm.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

const router = useRouter();

const data = ref<Workbench | null>(null);
const loading = ref(true);
const error = ref("");
const creating = ref(false);

/** Where each tile goes when clicked. A number you cannot open is a poster. */
const TILE_ROUTE: Record<string, { name: string; query?: Record<string, string> }> = {
  today: { name: "office-tasks" },
  overdue: { name: "office-tasks" },
  others: { name: "office-tasks" },
  letters: { name: "office-letters" },
  messages: { name: "chat" },
};

async function load() {
  loading.value = true;
  try {
    data.value = await workApi.workbench();
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function toggle(id: number) {
  await workApi.toggleTask(id);
  await load();
}

const MODULES = [
  { name: "office-letters", label: "مکاتبات", hint: "نامه‌ها، پاراف و ارجاع" },
  { name: "office-tasks", label: "وظایف", hint: "کارهای من و پیگیری از دیگران" },
  { name: "office-projects", label: "پروژه‌ها", hint: "کارهای گروهی و پیشرفتشان" },
  { name: "chat", label: "گفتگو", hint: "پیام مستقیم و گروهی" },
];
</script>

<template>
  <div class="space-y-5">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-24 rounded-card" />
      <Skeleton class="h-56 rounded-card" />
    </div>

    <p v-else-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3">
      {{ error }}
    </p>

    <template v-else-if="data">
      <div class="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <button
          v-for="t in data.tiles" :key="t.key"
          class="bg-surface rounded-card shadow-soft p-4 text-right transition
                 hover:shadow-pop hover:-translate-y-0.5"
          @click="router.push(TILE_ROUTE[t.key] ?? { name: 'office-tasks' })"
        >
          <p class="text-xs text-slate-500">{{ t.label }}</p>
          <p
            class="text-2xl font-bold mt-1 ltr-nums"
            :class="t.tone === 'warn' && t.value ? 'text-amber-600' : 'text-ink'"
          >{{ num(t.value) }}</p>
        </button>
      </div>

      <div class="grid lg:grid-cols-2 gap-4">
        <div class="bg-surface rounded-card shadow-soft overflow-hidden">
          <div class="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <h3 class="font-bold text-ink text-sm">کارهای من</h3>
            <button
              class="text-xs text-slate-500 hover:text-ink"
              @click="creating = true"
            >+ وظیفه</button>
          </div>

          <EmptyState
            v-if="!data.my_tasks.length"
            title="کاری برای انجام ندارید"
            hint="با «+ وظیفه» اولین کار را ثبت کنید."
          />

          <div v-else class="divide-y divide-slate-100 max-h-[24rem] overflow-y-auto">
            <div
              v-for="t in data.my_tasks" :key="t.id"
              class="px-4 py-2.5 flex items-center gap-3 hover:bg-slate-50"
            >
              <button
                class="w-5 h-5 rounded-md border-2 border-slate-300 hover:border-slate-400 shrink-0"
                aria-label="انجام شد"
                @click="toggle(t.id)"
              ></button>
              <button
                class="min-w-0 flex-1 text-right"
                @click="router.push({ name: 'office-tasks' })"
              >
                <span class="block text-sm text-ink truncate">{{ t.title }}</span>
                <span v-if="t.project_name" class="block text-xs text-slate-400 truncate">
                  {{ t.project_name }}
                </span>
              </button>
              <span
                v-if="t.due_on"
                class="text-xs shrink-0 ltr-nums"
                :class="t.is_overdue ? 'text-red-600' : 'text-slate-400'"
              >{{ faDate(t.due_on) }}</span>
            </div>
          </div>
        </div>

        <div class="bg-surface rounded-card shadow-soft overflow-hidden">
          <div class="px-4 py-3 border-b border-slate-100">
            <h3 class="font-bold text-ink text-sm">پیگیری از دیگران</h3>
            <p class="text-xs text-slate-400 mt-0.5">
              کارهایی که سپرده‌اید و هنوز انجام نشده
            </p>
          </div>

          <EmptyState v-if="!data.following.length" title="چیزی در انتظار دیگران نیست" />

          <div v-else class="divide-y divide-slate-100 max-h-[24rem] overflow-y-auto">
            <button
              v-for="t in data.following" :key="t.id"
              class="w-full text-right px-4 py-2.5 flex items-center gap-3 hover:bg-slate-50"
              @click="router.push({ name: 'office-tasks' })"
            >
              <UserAvatar
                v-if="t.assignee_detail"
                :user="t.assignee_detail as any" :size="26" class="shrink-0"
              />
              <span class="min-w-0 flex-1">
                <span class="block text-sm text-ink truncate">{{ t.title }}</span>
                <span class="block text-xs text-slate-400 truncate">
                  {{ t.assignee_detail?.name }}
                </span>
              </span>
              <span
                v-if="t.due_on"
                class="text-xs shrink-0 ltr-nums"
                :class="t.is_overdue ? 'text-red-600' : 'text-slate-400'"
              >{{ faDate(t.due_on) }}</span>
            </button>
          </div>
        </div>
      </div>

      <div v-if="data.projects.length">
        <p class="text-xs text-slate-400 px-1 mb-2">پروژه‌های در جریان</p>
        <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <button
            v-for="p in data.projects" :key="p.id"
            class="bg-surface rounded-card shadow-soft p-4 text-right hover:shadow-pop transition-shadow"
            @click="router.push({ name: 'office-project', params: { id: p.id } })"
          >
            <p class="text-sm font-medium text-ink truncate">{{ p.name }}</p>
            <div class="h-1.5 bg-slate-100 rounded-full overflow-hidden mt-2">
              <div
                class="h-full rounded-full bg-panel"
                :style="{ width: `${Math.max(p.progress_pct, 1)}%` }"
              ></div>
            </div>
            <p class="text-[11px] text-slate-400 mt-1 ltr-nums">
              {{ num(p.done_count) }} از {{ num(p.task_count) }} ·
              {{ num(p.my_open_count) }} کار من
            </p>
          </button>
        </div>
      </div>

      <div>
        <p class="text-xs text-slate-400 px-1 mb-2">بخش‌ها</p>
        <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <button
            v-for="m in MODULES" :key="m.name"
            class="bg-surface rounded-card shadow-soft p-4 text-right hover:shadow-pop transition-shadow"
            @click="router.push({ name: m.name })"
          >
            <span class="block font-medium text-ink text-sm">{{ m.label }}</span>
            <span class="block text-xs text-slate-400 mt-0.5">{{ m.hint }}</span>
          </button>
        </div>
      </div>

      <TaskForm v-if="creating" @close="creating = false" @saved="creating = false; load()" />
    </template>
  </div>
</template>
