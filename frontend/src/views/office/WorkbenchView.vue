<script setup lang="ts">
/**
 * میز کار — «حالا چه کنم», answered above the fold.
 *
 * The first version was five identical grey boxes with numbers in them, which
 * is a scoreboard, not a desk. What changed:
 *
 * **The tiles carry meaning, not just counts.** Each one has the colour of
 * the section it opens and a line saying what the number is, so «۳» reads as
 * «سه کار امروز» without a legend.
 *
 * **Late is the only thing that shouts.** Everything else is quiet on
 * purpose; a page where five numbers are all red has no signal in it.
 *
 * **The module cards are gone.** They duplicated the rail sitting two
 * centimetres to the right. The space went to the two lists people actually
 * work from.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { workApi, type Workbench } from "@/api/officeWork";
import { useAuthStore } from "@/stores/auth";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import { OFFICE_SECTIONS } from "@/components/office/sections";
import TaskForm from "@/components/office/TaskForm.vue";
import NavIcon from "@/components/NavIcon.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

const router = useRouter();
const auth = useAuthStore();

const data = ref<Workbench | null>(null);
const loading = ref(true);
const error = ref("");
const creating = ref(false);

const colorOf = (name: string) =>
  OFFICE_SECTIONS.find((s) => s.name === name)?.color ?? "#64748b";

/** Each tile: where it goes, what it looks like, and what the number means. */
const TILE: Record<string, { to: string; icon: string; note: string }> = {
  today: { to: "office-tasks", icon: "check", note: "کاری که امروز سررسید دارد" },
  overdue: { to: "office-tasks", icon: "activity", note: "از مهلتش گذشته" },
  others: { to: "office-tasks", icon: "team", note: "به دیگران سپرده‌اید" },
  letters: { to: "office-letters", icon: "inbox", note: "نامه‌ی باز نشده" },
  messages: { to: "chat", icon: "chat", note: "پیام خوانده نشده" },
};

const greeting = computed(() => {
  const h = new Date().getHours();
  if (h < 12) return "صبح بخیر";
  if (h < 17) return "ظهر بخیر";
  return "عصر بخیر";
});

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

