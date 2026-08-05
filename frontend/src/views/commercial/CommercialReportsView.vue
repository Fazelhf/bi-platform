<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  commercialApi,
  type Material,
  type PriceIncreaseRow,
  type PurchaseReport,
  type Supplier,
  type SupplierStats,
} from "@/api/commercial";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import SeriesChart from "@/components/charts/SeriesChart.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/** گزارش‌های بازرگانی: خرید، تحلیل تامین‌کنندگان، افزایش قیمت. */
const router = useRouter();
const { exact, toUnit, unitLabel } = useMoney();

type Tab = "purchases" | "suppliers" | "prices";
const tab = ref<Tab>("purchases");

const TABS: { key: Tab; label: string }[] = [
  { key: "purchases", label: "گزارش خرید" },
  { key: "suppliers", label: "تحلیل تامین‌کنندگان" },
  { key: "prices", label: "افزایش قیمت" },
];

const report = ref<PurchaseReport | null>(null);
const suppliersStats = ref<SupplierStats[]>([]);
const increases = ref<PriceIncreaseRow[]>([]);
const materials = ref<Material[]>([]);
const suppliers = ref<Supplier[]>([]);
const loading = ref(true);
const error = ref("");

const FA = new Intl.NumberFormat("fa-IR");

const filters = ref({
  material: "" as number | "",
  supplier: "" as number | "",
  status: "",
  from: "",
  to: "",
});

async function loadReport() {
  loading.value = true;
  error.value = "";
  try {
    const params: Record<string, unknown> = {};
    if (filters.value.material !== "") params.material = filters.value.material;
    if (filters.value.supplier !== "") params.supplier = filters.value.supplier;
    if (filters.value.status) params.status = filters.value.status;
    if (filters.value.from) params.from = filters.value.from;
    if (filters.value.to) params.to = filters.value.to;
    report.value = await commercialApi.purchaseReport(params);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  await loadMoneySettings();
  [materials.value, suppliers.value] = await Promise.all([
    commercialApi.materials(),
    commercialApi.suppliers(),
  ]);
  await loadReport();
});

watch(tab, async (next) => {
  if (next === "suppliers" && !suppliersStats.value.length) {
    loading.value = true;
    try {
      suppliersStats.value = await commercialApi.supplierReport();
    } finally {
      loading.value = false;
    }
  }
  if (next === "prices" && !increases.value.length) {
    loading.value = true;
    try {
      increases.value = await commercialApi.priceIncreases();
    } finally {
      loading.value = false;
    }
  }
});

const materialChart = computed(() => {
  const rows = (report.value?.by_material ?? []).slice(0, 10);
  return {
    categories: rows.map((r) => r.name),
    series: [{
      name: `مبلغ خرید (${unitLabel.value})`,
      values: rows.map((r) => toUnit(r.amount_rial)),
    }],
  };
});

const supplierChart = computed(() => {
  const rows = (report.value?.by_supplier ?? []).slice(0, 10);
  return {
    categories: rows.map((r) => r.name),
    series: [{
      name: `مبلغ خرید (${unitLabel.value})`,
      values: rows.map((r) => toUnit(r.amount_rial)),
    }],
  };
});

