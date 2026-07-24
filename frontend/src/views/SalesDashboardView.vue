<script setup lang="ts">
import { defaultPeriodId, type Period } from "@/types";
import { computed, onMounted, ref, watch } from "vue";
import api from "@/api/client";
import { salesApi } from "@/api/sales";
import SeriesChart from "@/components/charts/SeriesChart.vue";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import { rial } from "@/utils/format";

/**
 * Mirrors the workbook's two chart sheets:
 *   داشبورد فروشنده — 11 charts (9 per-salesperson + 2 provincial)
 *   داشبورد تیم     — 9 charts across the 5 teams
 */
const props = withDefaults(defineProps<{ channel?: string; title?: string }>(), {
  channel: "team",
  title: "داشبورد فروش",
});

interface Detail {
  period: { id: number; label: string };
  salespeople: Record<string, any>[];
  teams: Record<string, any>[];
  provinces: { name: string; sales: number; target: number }[];
}

const periods = ref<Period[]>([]);
const periodA = ref<number | null>(null);
const periodB = ref<number | null>(null);   // comparison month
const compare = ref(false);
const data = ref<Detail | null>(null);
const dataB = ref<Detail | null>(null);
const tab = ref<"people" | "teams">("people");
const loading = ref(false);

async function fetchDetail(pid: number): Promise<Detail> {
  const { data } = await api.get("/sales/dashboard/detail/", {
    params: { period: pid, channel: props.channel },
  });
  return data;
}

async function load() {
  if (!periodA.value) return;
  loading.value = true;
  try {
    data.value = await fetchDetail(periodA.value);
    dataB.value = compare.value && periodB.value ? await fetchDetail(periodB.value) : null;
  } finally {
    loading.value = false;
  }
}

// ---- helpers to build a chart series (with optional comparison month) ----
const names = computed(() => (data.value?.salespeople ?? []).map((s) => s.name));
const teamNames = computed(() => (data.value?.teams ?? []).map((t) => t.name));

function peopleSeries(label: string, key: string) {
  const s = [{ name: label, values: (data.value?.salespeople ?? []).map((p) => p[key]) }];
  if (dataB.value) {
    s.push({
      name: `${label} (${dataB.value.period.label})`,
      values: names.value.map((n) => dataB.value!.salespeople.find((p) => p.name === n)?.[key] ?? 0),
    });
  }
  return s;
}
function teamSeries(label: string, key: string) {
  const s = [{ name: label, values: (data.value?.teams ?? []).map((t) => t[key]) }];
  if (dataB.value) {
    s.push({
      name: `${label} (${dataB.value.period.label})`,
      values: teamNames.value.map((n) => dataB.value!.teams.find((t) => t.name === n)?.[key] ?? 0),
    });
  }
  return s;
}

// Top provinces with any sales (chart 10) + Tehran highlight (chart 11)
const topProvinces = computed(() => (data.value?.provinces ?? []).filter((p) => p.sales > 0).slice(0, 12));
const tehran = computed(() => (data.value?.provinces ?? []).find((p) => p.name.trim() === "تهران"));

const totalRevenue = computed(() =>
  (data.value?.salespeople ?? []).reduce((s, p) => s + Number(p.revenue || 0), 0),
);

onMounted(async () => {
  periods.value = await salesApi.periods();
  // Main period = latest month that has data; comparison starts unset.
  periodA.value = defaultPeriodId(periods.value);
  periodB.value = null;
  await load();
});
watch([periodA, periodB, compare, () => props.channel], load);
</script>

