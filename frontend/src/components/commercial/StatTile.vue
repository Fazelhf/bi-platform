<script setup lang="ts">
/**
 * One figure on the بازرگانی dashboard.
 *
 * `KpiCard` takes a `KpiResult` off the KPI fact table; these numbers are
 * computed straight from purchase orders and have no KPI row, so they get a
 * plain tile rather than a fake KPI object.
 */
withDefaults(defineProps<{
  label: string;
  value: string;
  hint?: string;
  /** Month-over-month movement. Null means there is no honest comparison. */
  changePct?: number | null;
  /** For spend, a rise is bad news; for order counts it is neutral. */
  riseIsGood?: boolean | null;
}>(), { hint: "", changePct: null, riseIsGood: null });

const FA = new Intl.NumberFormat("fa-IR");

function arrow(v: number): string {
  return v > 0 ? "▲" : v < 0 ? "▼" : "•";
}

function tone(v: number, riseIsGood: boolean | null): string {
  if (riseIsGood === null || v === 0) return "text-slate-400";
  const good = v > 0 ? riseIsGood : !riseIsGood;
  return good ? "text-emerald-600" : "text-red-500";
}

function fmt(v: number): string {
  return `${FA.format(Math.abs(Number(v.toFixed(1))))}٪`;
}
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <p class="text-sm text-slate-500 mb-1">{{ label }}</p>
    <p class="text-2xl font-bold text-ink ltr-nums">{{ value }}</p>
    <p v-if="hint" class="text-xs text-slate-400 mt-1 truncate">{{ hint }}</p>
    <p
      v-if="changePct !== null && changePct !== undefined"
      class="text-xs mt-1 ltr-nums"
      :class="tone(changePct, riseIsGood)"
    >
      {{ arrow(changePct) }} {{ fmt(changePct) }}
      <span class="text-slate-400">نسبت به ماه قبل</span>
    </p>
  </div>
</template>
