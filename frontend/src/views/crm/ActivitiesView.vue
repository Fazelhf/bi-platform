<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { crmApi, type CrmActivity } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num, pct } from "@/utils/format";
import CrmFilterBar from "@/components/crm/CrmFilterBar.vue";
import ActivityForm from "@/components/crm/ActivityForm.vue";
import TaskForm from "@/components/crm/TaskForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/** فعالیت‌ها و کارها — what the team did, and what it still owes customers. */
const crm = useCrmStore();
const route = useRoute();
const router = useRouter();

const tab = ref<"activities" | "tasks">((route.query.tab as any) === "tasks" ? "tasks" : "activities");
const rows = ref<CrmActivity[]>([]);
const tasks = ref<any[]>([]);
const total = ref(0);
const summary = ref<any>(null);
const loading = ref(true);
const kind = ref("");
const result = ref("");
const taskState = ref("open");
const page = ref(1);
const PAGE_SIZE = 30;

async function load() {
  loading.value = true;
  try {
    if (tab.value === "activities") {
      const p = { ...crm.query, kind: kind.value, result: result.value };
      const [res, sum] = await Promise.all([
        crmApi.activities({ ...p, page: page.value, page_size: PAGE_SIZE }),
        crmApi.activitySummary(p),
      ]);
      rows.value = res.results;
      total.value = res.count;
      summary.value = sum;
    } else {
      const res = await crmApi.tasks({
        owner: crm.query.owner, state: taskState.value,
        page: page.value, page_size: PAGE_SIZE,
      });
      tasks.value = res.results;
      total.value = res.count;
      summary.value = null;
    }
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await crm.loadOptions(); await load(); });
watch(() => crm.query, () => { page.value = 1; load(); }, { deep: true });
watch([kind, result, taskState, tab], () => { page.value = 1; load(); });
watch(page, load);

const pages = computed(() => Math.max(Math.ceil(total.value / PAGE_SIZE), 1));

async function complete(id: number) {
  await crmApi.completeTask(id);
  await load();
}

// Entry + editing. Clicking a row opens it; the buttons create new ones.
const modal = ref<"activity" | "task" | null>(null);
const editing = ref<any | null>(null);

function openNew(kind: "activity" | "task") {
  editing.value = null;
  modal.value = kind;
}
function openExisting(kind: "activity" | "task", row: any) {
  editing.value = row;
  modal.value = kind;
}
async function onSaved() {
  modal.value = null;
  editing.value = null;
  await load();
}

const resultClass: Record<string, string> = {
  success: "bg-emerald-100 text-emerald-700",
  no_answer: "bg-slate-200 text-slate-600",
  follow_up: "bg-amber-100 text-amber-700",
  failed: "bg-red-100 text-red-600",
};

function isOverdue(t: any) {
  return !t.done_at && new Date(t.due_at) < new Date();
}
</script>