<template>
  <div class="space-y-4">
    <!-- Header: month picker + comparison toggle -->
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-lg font-bold text-ink">{{ title }}</h2>
        <p v-if="data" class="text-xs text-slate-400 mt-0.5">
          فروش کل این کانال: <span class="ltr-nums">{{ rial(totalRevenue) }}</span>
        </p>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <select v-model.number="periodA" class="bg-white border border-slate-200 rounded-xl px-3 py-1.5 text-sm">
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
        <label class="flex items-center gap-1.5 text-sm text-slate-500 bg-white border border-slate-200 rounded-xl px-3 py-1.5 cursor-pointer hover:bg-slate-50 transition-colors">
          <input v-model="compare" type="checkbox" class="rounded accent-brand-600" /> مقایسه با ماه دیگر
        </label>
        <select
          v-if="compare"
          v-model.number="periodB"
          class="bg-white border border-slate-200 rounded-xl px-3 py-1.5 text-sm"
        >
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <!-- Tabs -->
    <div class="flex gap-1">
      <button
        class="px-4 py-1.5 rounded-xl text-sm"
        :class="tab === 'people' ? 'bg-ink text-white' : 'bg-white border border-slate-200 hover:bg-slate-50'"
        @click="tab = 'people'"
      >داشبورد فروشنده</button>
      <button
        class="px-4 py-1.5 rounded-xl text-sm"
        :class="tab === 'teams' ? 'bg-ink text-white' : 'bg-white border border-slate-200 hover:bg-slate-50'"
        @click="tab = 'teams'"
      >داشبورد تیم</button>
    </div>

    <DashboardSkeleton v-if="loading || !data" :cards="0" :charts="6" :table="false" />

    <!-- ========== داشبورد فروشنده — 11 charts ========== -->
    <template v-else-if="tab === 'people'">
      <div v-if="!data.salespeople.length" class="bg-white rounded-card shadow-soft">
        <EmptyState
          icon="📊"
          title="داده‌ای برای این ماه نیست"
          hint="برای این دوره هنوز فروش تاییدشده‌ای ثبت نشده است. پس از ثبت و تأیید داده، نمودارها اینجا ظاهر می‌شوند."
        />
      </div>
      <template v-else>
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          <SeriesChart title="فروش ریالی" :categories="names" :series="peopleSeries('فروش ریالی', 'revenue')" />
          <SeriesChart title="تعداد مشتری جدید" :categories="names" :series="peopleSeries('مشتری جدید', 'new_customers')" />
          <SeriesChart title="سود فروش" :categories="names" :series="peopleSeries('سود فروش', 'profit')" />
          <SeriesChart
            title="درصد از حجم فروش" kind="pie" percent
            :categories="names" :series="[{ name: 'سهم', values: data.salespeople.map(p => p.volume_share) }]"
          />
          <SeriesChart
            title="هزینه / سود فروش" :categories="names"
            :series="[
              { name: 'سود فروش', values: data.salespeople.map(p => p.profit) },
              { name: 'هزینه فروش', values: data.salespeople.map(p => p.cost) },
            ]"
          />
          <SeriesChart
            title="تعداد فروش / تعداد مشتری" :categories="names"
            :series="[
              { name: 'تعداد فاکتور', values: data.salespeople.map(p => p.invoices) },
              { name: 'مشتری فعال', values: data.salespeople.map(p => p.active_customers) },
            ]"
          />
          <SeriesChart title="درصد رسیدن به تارگت" percent :categories="names" :series="peopleSeries('تحقق تارگت', 'target_achievement')" />
          <SeriesChart title="تعداد تماس" :categories="names" :series="peopleSeries('تعداد تماس', 'calls')" />
          <SeriesChart title="نرخ تماس موفق" percent :categories="names" :series="peopleSeries('تماس به فروش', 'call_conversion')" />
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SeriesChart
            title="فروش و تارگت به تفکیک استان" :height="300"
            :categories="topProvinces.map(p => p.name)"
            :series="[
              { name: 'فروش', values: topProvinces.map(p => p.sales) },
              { name: 'تارگت', values: topProvinces.map(p => p.target) },
            ]"
          />
          <SeriesChart
            v-if="tehran"
            title="تهران — فروش در برابر تارگت" :height="300"
            :categories="['تهران']"
            :series="[
              { name: 'فروش', values: [tehran.sales] },
              { name: 'تارگت', values: [tehran.target] },
            ]"
          />
        </div>
      </template>
    </template>

    <!-- ========== داشبورد تیم — 9 charts ========== -->
    <template v-else>
      <div v-if="!data.teams.length" class="bg-white rounded-card shadow-soft">
        <EmptyState
          icon="📊"
          title="داده‌ای برای این ماه نیست"
          hint="برای این دوره هنوز فروش تیمی تاییدشده‌ای ثبت نشده است. پس از ثبت و تأیید داده، نمودارها اینجا ظاهر می‌شوند."
        />
      </div>
      <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <SeriesChart title="فروش ریالی تیم‌ها" :categories="teamNames" :series="teamSeries('فروش ریالی', 'revenue')" />
        <SeriesChart title="تعداد فاکتور فروش" :categories="teamNames" :series="teamSeries('تعداد فاکتور', 'invoices')" />
        <SeriesChart
          title="مشتری فعال / مشتری جدید" :categories="teamNames"
          :series="[
            { name: 'مشتری فعال', values: data.teams.map(t => t.active_customers) },
            { name: 'مشتری جدید', values: data.teams.map(t => t.new_customers) },
          ]"
        />
        <SeriesChart
          title="فروش در برابر تارگت" :categories="teamNames"
          :series="[
            { name: 'فروش ریالی', values: data.teams.map(t => t.revenue) },
            { name: 'تارگت فروش', values: data.teams.map(t => t.target) },
          ]"
        />
        <SeriesChart
          title="سود / هزینه فروش" :categories="teamNames"
          :series="[
            { name: 'سود فروش', values: data.teams.map(t => t.profit) },
            { name: 'هزینه فروش', values: data.teams.map(t => t.cost) },
          ]"
        />
        <SeriesChart title="نسبت تماس موفق" :categories="teamNames" :series="teamSeries('نسبت تماس موفق', 'success_call_ratio')" />
        <SeriesChart title="درصد تحقق تارگت" percent :categories="teamNames" :series="teamSeries('تحقق تارگت', 'target_achievement')" />
        <SeriesChart title="سهم تیم از فروش به تارگت" percent :categories="teamNames" :series="teamSeries('سهم از تارگت کل', 'share_of_total_target')" />
        <SeriesChart title="هزینه به فروش" percent :categories="teamNames" :series="teamSeries('هزینه به فروش', 'cost_to_sales')" />
      </div>
    </template>
  </div>
</template>
