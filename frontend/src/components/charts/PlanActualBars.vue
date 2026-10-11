<script setup lang="ts">
/**
 * Plan against actual, one bullet per row — groups of the budget, or sales
 * channels.
 *
 * The actual is the bar; the plan is a dark vertical mark on the same scale.
 * Where the bar stops short of the mark or runs past it is the variance,
 * printed beside it with its verdict, so nothing depends on colour alone.
 * One shared scale for every row: a small group cannot look as big as a
 * large one.
 */
import { computed } from "vue";
import type { Verdict } from "@/api/budget";
import { useMoney } from "@/composables/useMoney";
import SignedMoney from "./SignedMoney.vue";

const props = defineProps<{
  title: string;
  subtitle?: string;
  items: { label: string; budget: number; actual: number; verdict: Verdict; hint?: string; note?: string }[];
  empty?: string;
}>();

const { money } = useMoney();
const FA = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 0 });

const max = computed(() => Math.max(1, ...props.items.flatMap((i) => [Math.abs(i.budget), Math.abs(i.actual)])) * 1.05);
const w = (v: number) => `${Math.min(100, (Math.abs(v) / max.value) * 100)}%`;
const pct = (i: { budget: number; actual: number }) => (i.budget ? (i.actual / i.budget) * 100 : null);
const toneText = (v: Verdict) =>
  v === "good" ? "text-emerald-700 dark:text-emerald-400" : v === "bad" ? "text-rose-700 dark:text-rose-400" : "text-slate-500";
const toneBar = (v: Verdict) => (v === "good" ? "bg-emerald-500" : v === "bad" ? "bg-rose-500" : "bg-slate-400");
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <div class="flex flex-wrap items-start justify-between gap-2 mb-3">
      <div>
        <h3 class="text-sm font-semibold text-ink">{{ title }}</h3>
        <p v-if="subtitle" class="text-[11px] text-slate-400 mt-0.5">{{ subtitle }}</p>
      </div>
      <div class="flex items-center gap-3 text-[10px] text-slate-400">
        <span class="flex items-center gap-1"><span class="inline-block w-3 h-2 rounded-sm bg-slate-400"></span> واقعی</span>
        <span class="flex items-center gap-1"><span class="inline-block w-0.5 h-3 rounded bg-ink"></span> بودجه</span>
      </div>
    </div>

    <p v-if="!items.length" class="text-xs text-slate-400 text-center py-8">{{ empty ?? 'داده‌ای برای نمایش نیست.' }}</p>

    <ul class="space-y-3">
      <li v-for="i in items" :key="i.label">
        <div class="flex items-baseline justify-between gap-2 mb-1">
          <p class="text-xs text-ink truncate" :title="i.hint || i.label">{{ i.label }}</p>
          <p class="text-[11px] whitespace-nowrap">
            <span class="text-ink font-semibold">{{ money(i.actual, false) }}</span>
            <span class="text-slate-400"> / {{ money(i.budget, false) }}</span>
            <span class="ms-1.5 font-semibold" :class="toneText(i.verdict)">
              <SignedMoney :value="i.actual - i.budget" signed />
              <template v-if="pct(i) !== null"> · {{ FA.format(pct(i)!) }}٪</template>
            </span>
          </p>
        </div>
        <p v-if="i.note" class="text-[10px] text-amber-600 -mt-0.5 mb-1">{{ i.note }}</p>
        <div class="relative h-3 rounded bg-slate-100 dark:bg-white/5" role="img"
          :aria-label="`${i.label}: واقعی ${money(i.actual)} از بودجه ${money(i.budget)}`">
          <div class="absolute inset-y-0 right-0 rounded" :class="toneBar(i.verdict)" :style="{ width: w(i.actual) }"></div>
          <div v-if="i.budget" class="absolute -top-1 -bottom-1 w-0.5 rounded bg-ink" :style="{ right: w(i.budget) }"></div>
        </div>
      </li>
    </ul>
  </div>
</template>
