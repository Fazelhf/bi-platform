<script setup lang="ts">
withDefaults(defineProps<{
  tone?: "neutral" | "brand" | "good" | "warn" | "bad" | "info";
  dot?: boolean;
}>(), { tone: "neutral" });

const TONES: Record<string, string> = {
  neutral: "bg-slate-100 text-slate-600",
  brand: "bg-brand-50 text-brand-700",
  good: "bg-accent-50 text-accent-600",
  warn: "bg-amber-50 text-amber-700",
  bad: "bg-red-50 text-red-600",
  info: "bg-sky-50 text-sky-700",
};
const DOTS: Record<string, string> = {
  neutral: "bg-slate-400", brand: "bg-brand-600", good: "bg-accent-500",
  warn: "bg-amber-500", bad: "bg-red-500", info: "bg-sky-500",
};
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap"
    :class="TONES[tone]"
  >
    <span v-if="dot" class="w-1.5 h-1.5 rounded-full" :class="DOTS[tone]"></span>
    <slot />
  </span>
</template>
