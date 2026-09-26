<script setup lang="ts">
/**
 * A single percentage against its target, as a dial.
 *
 * Two kinds of «good»: achievement (sales, collections) is good when high,
 * spend is good when it stays at or under plan. The colour bands follow that,
 * so a 110% on «مصرف بودجهٔ خروجی» reads amber rather than green.
 */
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { useUiStore } from "@/stores/ui";
import { COLORS, labelColor, mutedColor } from "./theme";

const props = withDefaults(defineProps<{
  title: string;
  /** Percent, or null when there was nothing to measure against. */
  value: number | null;
  subtitle?: string;
  goodWhenHigh?: boolean;
  max?: number;
  height?: number;
  /** Without its own card — for use inside another one. */
  flat?: boolean;
}>(), { subtitle: "", goodWhenHigh: true, max: 150, height: 180, flat: false });

const ui = useUiStore();
const el = ref<HTMLElement | null>(null);
const FA = new Intl.NumberFormat("fa-IR");

const option = computed<EChartsOption>(() => {
  void ui.chartTheme;
  const max = props.max;
  const value = props.value ?? 0;
  const amber = "#f59e0b";
  const bands: [number, string][] = props.goodWhenHigh
    ? [[70 / max, COLORS.rose], [100 / max, amber], [1, COLORS.target]]
    : [[100 / max, COLORS.target], [115 / max, amber], [1, COLORS.rose]];

  return {
    series: [{
      type: "gauge",
      min: 0,
      max,
      startAngle: 200,
      endAngle: -20,
      radius: "96%",
      center: ["50%", "64%"],
      pointer: { length: "56%", width: 5, itemStyle: { color: labelColor() } },
      anchor: { show: true, size: 9, itemStyle: { color: labelColor() } },
      axisLine: { lineStyle: { width: 12, color: bands } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: {
        distance: -32,
        fontSize: 9,
        color: mutedColor(),
        formatter: (v: number) => (v === 0 || v === 100 || v === max ? FA.format(v) : ""),
      },
      title: { show: false },
      detail: {
        offsetCenter: [0, "34%"],
        fontSize: 20,
        fontWeight: "bold",
        color: labelColor(),
        formatter: () => (props.value === null ? "—" : `${FA.format(Math.round(value * 10) / 10)}٪`),
      },
      data: [{ value: Math.min(Math.max(value, 0), max) }],
    }],
  };
});

useChart(el, option);
</script>

<template>
  <div :class="flat ? '' : 'bg-surface rounded-card shadow-soft p-4'">
    <h3 class="text-sm font-semibold text-ink text-center">{{ title }}</h3>
    <div ref="el" :style="{ height: height + 'px' }"></div>
    <p v-if="subtitle" class="text-[11px] text-slate-400 text-center -mt-2 truncate" :title="subtitle">{{ subtitle }}</p>
  </div>
</template>
