<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { crmApi, type Deal } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num, pct, rial } from "@/utils/format";
import CrmFilterBar from "@/components/crm/CrmFilterBar.vue";
import DealForm from "@/components/crm/DealForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/** معاملات — the flat, filterable list with a reconciling totals strip. */
const crm = useCrmStore();
const router = useRouter();

const rows = ref<Deal[]>([]);
const total = ref(0);
const summary = ref<any>(null);
const loading = ref(true);
const search = ref("");
const status = ref("won");
const page = ref(1);
const PAGE_SIZE = 30;

const params = computed(() => ({
  ...crm.query,
  status: status.value,
  // Open deals are dated by when they were created; closed ones by when they
  // closed. Without this, "جاری" would filter on a date they do not have.
  date_basis: status.value === "open" ? "opened" : status.value === "" ? "opened" : "closed",
  search: search.value,
}));

async function load() {
  loading.value = true;
  try {
    const [res, sum] = await Promise.all([
      crmApi.deals({ ...params.value, page: page.value, page_size: PAGE_SIZE }),
      crmApi.dealSummary(params.value),
    ]);
    rows.value = res.results;
    total.value = res.count;
    summary.value = sum;
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await crm.loadOptions(); await load(); });
watch(() => crm.query, () => { page.value = 1; load(); }, { deep: true });
watch(status, () => { page.value = 1; load(); });
watch(page, load);

let t: number | undefined;
watch(search, () => { window.clearTimeout(t); t = window.setTimeout(() => { page.value = 1; load(); }, 350); });

const pages = computed(() => Math.max(Math.ceil(total.value / PAGE_SIZE), 1));

const showForm = ref(false);
function onSaved(id: number) {
  showForm.value = false;
  if (id) router.push({ name: "crm-deal", params: { id } });
  else load();
}

const TABS = [
  { key: "won", label: "موفق" },
  { key: "open", label: "جاری" },
  { key: "lost", label: "ناموفق" },
  { key: "", label: "همه" },
];
const statusClass: Record<string, string> = {
  won: "bg-emerald-100 text-emerald-700",
  lost: "bg-red-100 text-red-600",
  open: "bg-amber-100 text-amber-700",
};
</script>

<template>
  <div class="space-y-4">
    <CrmFilterBar />

    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <div class="flex rounded-xl bg-slate-100 p-0.5">
        <button
          v-for="t2 in TABS" :key="t2.key"
          class="text-xs px-3 py-1.5 rounded-lg transition"
          :class="status === t2.key ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-400'"
          @click="status = t2.key"
        >{{ t2.label }}</button>
      </div>
      <input
        v-model="search" placeholder="جستجوی معامله یا مشتری…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 flex-1 min-w-[180px]"
      />
      <button
        v-if="crm.canEdit"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm shrink-0"
        @click="showForm = true"
      >+ فرصت فروش جدید</button>
    </div>

    <DealForm v-if="showForm" @close="showForm = false" @saved="onSaved" />

    <!-- Totals -->
    <div v-if="summary" class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-400">تعداد</p><p class="text-lg font-bold text-ink mt-1">{{ num(summary.count) }}</p></div>
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-400">مبلغ</p><p class="text-lg font-bold text-ink mt-1">{{ rial(summary.amount) }}</p></div>
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-400">سود</p><p class="text-lg font-bold text-emerald-600 mt-1">{{ rial(summary.profit) }}</p></div>
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-400">حاشیه سود</p><p class="text-lg font-bold text-ink mt-1">{{ pct(summary.margin_pct) }}</p></div>
    </div>

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 10" :key="i" class="h-12 rounded-xl" />
    </div>

    <EmptyState v-else-if="!rows.length" title="معامله‌ای در این بازه نیست" />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[820px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-3">معامله</th>
              <th class="text-right font-medium px-3">کارشناس</th>
              <th class="text-right font-medium px-3">مرحله</th>
              <th class="text-right font-medium px-3">وضعیت</th>
              <th class="text-left font-medium px-3">مبلغ</th>
              <th class="text-left font-medium px-3">سود</th>
              <th class="text-left font-medium px-3">حاشیه</th>
              <th class="text-right font-medium px-4">تاریخ</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="d in rows" :key="d.id"
              class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
              @click="router.push({ name: 'crm-deal', params: { id: d.id } })"
            >
              <td class="px-4 py-2.5">
                <p class="text-ink font-medium truncate max-w-[280px]">{{ d.title }}</p>
                <p class="text-xs text-slate-400">{{ d.customer_name }} · {{ d.province_name }}</p>
              </td>
              <td class="px-3 text-slate-500">{{ d.owner_name }}</td>
              <td class="px-3 text-slate-500 text-xs">{{ d.stage_name }}</td>
              <td class="px-3">
                <span class="text-[11px] rounded-full px-2 py-0.5" :class="statusClass[d.status]">{{ d.status_display }}</span>
                <span v-if="d.reason_name" class="text-[10px] text-red-400 block mt-0.5">{{ d.reason_name }}</span>
              </td>
              <td class="px-3 text-left text-ink whitespace-nowrap">{{ rial(d.amount_rial) }}</td>
              <td class="px-3 text-left whitespace-nowrap" :class="Number(d.profit_rial) >= 0 ? 'text-emerald-600' : 'text-red-500'">{{ rial(d.profit_rial) }}</td>
              <td class="px-3 text-left" :class="d.margin_pct >= 20 ? 'text-emerald-600' : d.margin_pct >= 10 ? 'text-amber-600' : 'text-red-500'">{{ pct(d.margin_pct) }}</td>
              <td class="px-4 text-xs text-slate-400 whitespace-nowrap">{{ d.closed_jalali || d.opened_jalali }}</td>
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
  </div>
</template>
