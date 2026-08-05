<script setup lang="ts">
/**
 * 7 · Audit log — every mutation the API has recorded, searchable, filterable
 * by action/model/date, with the before→after diff expanded on demand.
 */
import { computed, onMounted, ref } from "vue";
import { auditApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { toast } from "@/composables/useUi";
import { apiError, faDateTime, faNum } from "@/utils/adminFormat";
import DataTable, { type Column } from "@/components/admin/DataTable.vue";
import Drawer from "@/components/admin/Drawer.vue";
import PageHeader from "@/components/admin/PageHeader.vue";
import StatCard from "@/components/admin/StatCard.vue";
import Badge from "@/components/admin/Badge.vue";

const admin = useAdminStore();

const rows = ref<any[]>([]);
const total = ref(0);
const loading = ref(true);
const summary = ref<Awaited<ReturnType<typeof auditApi.summary>> | null>(null);

const filters = ref({ action: "", model_label: "", days: "30" });
const query = ref({ search: "", ordering: "-created_at", page: 1, page_size: 25 });

const ACTIONS = [
  { value: "", label: "همه عملیات" },
  { value: "create", label: "ایجاد" },
  { value: "update", label: "ویرایش" },
  { value: "delete", label: "حذف" },
  { value: "submit", label: "ارسال برای تایید" },
  { value: "approve", label: "تایید" },
  { value: "reject", label: "رد" },
  { value: "revision", label: "ارسال برای اصلاح" },
  { value: "import", label: "ایمپورت" },
  { value: "formula", label: "تغییر فرمول" },
];
const ACTION_LABEL = Object.fromEntries(ACTIONS.map((a) => [a.value, a.label]));
const TONE: Record<string, any> = {
  create: "good", update: "brand", delete: "bad", approve: "good",
  reject: "bad", revision: "warn", submit: "info", import: "info", formula: "info",
};

const DAY_RANGES = [
  { value: "1", label: "۲۴ ساعت" },
  { value: "7", label: "۷ روز" },
  { value: "30", label: "۳۰ روز" },
  { value: "90", label: "۹۰ روز" },
  { value: "", label: "همه" },
];

const columns: Column[] = [
  { key: "created_at", label: "زمان", type: "datetime", width: "160px" },
  { key: "display_name", label: "کاربر", type: "slot" },
  { key: "action", label: "عملیات", type: "slot", align: "center" },
  { key: "model_label", label: "موجودیت" },
  { key: "object_repr", label: "رکورد" },
  { key: "changes", label: "تغییرات", type: "slot", sortable: false },
];

function params() {
  const out: Record<string, any> = { ...query.value };
  if (filters.value.action) out.action = filters.value.action;
  if (filters.value.model_label) out.model_label = filters.value.model_label;
  if (filters.value.days) out.days = filters.value.days;
  return out;
}

async function load() {
  loading.value = true;
  try {
    const data = await auditApi.list(params());
    rows.value = data.results;
    total.value = data.count;
  } catch (e) {
    toast.error(apiError(e, "بارگذاری رخدادها ناموفق بود."));
  } finally {
    loading.value = false;
  }
}

async function loadSummary() {
  try {
    summary.value = await auditApi.summary(Number(filters.value.days || 365));
  } catch { /* the table is the important part */ }
}

onMounted(() => { load(); loadSummary(); });

function applyFilters() {
  query.value.page = 1;
  load();
  loadSummary();
}

const detail = ref<any | null>(null);
const changeCount = (row: any) => Object.keys(row.changes || {}).length;

const topUsers = computed(() => summary.value?.by_user.slice(0, 5) ?? []);
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      title="گزارش رخدادها"
      description="هر تغییری که از طریق سامانه انجام شده — چه کسی، چه زمانی، چه چیزی، قبل و بعد"
    />

    <div v-if="summary" class="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <StatCard
        label="کل رخدادها در بازه" :value="faNum(summary.total)" icon="history" tone="brand"
      />
      <StatCard
        v-for="a in summary.by_action.slice(0, 3)" :key="a.action"
        :label="ACTION_LABEL[a.action] || a.action"
        :value="faNum(a.n)"
        icon="activity"
      />
    </div>

    <!-- Filters -->
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <select
        v-model="filters.action"
        class="border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface"
        @change="applyFilters"
      >
        <option v-for="a in ACTIONS" :key="a.value" :value="a.value">{{ a.label }}</option>
      </select>
      <select
        v-model="filters.model_label"
        class="border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface min-w-[180px]"
        @change="applyFilters"
      >
        <option value="">همه موجودیت‌ها</option>
        <option v-for="m in summary?.models ?? []" :key="m" :value="m">{{ m }}</option>
      </select>
      <div class="flex bg-slate-100 rounded-xl p-0.5">
        <button
          v-for="d in DAY_RANGES" :key="d.value"
          class="px-2.5 py-1 text-xs rounded-lg transition"
          :class="filters.days === d.value ? 'bg-surface shadow-sm text-ink' : 'text-slate-500'"
          @click="filters.days = d.value; applyFilters()"
        >{{ d.label }}</button>
      </div>
      <div class="flex-1"></div>
      <div v-if="topUsers.length" class="hidden lg:flex items-center gap-1.5 text-xs text-slate-400">
        <span>پرکارترین‌ها:</span>
        <Badge v-for="u in topUsers" :key="u.user" tone="neutral">
          {{ u.name || u.user }} · {{ faNum(u.n) }}
        </Badge>
      </div>
    </div>

    <DataTable
      :columns="columns"
      :rows="rows"
      :loading="loading"
      :client="false"
      :total="total"
      :page-size="25"
      :exportable="admin.can('audit.export')"
      dense
      search-placeholder="جستجو در رکوردها، کاربران، موجودیت‌ها…"
      empty-title="رخدادی با این فیلترها نبود"
      @query="(q) => { query = { ...q, ordering: q.ordering || '-created_at' }; load(); }"
      @refresh="load"
      @export="(f) => auditApi.export(f, { ...params(), page: undefined })"
    >
      <template #cell-display_name="{ row }">
        <span class="text-ink">{{ row.display_name || row.username || "سیستم" }}</span>
      </template>
      <template #cell-action="{ row }">
        <Badge :tone="TONE[row.action] || 'neutral'">{{ ACTION_LABEL[row.action] || row.action }}</Badge>
      </template>
      <template #cell-changes="{ row }">
        <button
          v-if="changeCount(row)"
          class="text-xs text-brand-600 hover:underline"
          @click="detail = row"
        >{{ faNum(changeCount(row)) }} فیلد</button>
        <span v-else class="text-slate-300">—</span>
      </template>
    </DataTable>

    <!-- ============ Diff ============ -->
    <Drawer
      :open="!!detail"
      title="جزئیات تغییر"
      :subtitle="detail ? `${detail.model_label} · ${faDateTime(detail.created_at)}` : ''"
      @close="detail = null"
    >
      <div v-if="detail" class="space-y-4">
        <dl class="grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt class="text-xs text-slate-400">کاربر</dt>
            <dd class="text-ink">{{ detail.display_name || detail.username || "سیستم" }}</dd>
          </div>
          <div>
            <dt class="text-xs text-slate-400">عملیات</dt>
            <dd><Badge :tone="TONE[detail.action] || 'neutral'">{{ ACTION_LABEL[detail.action] || detail.action }}</Badge></dd>
          </div>
          <div>
            <dt class="text-xs text-slate-400">رکورد</dt>
            <dd class="text-ink">{{ detail.object_repr || "—" }}</dd>
          </div>
          <div>
            <dt class="text-xs text-slate-400">شناسه</dt>
            <dd class="text-ink ltr-nums">{{ detail.object_id || "—" }}</dd>
          </div>
        </dl>

        <div class="border border-slate-200 rounded-xl overflow-hidden">
          <table class="w-full text-sm">
            <thead class="bg-slate-50 text-slate-400 text-xs">
              <tr>
                <th class="text-right font-medium px-3 py-2">فیلد</th>
                <th class="text-right font-medium px-3 py-2">قبل</th>
                <th class="text-right font-medium px-3 py-2">بعد</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(change, field) in detail.changes" :key="field"
                class="border-t border-slate-50"
              >
                <td class="px-3 py-2 text-ink">{{ field }}</td>
                <td class="px-3 py-2 text-red-500 break-all">{{ change.before ?? "—" }}</td>
                <td class="px-3 py-2 text-accent-600 break-all">{{ change.after ?? "—" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </Drawer>
  </div>
</template>
