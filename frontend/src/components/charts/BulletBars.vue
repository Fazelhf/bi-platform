<script setup lang="ts">
/**
 * Plan against actual, one horizontal bullet per item.
 *
 * The plan is the wide pale bar, the actual the narrow coloured one laid over
 * it — so «how much of the budget did this use» is read as a length, and the
 * colour says whether that is good news for this side of the ledger.
 */
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { useUiStore } from "@/stores/ui";
import { AXIS, COLORS, TOOLTIP, compact, mutedColor } from "./theme";
import type { Verdict } from "@/api/budget";

const props = defineProps<{
  title: string;
  items: { label: string; budget: number; actual: number; verdict: Verdict }[];
}>();

const ui = useUiStore();
const el = ref<HTMLElement | null>(null);
const FA = new Intl.NumberFormat("fa-IR");

const rows = computed(() => [...props.items].reverse()); // first item on top
const height = computed(() => Math.max(160, 56 + props.items.length * 36));

const option = computed<EChartsOption>(() => {
  void ui.chartTheme;
  const short = (s: string) => (s.length > 20 ? `${s.slice(0, 19)}…` : s);
  const tone = (v: Verdict) => (v === "good" ? COLORS.target : v === "bad" ? COLORS.rose : COLORS.actual);
  return {
    grid: { top: 26, right: 18, bottom: 22, left: 8, containLabel: true },
    legend: {
      top: 0,
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { fontSize: 11, color: mutedColor() },
      data: ["بودجه", "واقعی"],
    },
    tooltip: {
      ...TOOLTIP,
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params: any) => {
        const item = rows.value[params?.[0]?.dataIndex ?? 0];
        if (!item) return "";
        const pct = item.budget ? `${FA.format(Math.round((item.actual / item.budget) * 1000) / 10)}٪ بودجه` : "بدون بودجه";
        return `${item.label}<br/>بودجه: ${compact(item.budget)}<br/>واقعی: ${compact(item.actual)} (${pct})`;
      },
    },
    xAxis: {
      ...AXIS.value,
      axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => compact(v) },
    },
    yAxis: {
      ...AXIS.category,
      data: rows.value.map((i) => short(i.label)),
      axisLabel: { ...AXIS.category.axisLabel, fontSize: 11 },
    },
    series: [
      {
        name: "بودجه",
        type: "bar",
        barWidth: 18,
        data: rows.value.map((i) => i.budget),
        itemStyle: { color: COLORS.slate, borderRadius: 4, opacity: 0.6 },
        z: 1,
      },
      {
        name: "واقعی",
        type: "bar",
        barWidth: 8,
        barGap: "-72%",
        data: rows.value.map((i) => ({ value: i.actual, itemStyle: { color: tone(i.verdict), borderRadius: 3 } })),
        itemStyle: { color: COLORS.actual },
        z: 2,
      },
    ],
  };
});

useChart(el, option);
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink mb-1 text-center">{{ title }}</h3>
    <p v-if="!items.length" class="text-xs text-slate-400 text-center py-10">داده‌ای برای نمایش نیست.</p>
    <div v-show="items.length" ref="el" :style="{ height: height + 'px' }"></div>
  </div>
</template>
