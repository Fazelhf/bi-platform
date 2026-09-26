<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { sales2Api, type Options, type SalesListRow } from "@/api/sales2";
import JalaliDateField from "@/components/JalaliDateField.vue";
import CustomerSearch from "@/components/sales2/CustomerSearch.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import { apiError } from "@/components/crm/formError";
import { faDate } from "@/utils/adminFormat";
import { jalaliToIso, toJalali, todayIso } from "@/utils/jalali";

/**
 * لیست فروش — every issued invoice line in the period, returns negative, with
 * cost and profit beside it. This is the sheet finance reconciles against
 * and, once the formula arrives, what پورسانت will be computed from.
 */
const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));

// The finance month is the Jalali one: «این ماه» starts on the 1st of the
// شمسی month, not of the Gregorian one.
const todayJ = toJalali(new Date());
const firstOfMonth = jalaliToIso({ ...todayJ, jd: 1 });

const options = ref<Options | null>(null);
const filters = ref({
  date_from: firstOfMonth,
  date_to: todayIso(),
  salesperson: "" as string | number,
  customer: null as number | null,
});
const rows = ref<SalesListRow[]>([]);
const totals = ref<Record<string, string>>({});
const bySalesperson = ref<{ name: string; net_rial: string }[]>([]);
const loading = ref(true);
const exporting = ref(false);
const error = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const data = await sales2Api.salesList(filters.value);
    rows.value = data.rows;
    totals.value = data.totals;
    bySalesperson.value = data.by_salesperson;
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

watch(filters, load, { deep: true });
onMounted(async () => {
  options.value = await sales2Api.options();
  await load();
});

async function exportXlsx() {
  exporting.value = true;
  try {
    const blob = await sales2Api.exportSalesList(filters.value);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "لیست-فروش.xlsx";
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    exporting.value = false;
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 grid sm:grid-cols-2 lg:grid-cols-5 gap-2 items-end">
      <div><label class="text-xs text-slate-500 mb-1 block">از تاریخ</label><JalaliDateField v-model="filters.date_from" /></div>
      <div><label class="text-xs text-slate-500 mb-1 block">تا تاریخ</label><JalaliDateField v-model="filters.date_to" /></div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">فروشنده</label>
        <select v-model="filters.salesperson" class="w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
          <option value="">همه</option>
          <option v-for="s in options?.salespeople" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
      </div>
      <div><label class="text-xs text-slate-500 mb-1 block">مشتری</label><CustomerSearch v-model="filters.customer" /></div>
      <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm" :disabled="exporting" @click="exportXlsx">
        {{ exporting ? "در حال ساخت…" : "خروجی اکسل" }}
      </button>
    </div>

    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">{{ error }}</p>

    <div v-if="!loading && rows.length" class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-500">فروش خالص</p><p class="text-xl font-bold ltr-nums mt-1">{{ fa(totals.net_rial) }}</p></div>
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-500">ارزش افزوده</p><p class="text-xl font-bold ltr-nums mt-1">{{ fa(totals.vat_rial) }}</p></div>
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-500">بهای تمام‌شده</p><p class="text-xl font-bold ltr-nums mt-1">{{ fa(totals.cost_rial) }}</p></div>
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-500">سود ناخالص</p><p class="text-xl font-bold ltr-nums mt-1 text-emerald-600">{{ fa(totals.profit_rial) }}</p></div>
    </div>

    <div v-if="!loading && bySalesperson.length" class="bg-surface rounded-card shadow-soft p-4">
      <h2 class="text-sm font-bold text-ink mb-2">به تفکیک فروشنده (مبنای پورسانت)</h2>
      <div class="flex flex-wrap gap-2">
        <span v-for="p in bySalesperson" :key="p.name" class="text-xs bg-slate-100 rounded-lg px-3 py-1.5">
          {{ p.name }}: <b class="ltr-nums">{{ fa(p.net_rial) }}</b>
        </span>
      </div>
    </div>

    <div v-if="loading" class="space-y-2"><Skeleton v-for="i in 8" :key="i" class="h-10 rounded-xl" /></div>
    <EmptyState v-else-if="!rows.length" title="در این بازه فروشی ثبت نشده" />
    <div v-else class="bg-surface rounded-card shadow-soft overflow-x-auto">
      <table class="w-full text-xs min-w-[1100px]">
        <thead>
          <tr class="text-slate-400 bg-slate-50">
            <th class="text-right font-medium px-3 py-2">سند</th><th class="text-right font-medium px-2">تاریخ</th>
            <th class="text-right font-medium px-2">مشتری</th><th class="text-right font-medium px-2">فروشنده</th>
            <th class="text-right font-medium px-2">کالا</th><th class="text-right font-medium px-2">مقدار</th>
            <th class="text-right font-medium px-2">فی</th><th class="text-right font-medium px-2">خالص</th>
            <th class="text-right font-medium px-2">ارزش افزوده</th><th class="text-right font-medium px-2">بها</th>
            <th class="text-right font-medium px-2">سود</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in rows" :key="i" class="border-t border-slate-100" :class="r.kind === 'return' ? 'bg-red-50/40' : ''">
            <td class="px-3 py-1.5 ltr-nums">
              <router-link :to="{ name: 'sales2-document', params: { id: r.doc_id }, query: { kind: r.kind } }" class="text-sky-600">{{ r.number }}</router-link>
            </td>
            <td class="px-2 text-slate-500">{{ faDate(r.doc_date) }}</td>
            <td class="px-2">{{ r.customer }}</td>
            <td class="px-2 text-slate-500">{{ r.salesperson || "—" }}</td>
            <td class="px-2">{{ r.product }}</td>
            <td class="px-2 ltr-nums">{{ FA.format(Number(r.quantity)) }} {{ r.unit }}</td>
            <td class="px-2 ltr-nums">{{ fa(r.unit_price_rial) }}</td>
            <td class="px-2 ltr-nums font-medium">{{ fa(r.net_rial) }}</td>
            <td class="px-2 ltr-nums text-slate-500">{{ fa(r.vat_rial) }}</td>
            <td class="px-2 ltr-nums text-slate-500">{{ fa(r.cost_rial) }}</td>
            <td class="px-2 ltr-nums" :class="Number(r.profit_rial) < 0 ? 'text-red-600' : 'text-emerald-600'">{{ fa(r.profit_rial) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
