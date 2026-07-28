<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import api from "@/api/client";
import type { CompareSpec } from "@/components/charts/SeriesChart.vue";
import type { Period } from "@/types";
import SeriesChart from "@/components/charts/SeriesChart.vue";
import Skeleton from "@/components/Skeleton.vue";
import { pct, rial } from "@/utils/format";

/**
 * One chart, opened close-up across several months.
 *
 * The dashboards used to offer a single "compare with another month"
 * checkbox, which only reached the six charts built through the series
 * helpers and only ever held two months. The manager wants several months at
 * once, and cramming N months into twenty small cards would make all of them
 * unreadable — so comparison moved here: pick the months, open the one chart
 * you care about, and see it big.
 */
const props = defineProps<{
  spec: CompareSpec;
  title: string;
  channel: string;
  periods: Period[];
  selected: number[];
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "update:selected", ids: number[]): void }>();

interface Detail {
  period: { id: number; label: string };
  salespeople: Record<string, any>[];
  teams: Record<string, any>[];
  provinces: { name: string; sales: number; target: number }[];
}

const loading = ref(false);
const details = ref<Detail[]>([]);
const metric = ref(props.spec.metrics[0]);
const view = ref<"entity" | "trend">("entity");

/** Local copy so toggling months inside the modal feels immediate. */
const months = ref<number[]>([...props.selected]);

function toggleMonth(id: number) {
  const i = months.value.indexOf(id);
  if (i >= 0) {
    // Never leave nothing to draw.
    if (months.value.length === 1) return;
    months.value.splice(i, 1);
  } else {
    months.value.push(id);
  }
  months.value.sort((a, b) => periodOrder(a) - periodOrder(b));
  emit("update:selected", [...months.value]);
}

/** Chronological, using the order the period list already comes in. */
function periodOrder(id: number) {
  return props.periods.findIndex((p) => p.id === id);
}