const inp =
  "bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-2 flex gap-1">
      <button
        v-for="t in TABS" :key="t.key"
        class="px-4 py-2 rounded-xl text-sm transition-colors"
        :class="tab === t.key ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
        @click="tab = t.key"
      >{{ t.label }}</button>
    </div>

    <p
      v-if="error"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line"
    >{{ error }}</p>

    <!-- گزارش خرید -->
    <template v-if="tab === 'purchases'">
      <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
        <select v-model="filters.material" :class="inp">
          <option value="">همه کالاها</option>
          <option v-for="m in materials" :key="m.id" :value="m.id">{{ m.name_fa }}</option>
        </select>
        <select v-model="filters.supplier" :class="inp">
          <option value="">همه تامین‌کنندگان</option>
          <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.name_fa }}</option>
        </select>
        <select v-model="filters.status" :class="inp">
          <option value="">همه وضعیت‌ها</option>
          <option value="pending">در انتظار تایید</option>
          <option value="buying">در حال خرید</option>
          <option value="shipped">ارسال شده</option>
          <option value="delivered">تحویل شد</option>
          <option value="cancelled">لغو شد</option>
        </select>
        <input v-model="filters.from" type="date" :class="inp" dir="ltr" />
        <input v-model="filters.to" type="date" :class="inp" dir="ltr" />
        <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm" @click="loadReport">
          اعمال فیلتر
        </button>
      </div>

      <div v-if="loading" class="space-y-2">
        <Skeleton v-for="i in 6" :key="i" class="h-12 rounded-xl" />
      </div>

      <template v-else-if="report">
        <div class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap gap-6">
          <div>
            <p class="text-xs text-slate-400">جمع خرید</p>
            <p class="text-xl font-bold text-ink ltr-nums">
              {{ exact(report.totals.amount_rial, true) }}
            </p>
          </div>
          <div>
            <p class="text-xs text-slate-400">تعداد سفارش</p>
            <p class="text-xl font-bold text-ink ltr-nums">
              {{ num(report.totals.order_count) }}
            </p>
          </div>
          <div v-if="report.totals.cancelled_count">
            <p class="text-xs text-slate-400">لغوشده (خارج از جمع)</p>
            <p class="text-xl font-bold text-slate-400 ltr-nums">
              {{ num(report.totals.cancelled_count) }}
            </p>
          </div>
        </div>

        <div v-if="materialChart.categories.length" class="grid md:grid-cols-2 gap-3">
          <div class="bg-surface rounded-card shadow-soft p-4">
            <SeriesChart
              title="بیشترین کالاهای خریداری‌شده"
              :categories="materialChart.categories"
              :series="materialChart.series"
              :height="240"
            />
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <SeriesChart
              title="بیشترین تامین‌کنندگان"
              :categories="supplierChart.categories"
              :series="supplierChart.series"
              :height="240"
            />
          </div>
        </div>

        <EmptyState v-if="!report.rows.length" title="سفارشی با این فیلترها پیدا نشد" />

        <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
          <div class="overflow-x-auto">
            <table class="w-full text-sm min-w-[900px]">
              <thead>
                <tr class="text-xs text-slate-400 bg-slate-50">
                  <th class="text-right font-medium px-4 py-3">شماره</th>
                  <th class="text-right font-medium px-3">کالا</th>
                  <th class="text-right font-medium px-3">تامین‌کننده</th>
                  <th class="text-right font-medium px-3">تعداد</th>
                  <th class="text-right font-medium px-3">قیمت واحد</th>
                  <th class="text-right font-medium px-3">مبلغ کل</th>
                  <th class="text-right font-medium px-3">تاریخ</th>
                  <th class="text-right font-medium px-4">وضعیت</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="r in report.rows" :key="r.id"
                  class="border-t border-slate-100 hover:bg-slate-50"
                  :class="{ 'opacity-50': r.status === 'cancelled' }"
                >
                  <td class="px-4 py-2.5 ltr-nums text-ink font-medium">{{ r.order_no }}</td>
                  <td class="px-3 text-ink">{{ r.material }}</td>
                  <td class="px-3 text-slate-500">{{ r.supplier }}</td>
                  <td class="px-3 ltr-nums text-slate-500">
                    {{ num(r.quantity) }} {{ r.unit_label }}
                  </td>
                  <td class="px-3 ltr-nums text-slate-500">{{ exact(r.unit_price_rial) }}</td>
                  <td class="px-3 ltr-nums text-ink">{{ exact(r.total_rial) }}</td>
                  <td class="px-3 text-xs text-slate-500 ltr-nums">{{ faDate(r.ordered_on) }}</td>
                  <td class="px-4 text-xs text-slate-500">{{ r.status_label }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </template>

    <!-- تحلیل تامین‌کنندگان -->
    <template v-else-if="tab === 'suppliers'">
      <div v-if="loading" class="space-y-2">
        <Skeleton v-for="i in 6" :key="i" class="h-12 rounded-xl" />
      </div>
      <EmptyState v-else-if="!suppliersStats.length" title="هنوز تامین‌کننده‌ای ثبت نشده" />
      <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
        <div class="px-4 py-2 text-xs text-slate-400 border-b border-slate-100">
          مبالغ به {{ unitLabel }} · مرتب بر اساس جمع خرید
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[960px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">تامین‌کننده</th>
                <th class="text-right font-medium px-3">استعلام</th>
                <th class="text-right font-medium px-3">برد</th>
                <th class="text-right font-medium px-3">درصد برد</th>
                <th class="text-right font-medium px-3">میانگین قیمت</th>
                <th class="text-right font-medium px-3">میانگین تحویل</th>
                <th class="text-right font-medium px-3">سفارش</th>
                <th class="text-right font-medium px-4">جمع خرید</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="s in suppliersStats" :key="s.id"
                class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                @click="router.push({ name: 'commercial-supplier', params: { id: s.id } })"
              >
                <td class="px-4 py-2.5 text-ink font-medium">
                  {{ s.name }}
                  <span v-if="!s.is_active" class="text-xs text-slate-400">(غیرفعال)</span>
                </td>
                <td class="px-3 ltr-nums text-slate-500">{{ num(s.quote_count) }}</td>
                <td class="px-3 ltr-nums text-slate-500">{{ num(s.win_count) }}</td>
                <td class="px-3 ltr-nums">
                  <span v-if="s.win_rate_pct === null" class="text-slate-300">—</span>
                  <span
                    v-else
                    :class="s.win_rate_pct >= 50 ? 'text-emerald-600' : 'text-slate-500'"
                  >{{ FA.format(s.win_rate_pct) }}٪</span>
                </td>
                <td class="px-3 ltr-nums text-slate-500">
                  {{ exact(s.avg_quote_price_rial) }}
                </td>
                <td class="px-3 ltr-nums text-slate-500">
                  <span v-if="s.avg_actual_days !== null">
                    {{ FA.format(s.avg_actual_days) }} روز
                  </span>
                  <span v-else-if="s.avg_promised_days !== null" class="text-slate-400">
                    {{ FA.format(s.avg_promised_days) }} روز (قول)
                  </span>
                  <span v-else class="text-slate-300">—</span>
                </td>
                <td class="px-3 ltr-nums text-slate-500">{{ num(s.order_count) }}</td>
                <td class="px-4 ltr-nums text-ink font-medium">
                  {{ exact(s.total_spend_rial) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- افزایش قیمت -->
    <template v-else>
      <div v-if="loading" class="space-y-2">
        <Skeleton v-for="i in 6" :key="i" class="h-12 rounded-xl" />
      </div>
      <EmptyState
        v-else-if="!increases.length"
        title="داده‌ای برای مقایسه نیست"
        hint="برای گزارش افزایش قیمت، هر کالا باید دست‌کم در دو ماه خریداری شده باشد."
      />
      <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
        <div class="px-4 py-2 text-xs text-slate-400 border-b border-slate-100">
          مقایسه دو ماه آخری که هر کالا در آن خریداری شده · مبالغ به {{ unitLabel }}
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[760px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">کالا</th>
                <th class="text-right font-medium px-3">ماه قبل</th>
                <th class="text-right font-medium px-3">این ماه</th>
                <th class="text-right font-medium px-4">تغییر</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in increases" :key="r.material_id"
                class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                @click="router.push({ name: 'commercial-material', params: { id: r.material_id } })"
              >
                <td class="px-4 py-2.5 text-ink font-medium">{{ r.material }}</td>
                <td class="px-3 ltr-nums text-slate-500">
                  {{ exact(r.previous_rial) }}
                  <p class="text-xs text-slate-400">{{ r.previous_label }}</p>
                </td>
                <td class="px-3 ltr-nums text-ink">
                  {{ exact(r.latest_rial) }}
                  <p class="text-xs text-slate-400">{{ r.latest_label }}</p>
                </td>
                <td class="px-4 ltr-nums font-medium"
                    :class="r.change_pct > 0 ? 'text-red-500' : 'text-emerald-600'">
                  {{ r.change_pct > 0 ? "▲" : "▼" }}
                  {{ FA.format(Math.abs(Number(r.change_pct.toFixed(1)))) }}٪
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
