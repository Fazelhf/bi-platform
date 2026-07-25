<script setup lang="ts">
import { computed } from "vue";
import type { KpiResult } from "@/types";
import { kpiValue } from "@/utils/format";

const props = defineProps<{ kpi: KpiResult }>();

const eff = computed(() => {
  const v = props.kpi.efficiency_pct;
  return v === null ? null : Number(v);
});

// Colour the efficiency bar: green near/above ideal, amber mid, red low.
const barColor = computed(() => {
  const e = eff.value;
  if (e === null) return "#cbd5e1";
  if (e >= 90) return "#16a34a";
  if (e >= 60) return "#d97706";
  return "#dc2626";
});

const barWidth = computed(() => {
  const e = eff.value;
  if (e === null) return 0;
  return Math.max(0, Math.min(100, e));
});
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4 hover:shadow-pop transition-shadow duration-200">
    <div class="text-sm text-slate-500 mb-1">{{ kpi.kpi_name_fa }}</div>
    <div class="text-2xl font-bold ltr-nums text-ink">
      {{ kpiValue(kpi.actual, kpi.unit) }}
    </div>

    <div class="flex gap-4 text-xs text-slate-400 mt-2">
      <span v-if="kpi.target !== null">
        مطلوب: <span class="ltr-nums">{{ kpiValue(kpi.target, kpi.unit) }}</span>
      </span>
      <span v-if="kpi.ideal !== null">
        ایده‌آل: <span class="ltr-nums">{{ kpiValue(kpi.ideal, kpi.unit) }}</span>
      </span>
    </div>

    <div v-if="eff !== null" class="mt-3">
      <div class="h-2 rounded-full bg-slate-100 overflow-hidden">
        <div
          class="h-full rounded-full transition-all"
          :style="{ width: barWidth + '%', backgroundColor: barColor }"
        ></div>
      </div>
      <div class="text-xs mt-1 ltr-nums" :style="{ color: barColor }">
        بهره‌وری: {{ eff.toFixed(1) }}٪
      </div>
    </div>
  </div>
</template>
