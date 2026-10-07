<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { dashboardsApi, type BoardWidget, type QueryResult } from "@/api/dashboards";
import SeriesChart from "@/components/charts/SeriesChart.vue";
import Skeleton from "@/components/Skeleton.vue";
import { byUnit } from "./format";

/**
 * One board card, set against other months.
 *
 * A card stores a question, not an answer, so comparing is just asking the
 * same question once per month: each month runs the card's own query with the
 * time window pinned to that month. Nothing is re-derived client-side, which
 * keeps the comparison identical to what the card itself would show if the
 * month picker were moved.
 */
const props = defineProps<{
  widget: BoardWidget;
  periods: { id: number; label: string }[];
  current: number | null;
}>();
const emit = defineEmits<{ (e: "close"): void }>();

const months = ref<number[]>([]);
const results = ref<{ id: number; label: string; data: QueryResult }[]>([]);
const loading = ref(false);
const failed = ref(false);
const metricKey = ref(props.widget.config.metrics?.[0] ?? "");
const view = ref<"entity" | "trend">("entity");

function order(id: number) {
  return props.periods.findIndex((p) => p.id === id);
}

function toggle(id: number) {
  const i = months.value.indexOf(id);
  if (i >= 0) {
    // Never leave nothing to draw.
    if (months.value.length === 1) return;
    months.value.splice(i, 1);
  } else {
    months.value.push(id);
  }
  months.value.sort((a, b) => order(a) - order(b));
}

async function load() {
  loading.value = true;
  failed.value = false;
  try {
    const config = { ...props.widget.config, time: { mode: "selected" as const } };
    results.value = await Promise.all(
      months.value.map(async (id) => ({
        id,
        label: props.periods.find((p) => p.id === id)?.label ?? String(id),
        data: await dashboardsApi.query(config, id),
      })),
    );
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  const i = order(props.current ?? -1);
  months.value = [props.periods[i - 1]?.id, props.periods[i]?.id ?? props.periods.at(-1)?.id]
    .filter((x): x is number => x !== undefined);
  load();
});
watch(months, load, { deep: true });

// ---- shaping ---------------------------------------------------------------
const metrics = computed(() =>
  (results.value[0]?.data.series ?? []).map((s) => ({ key: s.key, name: s.name, unit: s.unit })),
);
const unit = computed(() => metrics.value.find((m) => m.key === metricKey.value)?.unit ?? "number");
const percent = computed(() => unit.value === "percent");

function valuesOf(r: QueryResult): Map<string, number> {
  const s = r.series.find((x) => x.key === metricKey.value) ?? r.series[0];
  return new Map(r.categories.map((c, i) => [c, Number(s?.values[i] ?? 0)]));
}

/** Everyone seen in any month, so someone present in only one is not dropped. */
const entities = computed(() => {
  const seen = new Set<string>();
  for (const r of results.value) for (const c of r.data.categories) seen.add(c);
  return [...seen];
});

const perMonth = computed(() => results.value.map((r) => ({ label: r.label, values: valuesOf(r.data) })));

const entitySeries = computed(() =>
  perMonth.value.map((m) => ({ name: m.label, values: entities.value.map((e) => m.values.get(e) ?? 0) })),
);

const totals = computed(() =>
  results.value.map((r) => {
    const t = r.data.totals?.[metricKey.value];
    const vals = [...valuesOf(r.data).values()];
    const sum = vals.reduce((a, b) => a + b, 0);
    return { label: r.label, value: t ?? (percent.value && vals.length ? sum / vals.length : sum) };
  }),
);

const change = computed(() => {
  const t = totals.value;
  if (t.length < 2 || !t[0].value) return null;
  return ((t[t.length - 1].value - t[0].value) / Math.abs(t[0].value)) * 100;
});

