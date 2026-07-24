<script setup lang="ts">
import { computed } from "vue";
import type { KpiResult } from "@/types";
import { kpiValue } from "@/utils/format";

const props = defineProps<{ kpi: KpiResult }>();

const display = computed(() => kpiValue(props.kpi.actual, props.kpi.unit));

// Colour by target achievement when we have a target, else neutral.
const accent = computed(() => {
  if (props.kpi.kpi_code === "cost_to_sales") return "text-amber-600";
  return "text-brand-600";
});
</script>

<template>
  <div class="bg-white rounded-card shadow-soft p-4 hover:shadow-pop transition-shadow duration-200">
    <div class="text-sm text-slate-500 mb-1">{{ kpi.kpi_name_fa }}</div>
    <div class="text-2xl font-bold ltr-nums" :class="accent">{{ display }}</div>
    <div class="text-xs text-slate-400 mt-1">{{ kpi.kpi_name_en }}</div>
  </div>
</template>
