<script setup lang="ts">
import NavIcon from "@/components/NavIcon.vue";

withDefaults(defineProps<{
  label: string;
  value: string | number;
  icon?: string;
  hint?: string;
  tone?: "neutral" | "brand" | "good" | "warn" | "bad";
}>(), { tone: "neutral", icon: "grid" });

const TONES: Record<string, string> = {
  neutral: "bg-slate-100 text-slate-500",
  brand: "bg-brand-50 text-brand-600",
  good: "bg-accent-50 text-accent-600",
  warn: "bg-amber-50 text-amber-600",
  bad: "bg-red-50 text-red-500",
};
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4 flex items-center gap-3">
    <span class="w-11 h-11 rounded-2xl grid place-items-center shrink-0" :class="TONES[tone]">
      <NavIcon :name="icon" :size="20" />
    </span>
    <div class="min-w-0">
      <p class="text-xs text-slate-400 truncate">{{ label }}</p>
      <p class="text-xl font-bold text-ink ltr-nums truncate">{{ value }}</p>
      <p v-if="hint" class="text-[11px] text-slate-400 truncate">{{ hint }}</p>
    </div>
  </div>
</template>