<template>
  <div class="space-y-4">
    <CrmFilterBar />

    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <div class="flex rounded-xl bg-slate-100 p-0.5">
        <button
          class="text-xs px-3 py-1.5 rounded-lg" :class="tab === 'activities' ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-400'"
          @click="tab = 'activities'"
        >فعالیت‌های انجام شده</button>
        <button
          class="text-xs px-3 py-1.5 rounded-lg" :class="tab === 'tasks' ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-400'"
          @click="tab = 'tasks'"
        >کارها و یادآوری‌ها</button>
      </div>

      <template v-if="tab === 'activities'">
        <select v-model="kind" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
          <option value="">همه فعالیت‌ها</option>
          <option v-for="k in crm.options?.activity_kinds" :key="k.code" :value="k.code">{{ k.label }}</option>
        </select>
        <select v-model="result" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
          <option value="">همه نتایج</option>
          <option v-for="r in crm.options?.activity_results" :key="r.code" :value="r.code">{{ r.label }}</option>
        </select>
      </template>
      <template v-else>
        <select v-model="taskState" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
          <option value="open">باز</option>
          <option value="overdue">عقب‌افتاده</option>
          <option value="done">انجام‌شده</option>
          <option value="">همه</option>
        </select>
      </template>

      <span class="text-xs text-slate-400 px-2">{{ num(total) }} رکورد</span>
      <span class="flex-1"></span>
      <button
        v-if="crm.canEdit"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm shrink-0"
        @click="openNew(tab === 'tasks' ? 'task' : 'activity')"
      >{{ tab === "tasks" ? "+ کار جدید" : "+ ثبت فعالیت" }}</button>
    </div>

    <ActivityForm v-if="modal === 'activity'" :activity="editing" @close="modal = null" @saved="onSaved" />
    <TaskForm v-if="modal === 'task'" :task="editing" @close="modal = null" @saved="onSaved" />

    <div v-if="summary && tab === 'activities'" class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-400">تعداد</p><p class="text-lg font-bold text-ink mt-1">{{ num(summary.count) }}</p></div>
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-400">موفق</p><p class="text-lg font-bold text-emerald-600 mt-1">{{ num(summary.success) }}</p></div>
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-400">نرخ موفقیت</p><p class="text-lg font-bold text-ink mt-1">{{ pct(summary.success_rate) }}</p></div>
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-400">مشتریان درگیر</p><p class="text-lg font-bold text-ink mt-1">{{ num(summary.customers) }}</p></div>
    </div>

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 10" :key="i" class="h-12 rounded-xl" />
    </div>

    <!-- Activities -->
    <template v-else-if="tab === 'activities'">
      <EmptyState v-if="!rows.length" title="فعالیتی در این بازه نیست" />
      <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[700px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">نوع</th>
                <th class="text-right font-medium px-3">مشتری</th>
                <th class="text-right font-medium px-3">کارشناس</th>
                <th class="text-right font-medium px-3">نتیجه</th>
                <th class="text-left font-medium px-3">مدت</th>
                <th class="text-right font-medium px-4">تاریخ</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="a in rows" :key="a.id"
                class="border-t border-slate-100 hover:bg-slate-50"
                :class="crm.canEdit ? 'cursor-pointer' : ''"
                @click="crm.canEdit && openExisting('activity', a)"
              >
                <td class="px-4 py-2.5">
                  <p class="text-ink">{{ a.kind_display }}</p>
                  <p v-if="a.note" class="text-xs text-slate-400">{{ a.note }}</p>
                </td>
                <td class="px-3">
                  <button class="text-slate-600 hover:text-ink hover:underline" @click.stop="router.push({ name: 'crm-customer', params: { id: a.customer } })">
                    {{ a.customer_name }}
                  </button>
                </td>
                <td class="px-3 text-slate-500">{{ a.owner_name }}</td>
                <td class="px-3"><span class="text-[11px] rounded-full px-2 py-0.5" :class="resultClass[a.result]">{{ a.result_display }}</span></td>
                <td class="px-3 text-left text-slate-500">{{ num(a.duration_min) }}′</td>
                <td class="px-4 text-xs text-slate-400 whitespace-nowrap">{{ a.at_jalali }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="pages > 1" class="px-4 py-3 border-t border-slate-100 flex items-center justify-between">
          <button class="text-sm px-3 py-1.5 rounded-lg bg-slate-100 text-slate-600 disabled:opacity-40" :disabled="page <= 1" @click="page--">قبلی</button>
          <span class="text-xs text-slate-400">صفحه {{ num(page) }} از {{ num(pages) }}</span>
          <button class="text-sm px-3 py-1.5 rounded-lg bg-slate-100 text-slate-600 disabled:opacity-40" :disabled="page >= pages" @click="page++">بعدی</button>
        </div>
      </div>
    </template>

    <!-- Tasks -->
    <template v-else>
      <EmptyState v-if="!tasks.length" title="کاری ثبت نشده" />
      <div v-else class="bg-surface rounded-card shadow-soft divide-y divide-slate-100">
        <div
          v-for="t2 in tasks" :key="t2.id"
          class="p-3 flex items-center gap-3 hover:bg-slate-50"
          :class="crm.canEdit ? 'cursor-pointer' : ''"
          @click="crm.canEdit && openExisting('task', t2)"
        >
          <button
            class="w-5 h-5 rounded-full border-2 shrink-0 transition"
            :class="t2.is_done ? 'bg-emerald-500 border-emerald-500' : 'border-slate-300 hover:border-emerald-500'"
            :disabled="t2.is_done"
            :title="t2.is_done ? 'انجام شده' : 'علامت‌گذاری به عنوان انجام‌شده'"
            @click.stop="complete(t2.id)"
          ></button>
          <div class="min-w-0 flex-1">
            <p class="text-sm text-ink" :class="t2.is_done ? 'line-through text-slate-400' : ''">{{ t2.title }}</p>
            <p class="text-xs text-slate-400">
              {{ t2.customer_name }} · {{ t2.owner_name }} · {{ t2.kind_display }}
            </p>
          </div>
          <span
            class="text-xs shrink-0 rounded-full px-2 py-0.5"
            :class="isOverdue(t2) ? 'bg-red-100 text-red-600' : 'bg-slate-100 text-slate-500'"
          >{{ t2.due_jalali }}</span>
        </div>
      </div>
    </template>
  </div>
</template>