async function load() {
  loading.value = true;
  try {
    const results = await Promise.all(
      months.value.map(async (id) => {
        const { data } = await api.get("/sales/dashboard/detail/", {
          params: { period: id, channel: props.channel },
        });
        return data as Detail;
      }),
    );
    details.value = results;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(months, load, { deep: true });

// ---- shaping ---------------------------------------------------------------
function rowsOf(d: Detail): Record<string, any>[] {
  if (props.spec.scope === "teams") return d.teams ?? [];
  if (props.spec.scope === "provinces") return d.provinces ?? [];
  return d.salespeople ?? [];
}

function valueOf(row: Record<string, any> | undefined): number {
  return Number(row?.[metric.value.key] ?? 0);
}

/** Every entity seen in any of the months, so someone who sold in only one
 *  month is not silently dropped from the comparison. */
const entities = computed(() => {
  const seen = new Set<string>();
  for (const d of details.value) for (const r of rowsOf(d)) seen.add(r.name);
  return [...seen];
});

const monthLabels = computed(() => details.value.map((d) => d.period.label));

const entitySeries = computed(() =>
  details.value.map((d) => ({
    name: d.period.label,
    values: entities.value.map((n) => valueOf(rowsOf(d).find((r) => r.name === n))),
  })),
);

/** Percent metrics are averages, not sums — totalling them would be nonsense. */
const isRate = computed(() => !!metric.value.percent);

const trendSeries = computed(() => [{
  name: metric.value.label,
  values: details.value.map((d) => {
    const rows = rowsOf(d);
    const total = rows.reduce((s, r) => s + valueOf(r), 0);
    return isRate.value ? (rows.length ? total / rows.length : 0) : total;
  }),
}]);

const totals = computed(() =>
  details.value.map((d, i) => ({
    label: d.period.label,
    value: trendSeries.value[0].values[i],
  })),
);

/** First → last change, the number the manager actually asks for. */
const change = computed(() => {
  const v = trendSeries.value[0].values;
  if (v.length < 2) return null;
  const [first, last] = [v[0], v[v.length - 1]];
  if (!first) return null;
  return ((last - first) / Math.abs(first)) * 100;
});

function fmt(v: number): string {
  return isRate.value ? pct(v) : rial(v);
}

function cellClass(v: number, best: number, worst: number): string {
  if (details.value.length < 2 || best === worst) return "text-slate-600";
  if (v === best) return "text-green-600 font-semibold";
  if (v === worst) return "text-red-500";
  return "text-slate-600";
}

function rowStats(name: string) {
  const vals = details.value.map((d) => valueOf(rowsOf(d).find((r) => r.name === name)));
  return { vals, best: Math.max(...vals), worst: Math.min(...vals) };
}

function exportCsv() {
  const head = [props.spec.scope === "teams" ? "تیم" : props.spec.scope === "provinces" ? "استان" : "کارشناس", ...monthLabels.value];
  const body = entities.value.map((n) => [n, ...rowStats(n).vals]);
  const foot = ["مجموع", ...trendSeries.value[0].values];
  const csv = [head, ...body, foot]
    .map((line) => line.map((c: any) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(","))
    .join("\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${props.title} — ${metric.value.label}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[70] bg-black/40 flex items-start justify-center p-3 sm:p-6 overflow-y-auto" dir="rtl">
      <div class="bg-surface rounded-card shadow-pop w-full max-w-5xl my-auto flex flex-col max-h-[94vh]">
        <!-- Header -->
        <header class="px-5 py-4 border-b border-slate-100 flex items-start justify-between gap-3 shrink-0">
          <div class="min-w-0">
            <p class="text-[11px] text-slate-400">مقایسه چند ماه</p>
            <h2 class="font-bold text-ink truncate">{{ title }}</h2>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <button class="text-xs rounded-lg px-3 py-1.5 bg-slate-100 text-slate-600 hover:bg-slate-200" @click="exportCsv">
              خروجی اکسل
            </button>
            <button class="text-slate-400 hover:text-ink text-2xl leading-none px-1" @click="emit('close')">×</button>
          </div>
        </header>

        <div class="flex-1 overflow-y-auto p-5 space-y-4">
          <!-- Month chips -->
          <div>
            <p class="text-xs text-slate-400 mb-2">ماه‌های انتخابی — برای افزودن یا حذف کلیک کنید</p>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="p in periods" :key="p.id"
                class="text-xs rounded-xl px-3 py-1.5 border transition-colors"
                :class="months.includes(p.id)
                  ? 'bg-panel text-white border-panel'
                  : 'bg-surface text-slate-500 border-slate-200 hover:bg-slate-50'"
                @click="toggleMonth(p.id)"
              >{{ p.label }}</button>
            </div>
          </div>

          <!-- Metric + view -->
          <div class="flex flex-wrap items-center gap-2">
            <div v-if="spec.metrics.length > 1" class="flex rounded-xl bg-slate-100 p-0.5">
              <button
                v-for="m in spec.metrics" :key="m.key"
                class="text-xs px-3 py-1.5 rounded-lg transition-colors"
                :class="metric.key === m.key ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-400'"
                @click="metric = m"
              >{{ m.label }}</button>
            </div>
            <span class="flex-1"></span>
            <div class="flex rounded-xl bg-slate-100 p-0.5">
              <button
                class="text-xs px-3 py-1.5 rounded-lg transition-colors"
                :class="view === 'entity' ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-400'"
                @click="view = 'entity'"
              >تفکیکی</button>
              <button
                class="text-xs px-3 py-1.5 rounded-lg transition-colors"
                :class="view === 'trend' ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-400'"
                @click="view = 'trend'"
              >روند کل</button>
            </div>
          </div>

          <Skeleton v-if="loading" class="h-80 rounded-card" />

          <template v-else>
            <!-- Close-up chart -->
            <SeriesChart
              v-if="view === 'entity'"
              :title="`${metric.label} — به تفکیک ${spec.scope === 'teams' ? 'تیم' : spec.scope === 'provinces' ? 'استان' : 'کارشناس'}`"
              :categories="entities"
              :series="entitySeries"
              :percent="metric.percent"
              :height="360"
            />
            <SeriesChart
              v-else
              :title="`${metric.label} — ${isRate ? 'میانگین' : 'مجموع'} هر ماه`"
              :categories="monthLabels"
              :series="trendSeries"
              :percent="metric.percent"
              :height="360"
            />

            <!-- Headline: where it started, where it ended -->
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div v-for="t in totals" :key="t.label" class="bg-slate-50 rounded-xl px-3 py-2">
                <p class="text-[11px] text-slate-400 truncate">{{ t.label }}</p>
                <p class="text-sm font-bold text-ink ltr-nums">{{ fmt(t.value) }}</p>
              </div>
              <div v-if="change !== null" class="bg-slate-50 rounded-xl px-3 py-2">
                <p class="text-[11px] text-slate-400">تغییر اول تا آخر</p>
                <p class="text-sm font-bold ltr-nums" :class="change >= 0 ? 'text-green-600' : 'text-red-500'">
                  {{ change >= 0 ? "▲" : "▼" }} {{ pct(Math.abs(change)) }}
                </p>
              </div>
            </div>

            <!-- The numbers behind the bars -->
            <div class="overflow-x-auto">
              <table class="w-full text-sm min-w-[520px]">
                <thead>
                  <tr class="text-xs text-slate-400 bg-slate-50">
                    <th class="text-right font-medium px-3 py-2">
                      {{ spec.scope === "teams" ? "تیم" : spec.scope === "provinces" ? "استان" : "کارشناس" }}
                    </th>
                    <th v-for="l in monthLabels" :key="l" class="text-left font-medium px-3 py-2 whitespace-nowrap">{{ l }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="n in entities" :key="n" class="border-t border-slate-100">
                    <td class="px-3 py-2 text-ink">{{ n }}</td>
                    <td
                      v-for="(v, i) in rowStats(n).vals" :key="i"
                      class="px-3 py-2 text-left ltr-nums whitespace-nowrap"
                      :class="cellClass(v, rowStats(n).best, rowStats(n).worst)"
                    >{{ fmt(v) }}</td>
                  </tr>
                </tbody>
                <tfoot>
                  <tr class="border-t-2 border-slate-200 bg-slate-50 font-bold text-ink">
                    <td class="px-3 py-2">{{ isRate ? "میانگین" : "مجموع" }}</td>
                    <td v-for="(v, i) in trendSeries[0].values" :key="i" class="px-3 py-2 text-left ltr-nums whitespace-nowrap">
                      {{ fmt(v) }}
                    </td>
                  </tr>
                </tfoot>
              </table>
              <p v-if="details.length > 1" class="text-[11px] text-slate-300 mt-2">
                در هر ردیف، بهترین ماه سبز و ضعیف‌ترین ماه قرمز نشان داده شده است.
              </p>
            </div>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>