function fmt(v: number) {
  return byUnit(v, unit.value);
}
function rowVals(name: string) {
  return perMonth.value.map((m) => m.values.get(name) ?? 0);
}
function cell(v: number, vals: number[]) {
  const best = Math.max(...vals);
  const worst = Math.min(...vals);
  if (vals.length < 2 || best === worst) return "text-slate-600";
  return v === best ? "text-green-600 font-semibold" : v === worst ? "text-red-500" : "text-slate-600";
}
const title = computed(() => props.widget.title || "مقایسه");
const metricName = computed(() => metrics.value.find((m) => m.key === metricKey.value)?.name ?? "");
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[70] bg-black/40 flex items-start justify-center p-3 sm:p-6 overflow-y-auto" dir="rtl"
         @click.self="emit('close')">
      <div class="bg-surface rounded-card shadow-pop w-full max-w-5xl my-auto flex flex-col max-h-[94vh]">
        <header class="px-5 py-4 border-b border-slate-100 flex items-start justify-between gap-3 shrink-0">
          <div class="min-w-0">
            <p class="text-[11px] text-slate-400">مقایسه چند ماه</p>
            <h2 class="font-bold text-ink truncate">{{ title }}</h2>
          </div>
          <button class="text-slate-400 hover:text-ink text-2xl leading-none px-1" @click="emit('close')">×</button>
        </header>

        <div class="flex-1 overflow-y-auto p-5 space-y-4">
          <div>
            <p class="text-xs text-slate-400 mb-2">ماه‌های انتخابی — برای افزودن یا حذف کلیک کنید</p>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="p in periods" :key="p.id"
                class="text-xs rounded-xl px-3 py-1.5 border transition-colors"
                :class="months.includes(p.id)
                  ? 'bg-panel text-white border-panel'
                  : 'bg-surface text-slate-500 border-slate-200 hover:bg-slate-50'"
                @click="toggle(p.id)"
              >{{ p.label }}</button>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-2">
            <div v-if="metrics.length > 1" class="flex rounded-xl bg-slate-100 p-0.5">
              <button
                v-for="m in metrics" :key="m.key"
                class="text-xs px-3 py-1.5 rounded-lg transition-colors"
                :class="metricKey === m.key ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-400'"
                @click="metricKey = m.key"
              >{{ m.name }}</button>
            </div>
            <span class="flex-1"></span>
            <div class="flex rounded-xl bg-slate-100 p-0.5">
              <button class="text-xs px-3 py-1.5 rounded-lg transition-colors"
                      :class="view === 'entity' ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-400'"
                      @click="view = 'entity'">تفکیکی</button>
              <button class="text-xs px-3 py-1.5 rounded-lg transition-colors"
                      :class="view === 'trend' ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-400'"
                      @click="view = 'trend'">روند کل</button>
            </div>
          </div>

          <p v-if="failed" class="text-sm text-red-500 text-center py-10">مقایسه بارگذاری نشد.</p>
          <Skeleton v-else-if="loading" class="h-80 rounded-card" />

          <template v-else-if="results.length">
            <SeriesChart
              v-if="view === 'entity'"
              :title="title" :categories="entities" :series="entitySeries" :percent="percent" :height="360"
            />
            <SeriesChart
              v-else
              :title="title" :categories="totals.map((t) => t.label)"
              :series="[{ name: metricName, values: totals.map((t) => t.value) }]"
              :percent="percent" :height="360"
            />

            <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div v-for="t in totals" :key="t.label" class="bg-slate-50 rounded-xl px-3 py-2">
                <p class="text-[11px] text-slate-400 truncate">{{ t.label }}</p>
                <p class="text-sm font-bold text-ink ltr-nums">{{ fmt(t.value) }}</p>
              </div>
              <div v-if="change !== null" class="bg-slate-50 rounded-xl px-3 py-2">
                <p class="text-[11px] text-slate-400">تغییر اول تا آخر</p>
                <p class="text-sm font-bold ltr-nums" :class="change >= 0 ? 'text-green-600' : 'text-red-500'">
                  {{ change >= 0 ? "▲" : "▼" }} {{ Math.abs(Math.round(change * 10) / 10) }}٪
                </p>
              </div>
            </div>

            <div class="overflow-x-auto">
              <table class="w-full text-sm min-w-[520px]">
                <thead>
                  <tr class="text-xs text-slate-400 bg-slate-50">
                    <th class="text-right font-medium px-3 py-2">{{ results[0]?.data.dimension?.label }}</th>
                    <th v-for="r in results" :key="r.id" class="text-left font-medium px-3 py-2 whitespace-nowrap">{{ r.label }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="n in entities" :key="n" class="border-t border-slate-100">
                    <td class="px-3 py-2 text-ink">{{ n }}</td>
                    <td v-for="(v, i) in rowVals(n)" :key="i"
                        class="px-3 py-2 text-left ltr-nums whitespace-nowrap" :class="cell(v, rowVals(n))">{{ fmt(v) }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-if="results.length > 1" class="text-[11px] text-slate-300 mt-2">
                در هر ردیف، بهترین ماه سبز و ضعیف‌ترین ماه قرمز نشان داده شده است.
              </p>
            </div>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>
