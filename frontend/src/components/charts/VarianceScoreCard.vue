<script setup lang="ts">
/**
 * One measure of the budget, read the way a finance team reads it: what
 * happened, against what was planned, by how much — and whether that has
 * been the pattern all year.
 *
 * Three layers, top to bottom:
 *
 * * the actual as the headline, the plan beside it, the variance as a signed
 *   amount and percent with its verdict in words and an arrow (never colour
 *   alone — over plan is good news for money in and bad news for money out);
 * * a bullet: the actual as a bar, the plan as a vertical mark across it, so
 *   «how far off» is a length, not an angle on a dial;
 * * the variance month by month as small columns around zero, the selected
 *   month outlined — one bad month and a bad trend look different here.
 */
import { computed } from "vue";
import type { Verdict } from "@/api/budget";
import { useMoney } from "@/composables/useMoney";
import SignedMoney from "./SignedMoney.vue";

const props = defineProps<{
  title: string;
  budget: number;
  actual: number;
  verdict: Verdict;
  /** Short line under the title, e.g. the data source. */
  hint?: string;
  /** Monthly variance, oldest first; `current` marks the month on screen. */
  trend?: { label: string; variance: number; verdict: Verdict; current?: boolean; empty?: boolean }[];
  /** Hide the bullet when plan/actual are not on one scale (net cash can be negative). */
  bullet?: boolean;
}>();

const { money } = useMoney();
const FA = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });

const variance = computed(() => props.actual - props.budget);
const pct = computed(() => (props.budget ? (variance.value / Math.abs(props.budget)) * 100 : null));

const tone = computed(() =>
  props.verdict === "good"
    ? { text: "text-emerald-700 dark:text-emerald-400", chip: "bg-emerald-500/10", bar: "bg-emerald-500", word: "مطلوب" }
    : props.verdict === "bad"
      ? { text: "text-rose-700 dark:text-rose-400", chip: "bg-rose-500/10", bar: "bg-rose-500", word: "نامطلوب" }
      : { text: "text-slate-500", chip: "bg-slate-500/10", bar: "bg-slate-400", word: "طبق برنامه" },
);
const arrow = computed(() => (variance.value > 0 ? "▲" : variance.value < 0 ? "▼" : "●"));

// Bullet scale: a little headroom past the larger of the two.
const scale = computed(() => Math.max(Math.abs(props.budget), Math.abs(props.actual)) * 1.08 || 1);
const actualW = computed(() => `${Math.min(100, (Math.abs(props.actual) / scale.value) * 100)}%`);
const planX = computed(() => `${Math.min(100, (Math.abs(props.budget) / scale.value) * 100)}%`);
const ratio = computed(() => (props.budget ? (props.actual / props.budget) * 100 : null));

// Trend: columns around a zero line, heights relative to the largest month.
const trendMax = computed(() => Math.max(1, ...(props.trend ?? []).map((t) => Math.abs(t.variance))));
const H = 34;
const bars = computed(() => {
  const list = props.trend ?? [];
  const w = list.length ? 100 / list.length : 0;
  return list.map((t, i) => {
    const h = t.empty ? 0 : Math.max(1.5, (Math.abs(t.variance) / trendMax.value) * (H / 2 - 2));
    const y = t.variance >= 0 ? H / 2 - h : H / 2;
    return { ...t, x: i * w + w * 0.18, w: w * 0.64, y, h };
  });
});
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4 flex flex-col gap-3">
    <div class="flex items-start justify-between gap-2">
      <div class="min-w-0">
        <p class="text-xs font-semibold text-ink">{{ title }}</p>
        <p v-if="hint" class="text-[10px] text-slate-400 mt-0.5 truncate" :title="hint">{{ hint }}</p>
      </div>
      <span class="shrink-0 px-2 py-0.5 rounded-full text-[10px] font-medium" :class="[tone.chip, tone.text]">
        {{ arrow }} {{ tone.word }}
      </span>
    </div>

    <div class="flex items-end justify-between gap-2">
      <div>
        <p class="text-[10px] text-slate-400">واقعی</p>
        <p class="text-xl font-extrabold text-ink leading-tight">{{ money(actual, false) }}</p>
      </div>
      <div class="text-left">
        <p class="text-[10px] text-slate-400">بودجه</p>
        <p class="text-sm font-semibold text-slate-500">{{ money(budget, false) }}</p>
      </div>
    </div>

    <div class="flex items-baseline gap-2" :class="tone.text">
      <SignedMoney class="text-base font-bold" :value="variance" signed :pct="pct" />
      <span class="text-[10px] text-slate-400">انحراف</span>
    </div>

    <!-- Bullet: actual bar, plan mark -->
    <div v-if="bullet !== false && (budget || actual)" class="space-y-1">
      <div class="relative h-2.5 rounded-full bg-slate-100 dark:bg-white/5 overflow-visible" role="img"
        :aria-label="`واقعی ${money(actual)} در برابر بودجه ${money(budget)}`">
        <div class="absolute inset-y-0 right-0 rounded-full" :class="tone.bar" :style="{ width: actualW }"></div>
        <div class="absolute -top-1 -bottom-1 w-0.5 rounded bg-ink" :style="{ right: planX }" title="بودجه"></div>
      </div>
      <div class="flex justify-between text-[10px] text-slate-400">
        <span>{{ ratio === null ? 'بدون بودجه' : `${FA.format(ratio)}٪ بودجه` }}</span>
        <span class="flex items-center gap-1"><span class="inline-block w-0.5 h-2.5 bg-ink rounded"></span> بودجه</span>
      </div>
    </div>

    <!-- Monthly variance -->
    <div v-if="bars.length > 1" class="pt-1 border-t border-slate-100 dark:border-white/5">
      <p class="text-[10px] text-slate-400 mb-1">انحراف ماه‌به‌ماه</p>
      <svg :viewBox="`0 0 100 ${H}`" preserveAspectRatio="none" class="w-full h-9 overflow-visible">
        <line x1="0" :y1="H / 2" x2="100" :y2="H / 2" class="stroke-slate-300 dark:stroke-white/20" stroke-width="0.4" vector-effect="non-scaling-stroke" />
        <g v-for="b in bars" :key="b.label">
          <rect
            :x="b.x" :y="b.y" :width="b.w" :height="b.h" rx="0.8"
            :class="b.empty ? 'fill-slate-200' : b.verdict === 'good' ? 'fill-emerald-500' : b.verdict === 'bad' ? 'fill-rose-500' : 'fill-slate-400'"
            :opacity="b.current ? 1 : 0.55"
          >
            <title>{{ b.label }}: {{ b.empty ? 'بدون رقم واقعی' : `${money(b.variance, false)}` }}</title>
          </rect>
        </g>
      </svg>
      <div class="flex justify-between text-[9px] text-slate-400 mt-0.5">
        <span>{{ trend?.[trend.length - 1]?.label }}</span>
        <span>{{ trend?.[0]?.label }}</span>
      </div>
    </div>
  </div>
</template>
