<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";

// درصد بهره‌وری — a donut of value vs the remaining gap to 100%.
const props = defineProps<{ title: string; value: number | null }>();

const el = ref<HTMLElement | null>(null);
const pct = computed(() => Math.max(0, Math.min(100, Number(props.value ?? 0))));

const option = computed<EChartsOption>(() => ({
  tooltip: { trigger: "item", formatter: "{b}: {c}٪" },
  series: [
    {
      type: "pie",
      radius: ["58%", "82%"],
      avoidLabelOverlap: false,
      label: {
        show: true, position: "center",
        formatter: () => `${pct.value.toFixed(1)}٪`,
        fontSize: 22, fontWeight: "bold", color: "#1c1c1e",
      },
      data: [
        { value: pct.value, name: "بهره‌وری", itemStyle: { color: "#f472b6" } },
        { value: 100 - pct.value, name: "فاصله تا ایده‌آل", itemStyle: { color: "#4f7cf6" } },
      ],
    },
  ],
}));

useChart(el, option);
</script>

<template>
  <div class="bg-white rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink mb-1 text-center">{{ title }}</h3>
    <div ref="el" style="height: 220px"></div>
  </div>
</template>
