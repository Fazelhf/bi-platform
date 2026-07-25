<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { COLORS, TOOLTIP } from "./theme";

// درصد بهره‌وری — value (green) vs remaining gap (light), colour-cued by level.
const props = defineProps<{ title: string; value: number | null }>();

const el = ref<HTMLElement | null>(null);
const pct = computed(() => Math.max(0, Math.min(100, Number(props.value ?? 0))));
const color = computed(() => (pct.value >= 90 ? COLORS.target : pct.value >= 60 ? "#f59e0b" : COLORS.rose));

const option = computed<EChartsOption>(() => ({
  tooltip: { ...TOOLTIP, trigger: "item", formatter: "{b}: {c}٪" },
  series: [
    {
      type: "pie",
      radius: ["62%", "84%"],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 8, borderColor: "#fff", borderWidth: 3 },
      label: {
        show: true, position: "center",
        formatter: () => `${pct.value.toFixed(1)}٪`,
        fontSize: 24, fontWeight: "bold", color: COLORS.ink,
      },
      data: [
        { value: pct.value, name: "بهره‌وری", itemStyle: { color: color.value } },
        { value: 100 - pct.value, name: "فاصله تا ایده‌آل", itemStyle: { color: "#eef1f4" } },
      ],
    },
  ],
}));

useChart(el, option);
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink mb-1 text-center">{{ title }}</h3>
    <div ref="el" style="height: 210px"></div>
  </div>
</template>
