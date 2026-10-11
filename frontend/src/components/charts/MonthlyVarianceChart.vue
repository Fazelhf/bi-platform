<script setup lang="ts">
/**
 * انحراف ماه‌به‌ماه — one column per month: how far the month's net cash
 * landed from plan, above zero when it beat the plan, below when it fell
 * short. The selected month is drawn solid, the others lighter; months with
 * nothing recorded are left empty rather than drawn as a «zero variance».
 *
 * The cumulative variance runs along it as a line — on the same axis and in
 * the same unit (rials of variance), so it is one scale, not two: it is the
 * running sum of the very columns beneath it.
 */
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { useUiStore } from "@/stores/ui";
import { AXIS, TOOLTIP, compact, labelColor, mutedColor } from "./theme";

const props = withDefaults(defineProps<{
  title: string;
  subtitle?: string;
  points: { label: string; budget: number; actual: number; has: boolean; current?: boolean }[];
  /** Judge as money in (more is good). Net cash is judged that way. */
  goodWhenHigher?: boolean;
  height?: number;
}>(), { goodWhenHigher: true, height: 280 });

const ui = useUiStore();
const el = ref<HTMLElement | null>(null);
const GOOD = "#10b981";
const BAD = "#f43f5e";

const option = computed<EChartsOption>(() => {
  void ui.chartTheme;
  const pts = props.points;
  const variance = pts.map((p) => (p.has ? p.actual - p.budget : null));
  let run = 0;
  const cumulative = pts.map((p, i) => {
    if (!p.has) return null;
    run += variance[i] ?? 0;
    return run;
  });
  const good = (v: number) => (props.goodWhenHigher ? v >= 0 : v <= 0);
  return {
    grid: { top: 34, right: 12, bottom: 28, left: 56 },
    legend: {
      top: 0,
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { fontSize: 11, color: mutedColor() },
      data: ["انحراف ماه", "انحراف تجمعی"],
    },
    tooltip: {
      ...TOOLTIP,
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params: any) => {
        const i = params?.[0]?.dataIndex ?? 0;
        const p = pts[i];
        if (!p) return "";
        if (!p.has) return `${p.label}<br/>هنوز رقم واقعی ثبت نشده`;
        const v = p.actual - p.budget;
        const pct = p.budget ? ` (${v > 0 ? "+" : ""}${Math.round((v / Math.abs(p.budget)) * 1000) / 10}٪)` : "";
        return `<b>${p.label}</b><br/>بودجه: ${compact(p.budget)}<br/>واقعی: ${compact(p.actual)}<br/>` +
          `انحراف: ${v > 0 ? "+" : ""}${compact(v)}${pct} — ${good(v) ? "مطلوب" : "نامطلوب"}<br/>` +
          `تجمعی تا این ماه: ${compact(cumulative[i] ?? 0)}`;
      },
    },
    xAxis: { ...AXIS.category, data: pts.map((p) => p.label) },
    yAxis: {
      ...AXIS.value,
      axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => compact(v) },
    },
    series: [
      {
        name: "انحراف ماه",
        type: "bar",
        barMaxWidth: 34,
        // The legend swatch: neutral, since each column carries its own verdict colour.
        itemStyle: { color: mutedColor() },
        data: variance.map((v, i) =>
          v === null
            ? { value: null }
            : {
                value: v,
                itemStyle: {
                  color: good(v) ? GOOD : BAD,
                  opacity: pts[i].current ? 1 : 0.55,
                  borderRadius: v >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4],
                },
              },
        ),
        label: {
          show: true,
          position: "top",
          fontSize: 10,
          color: labelColor(),
          formatter: (p: any) => (p.value === null || p.value === undefined ? "" : compact(Number(p.value))),
        },
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: mutedColor(), width: 1, type: "solid" },
          label: { show: false },
          data: [{ yAxis: 0 }],
        },
      },
      {
        name: "انحراف تجمعی",
        type: "line",
        data: cumulative,
        connectNulls: false,
        symbol: "circle",
        symbolSize: 8,
        lineStyle: { width: 2, color: labelColor() },
        itemStyle: { color: labelColor(), borderColor: "#fff", borderWidth: 2 },
      },
    ],
  };
});

useChart(el, option);
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink">{{ title }}</h3>
    <p v-if="subtitle" class="text-[11px] text-slate-400 mt-0.5">{{ subtitle }}</p>
    <p v-if="!points.some((p) => p.has)" class="text-xs text-slate-400 text-center py-10">هنوز برای هیچ ماهی رقم واقعی نیست.</p>
    <div v-show="points.some((p) => p.has)" ref="el" :style="{ height: height + 'px' }"></div>
  </div>
</template>