/** Only «دارای تاخیر» is allowed to be loud. */
function tileTone(key: string, value: number): boolean {
  return key === "overdue" && value > 0;
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-28 rounded-card" />
      <Skeleton class="h-56 rounded-card" />
    </div>

    <p v-else-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3">
      {{ error }}
    </p>

    <template v-else-if="data">
      <!-- Greeting + the five numbers -->
      <div class="bg-surface rounded-card shadow-soft p-4 sm:p-5">
        <div class="flex flex-wrap items-baseline justify-between gap-2 mb-4">
          <h2 class="text-lg font-bold text-ink">
            {{ greeting }}، {{ auth.me?.display_name_fa || auth.me?.username }}
          </h2>
          <button
            class="text-white rounded-xl px-4 py-2 text-sm"
            :style="{ background: 'var(--sec)' }"
            @click="creating = true"
          >+ وظیفه جدید</button>
        </div>

        <div class="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <button
            v-for="t in data.tiles" :key="t.key"
            class="rounded-2xl p-3.5 text-right transition hover:-translate-y-0.5"
            :class="tileTone(t.key, t.value) ? 'bg-red-50' : 'bg-slate-50 hover:bg-slate-100'"
            @click="router.push({ name: TILE[t.key]?.to ?? 'office-tasks' })"
          >
            <span class="flex items-center gap-2">
              <span
                class="w-7 h-7 rounded-lg grid place-items-center text-white shrink-0"
                :style="{ background: tileTone(t.key, t.value)
                  ? '#ef4444'
                  : colorOf(TILE[t.key]?.to ?? 'office-tasks') }"
              >
                <NavIcon :name="TILE[t.key]?.icon ?? 'check'" :size="15" />
              </span>
              <span
                class="text-2xl font-bold ltr-nums"
                :class="tileTone(t.key, t.value) ? 'text-red-600' : 'text-ink'"
              >{{ num(t.value) }}</span>
            </span>
            <span class="block text-xs text-slate-500 mt-2">{{ t.label }}</span>
            <span class="block text-[10px] text-slate-400">{{ TILE[t.key]?.note }}</span>
          </button>
        </div>
      </div>

      <!-- The two lists people actually work from -->
      <div class="grid lg:grid-cols-2 gap-4">
        <div class="bg-surface rounded-card shadow-soft overflow-hidden flex flex-col">
          <div class="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <h3 class="font-bold text-ink text-sm">کارهای من</h3>
            <button
              class="text-xs text-slate-400 hover:text-ink"
              @click="router.push({ name: 'office-tasks' })"
            >همه</button>
          </div>

          <EmptyState
            v-if="!data.my_tasks.length"
            title="کاری برای انجام ندارید"
            hint="با «+ وظیفه جدید» اولین کار را ثبت کنید."
          />

          <div v-else class="divide-y divide-slate-100 overflow-y-auto max-h-[22rem]">
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
                :class="t.is_overdue ? 'text-red-600 font-medium' : 'text-slate-400'"
              >{{ faDate(t.due_on) }}</span>
            </div>
          </div>
        </div>

        <div class="bg-surface rounded-card shadow-soft overflow-hidden flex flex-col">
          <div class="px-4 py-3 border-b border-slate-100">
            <h3 class="font-bold text-ink text-sm">پیگیری از دیگران</h3>
            <p class="text-xs text-slate-400 mt-0.5">
              سپرده‌اید و هنوز انجام نشده
            </p>
          </div>

          <EmptyState v-if="!data.following.length" title="چیزی در انتظار دیگران نیست" />

          <div v-else class="divide-y divide-slate-100 overflow-y-auto max-h-[22rem]">
            <button
              v-for="t in data.following" :key="t.id"
              class="w-full text-right px-4 py-2.5 flex items-center gap-3 hover:bg-slate-50"
              @click="router.push({ name: 'office-tasks' })"
            >
              <UserAvatar
                v-if="t.assignee_detail"
                :user="t.assignee_detail as any" :size="28" class="shrink-0"
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
                :class="t.is_overdue ? 'text-red-600 font-medium' : 'text-slate-400'"
              >{{ faDate(t.due_on) }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Projects, with the one number that matters per card -->
      <div v-if="data.projects.length" class="bg-surface rounded-card shadow-soft p-4">
        <div class="flex items-baseline justify-between mb-3">
          <h3 class="font-bold text-ink text-sm">پروژه‌های در جریان</h3>
          <button
            class="text-xs text-slate-400 hover:text-ink"
            @click="router.push({ name: 'office-projects' })"
          >همه</button>
        </div>
        <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <button
            v-for="p in data.projects" :key="p.id"
            class="bg-slate-50 hover:bg-slate-100 rounded-2xl p-3 text-right transition-colors"
            @click="router.push({ name: 'office-project', params: { id: p.id } })"
          >
            <p class="text-sm font-medium text-ink truncate">{{ p.name }}</p>
            <div class="h-1.5 bg-slate-200 rounded-full overflow-hidden mt-2">
              <div
                class="h-full rounded-full"
                :style="{
                  width: `${Math.max(p.progress_pct, 2)}%`,
                  background: p.overdue_count ? '#f59e0b' : colorOf('office-projects'),
                }"
              ></div>
            </div>
            <p class="text-[11px] text-slate-400 mt-1.5 ltr-nums">
              {{ num(p.done_count) }}/{{ num(p.task_count) }}
              <span v-if="p.my_open_count"> · {{ num(p.my_open_count) }} کار من</span>
              <span v-if="p.overdue_count" class="text-amber-600">
                · {{ num(p.overdue_count) }} عقب‌افتاده
              </span>
            </p>
          </button>
        </div>
      </div>

      <TaskForm v-if="creating" @close="creating = false" @saved="creating = false; load()" />
    </template>
  </div>
</template>
