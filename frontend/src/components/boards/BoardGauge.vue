<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { useUiStore } from "@/stores/ui";
import { labelColor, mutedColor, seriesColor } from "@/components/charts/theme";
import type { QueryResult, WidgetOptions } from "@/api/dashboards";

/**
 * Achievement against a target, as a dial.
 *
 * The second metric is the target; without one the widget falls back to the
 * `goal` typed into the editor, and without that it has nothing to be a
 * fraction *of* — so it says so rather than drawing a needle at an arbitrary
 * place on an arbitrary scale.
 */
const props = withDefaults(defineProps<{
  result: QueryResult;
  options?: WidgetOptions;
}>(), { options: () => ({}) });

const ui = useUiStore();
const el = ref<HTMLElement | null>(null);

const value = computed(() => props.result.series[0]?.values[0] ?? 0);
const target = computed(
  () => props.result.series[1]?.values[0] ?? props.options.goal ?? 0,
);
const hasTarget = computed(() => !!target.value);
const percent = computed(() =>
  hasTarget.value ? Math.round((value.value / target.value) * 1000) / 10 : 0,
);

const option = computed<EChartsOption>(() => {
  void ui.chartTheme;
  const p = percent.value;
  const color = props.options.color
    || (p >= 100 ? "#16a34a" : p >= 70 ? "#f59e0b" : "#ef4444");
  return {
    series: [{
      type: "gauge",
      startAngle: 210,
      endAngle: -30,
      min: 0,
      max: 120,
      radius: "94%",
      center: ["50%", "58%"],
      progress: { show: true, width: 14, itemStyle: { color } },
      axisLine: {
        lineStyle: { width: 14, color: [[1, seriesColor(9)]] },
      },
      pointer: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      anchor: { show: false },
      title: {
        offsetCenter: [0, "34%"],
        fontSize: 11,
        color: mutedColor(),
      },
      detail: {
        offsetCenter: [0, "-4%"],
        fontSize: 24,
        fontWeight: "bold" as const,
        color: labelColor(),
        formatter: (v: number) => `${Math.round(v * 10) / 10}٪`,
      },
      data: [{
        value: Math.min(p, 120),
        name: props.result.series[1]?.name ?? "درصد تحقق",
      }],
    }],
  };
});

useChart(el, option);
</script>

<template>
  <div class="h-full w-full">
    <div v-if="hasTarget" ref="el" class="w-full h-full"></div>
    <p v-else class="h-full flex items-center justify-center text-xs text-slate-400 text-center px-4">
      برای گیج، شاخص دوم (هدف) را انتخاب کنید یا در تنظیمات نمایش عدد هدف را وارد کنید.
    </p>
  </div>
</template>
