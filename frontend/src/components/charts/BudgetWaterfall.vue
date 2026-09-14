<script setup lang="ts">
/**
 * آبشار انحراف — from planned net cash to actual net cash, one step per line.
 *
 * The one chart that answers «چرا پول‌مان با انتظار فرق کرد؟». Each step is
 * the line's effect on cash (an inflow that came in short pushes down, and so
 * does an overspend), so the steps genuinely add up to the gap.
 *
 * ECharts has no native waterfall. It is drawn as stacked bars over an
 * invisible base — split into a positive and a negative stack, because net
 * cash here is often below zero and a single stack cannot float a bar that
 * starts at −110 and ends at −155.
 */
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { useUiStore } from "@/stores/ui";
import { AXIS, COLORS, TOOLTIP, compact } from "./theme";
import type { Verdict } from "@/api/budget";

const props = withDefaults(defineProps<{
  title: string;
  start: number;
  end: number;
  steps: { label: string; effect: number; verdict: Verdict }[];
  /** Beyond this many steps the rest are folded into «سایر اقلام». */
  maxSteps?: number;
  height?: number;
}>(), { maxSteps: 10, height: 320 });

const ui = useUiStore();
const el = ref<HTMLElement | null>(null);

const short = (s: string) => (s.length > 16 ? `${s.slice(0, 15)}…` : s);

const option = computed<EChartsOption>(() => {
  void ui.chartTheme;
  const good = COLORS.target;
  const bad = COLORS.rose;
  const total = COLORS.actual;

  // Fold the tail so the chart stays readable, and derive «سایر» from the gap
  // itself: the bars must land exactly on the actual figure however the
  // steps were rounded.
  const top = props.steps.slice(0, props.maxSteps);
  const shown = top.reduce((s, x) => s + x.effect, 0);
  const rest = props.end - props.start - shown;
  const steps = [...top];
  if (Math.abs(rest) >= 1) {
    steps.push({ label: "سایر اقلام", effect: rest, verdict: rest >= 0 ? "good" : "bad" });
  }

  const labels: string[] = ["بودجهٔ خالص"];
  const tips: string[] = [`بودجهٔ خالص: ${compact(props.start)}`];
  const basePos: number[] = [];
  const baseNeg: number[] = [];
  const barPos: any[] = [];
  const barNeg: any[] = [];

  const totalBar = (v: number) => {
    basePos.push(0);
    baseNeg.push(0);
    barPos.push({ value: v >= 0 ? v : 0, itemStyle: { color: total } });
    barNeg.push({ value: v < 0 ? v : 0, itemStyle: { color: total } });
  };

  /** A floating bar spanning [lo, hi], wherever zero falls. */
  const span = (lo: number, hi: number, color: string) => {
    if (lo >= 0) {
      basePos.push(lo); baseNeg.push(0);
      barPos.push({ value: hi - lo, itemStyle: { color } }); barNeg.push({ value: 0 });
    } else if (hi <= 0) {
      basePos.push(0); baseNeg.push(hi);
      barPos.push({ value: 0 }); barNeg.push({ value: lo - hi, itemStyle: { color } });
    } else {
      basePos.push(0); baseNeg.push(0);
      barPos.push({ value: hi, itemStyle: { color } });
      barNeg.push({ value: lo, itemStyle: { color } });
    }
  };

  totalBar(props.start);
  let run = props.start;
  for (const s of steps) {
    const next = run + s.effect;
    span(Math.min(run, next), Math.max(run, next), s.verdict === "good" ? good : bad);
    labels.push(short(s.label));
    const sign = s.effect > 0 ? "+" : "";
    tips.push(`${s.label}: ${sign}${compact(s.effect)}<br/>پس از این قلم: ${compact(next)}`);
    run = next;
  }
  labels.push("واقعی خالص");
  tips.push(`واقعی خالص: ${compact(props.end)}`);
  totalBar(props.end);

  const invisible = {
    type: "bar" as const,
    stack: "w",
    silent: true,
    itemStyle: { color: "transparent" },
    emphasis: { disabled: true },
  };
  const visible = { type: "bar" as const, stack: "w", barMaxWidth: 34 };

  return {
    grid: { top: 16, right: 14, bottom: 70, left: 56 },
    tooltip: {
      ...TOOLTIP,
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params: any) => tips[params?.[0]?.dataIndex ?? 0] ?? "",
    },
    xAxis: {
      ...AXIS.category,
      data: labels,
      axisLabel: { ...AXIS.category.axisLabel, rotate: 35, fontSize: 10, interval: 0 },
    },
    yAxis: {
      ...AXIS.value,
      axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => compact(v) },
    },
    series: [
      { ...invisible, name: "base+", data: basePos },
      { ...invisible, name: "base-", data: baseNeg },
      { ...visible, name: "value+", data: barPos },
      { ...visible, name: "value-", data: barNeg },
    ],
  };
});

useChart(el, option);
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink mb-1 text-center">{{ title }}</h3>
    <p v-if="!steps.length" class="text-xs text-slate-400 text-center py-10">
      در این دوره هیچ قلمی از بودجه فاصله نگرفته است.
    </p>
    <div v-show="steps.length" ref="el" :style="{ height: height + 'px' }"></div>
  </div>
</template>
