<script setup lang="ts">
/**
 * انحراف به تفکیک سرفصل — every line's variance on one zero axis.
 *
 * Plotted by effect on cash, so the left half (in RTL, the side the eye
 * reaches second) always cost money and the right half always saved it,
 * whichever direction the line flows: an inflow that came in short and an
 * overspend both land on the «به ضرر» side. Bars are lengths from a shared
 * centre — the largest variance sets the scale — with plan, actual and the
 * percentage printed beside each, so the chart is also the table.
 */
import { computed, ref } from "vue";
import type { ActualSource, Direction, Verdict } from "@/api/budget";
import { useMoney } from "@/composables/useMoney";
import SignedMoney from "./SignedMoney.vue";

const props = withDefaults(defineProps<{
  title: string;
  rows: {
    label: string;
    direction: Direction;
    budget: number;
    actual: number;
    /** Signed by effect on cash: + saved / brought more, − cost. */
    effect: number;
    verdict: Verdict;
    material?: boolean;
    note?: string;
    source?: ActualSource;
  }[];
  limit?: number;
}>(), { limit: 12 });

const { money } = useMoney();
const FA = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 0 });
const showAll = ref(false);
const onlyMaterial = ref(false);

const sorted = computed(() =>
  [...props.rows]
    .filter((r) => r.effect !== 0 && (!onlyMaterial.value || r.material))
    .sort((a, b) => Math.abs(b.effect) - Math.abs(a.effect)),
);
const shown = computed(() => (showAll.value ? sorted.value : sorted.value.slice(0, props.limit)));
const max = computed(() => Math.max(1, ...sorted.value.map((r) => Math.abs(r.effect))));
// 72% of the half at most: the label printed past the bar end must still fit.
const width = (v: number) => `${(Math.abs(v) / max.value) * 72}%`;
const pct = (r: { budget: number; actual: number }) =>
  r.budget ? ((r.actual - r.budget) / Math.abs(r.budget)) * 100 : null;
const sign = (v: number) => (v > 0 ? "+" : v < 0 ? "−" : "");

const gain = computed(() => sorted.value.filter((r) => r.effect > 0).reduce((s, r) => s + r.effect, 0));
const loss = computed(() => sorted.value.filter((r) => r.effect < 0).reduce((s, r) => s + r.effect, 0));
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <div class="flex flex-wrap items-start justify-between gap-2 mb-3">
      <div>
        <h3 class="text-sm font-semibold text-ink">{{ title }}</h3>
        <p class="text-[11px] text-slate-400 mt-0.5">اثر هر سرفصل بر نقدینگی — راست: به نفع، چپ: به ضرر</p>
      </div>
      <label class="flex items-center gap-1.5 text-[11px] text-slate-500">
        <input v-model="onlyMaterial" type="checkbox" /> فقط انحراف‌های مهم
      </label>
    </div>

    <div v-if="!sorted.length" class="text-xs text-slate-400 text-center py-10">انحرافی برای نمایش نیست.</div>

    <template v-else>
      <!-- Axis legend -->
      <div class="grid grid-cols-[minmax(7rem,1.1fr)_2.4fr_auto] gap-x-3 text-[10px] text-slate-400 pb-1 border-b border-slate-100 dark:border-white/5">
        <span>سرفصل</span>
        <div class="grid grid-cols-2">
          <span class="text-emerald-700 dark:text-emerald-400">▲ به نفع نقدینگی {{ money(gain, false) }}</span>
          <span class="text-left text-rose-700 dark:text-rose-400">{{ money(Math.abs(loss), false) }} به ضرر ▼</span>
        </div>
        <span class="w-24 text-left">بودجه ← واقعی</span>
      </div>

      <ul>
        <li
          v-for="r in shown" :key="`${r.label}-${r.direction}`"
          class="group grid grid-cols-[minmax(7rem,1.1fr)_2.4fr_auto] gap-x-3 items-center py-1.5 border-b border-slate-50 dark:border-white/5 hover:bg-slate-50/70 dark:hover:bg-white/5"
        >
          <div class="min-w-0">
            <p class="text-xs text-ink truncate" :title="r.label">
              <span v-if="r.material" class="text-amber-500" title="انحراف مهم">●</span>
              {{ r.label }}
            </p>
            <p class="text-[10px] text-slate-400 truncate">
              {{ r.direction === 'in' ? 'ورودی' : 'خروجی' }}
              <template v-if="r.source === 'ledger'"> · از دفتر نقدینگی</template>
              <template v-if="r.note"> · {{ r.note }}</template>
            </p>
          </div>

          <!-- Diverging bar around the centre line -->
          <div class="relative h-6 grid grid-cols-2" :title="`${r.label}: ${sign(r.effect)}${money(Math.abs(r.effect))}`">
            <div class="relative">
              <div
                v-if="r.effect > 0"
                class="absolute inset-y-1 left-0 rounded-r-[4px] bg-emerald-500"
                :style="{ width: width(r.effect) }"
              ></div>
              <span
                v-if="r.effect > 0"
                class="absolute inset-y-0 flex items-center text-[10px] font-semibold text-emerald-700 dark:text-emerald-400 whitespace-nowrap"
                :style="{ left: `calc(${width(r.effect)} + 4px)` }"
              ><SignedMoney :value="r.effect" signed /></span>
            </div>
            <div class="relative">
              <div
                v-if="r.effect < 0"
                class="absolute inset-y-1 right-0 rounded-l-[4px] bg-rose-500"
                :style="{ width: width(r.effect) }"
              ></div>
              <span
                v-if="r.effect < 0"
                class="absolute inset-y-0 flex items-center text-[10px] font-semibold text-rose-700 dark:text-rose-400 whitespace-nowrap"
                :style="{ right: `calc(${width(r.effect)} + 4px)` }"
              ><SignedMoney :value="r.effect" signed /></span>
            </div>
            <div class="absolute inset-y-0 left-1/2 w-px bg-slate-300 dark:bg-white/20"></div>
          </div>

          <div class="w-24 text-left leading-tight">
            <p class="text-[10px] text-slate-400 whitespace-nowrap">{{ money(r.budget, false) }} ←</p>
            <p class="text-[11px] text-ink whitespace-nowrap">
              {{ money(r.actual, false) }}
              <bdi
                v-if="pct(r) !== null" dir="ltr" class="text-[10px]"
                :class="r.verdict === 'good' ? 'text-emerald-700 dark:text-emerald-400' : r.verdict === 'bad' ? 'text-rose-700 dark:text-rose-400' : 'text-slate-400'"
              >{{ sign(pct(r)!) }}{{ FA.format(Math.abs(pct(r)!)) }}٪</bdi>
            </p>
          </div>
        </li>
      </ul>

      <button
        v-if="sorted.length > limit"
        class="mt-2 text-xs text-brand-700 hover:underline"
        @click="showAll = !showAll"
      >{{ showAll ? 'نمایش کمتر' : `همهٔ ${FA.format(sorted.length)} سرفصل` }}</button>
    </template>
  </div>
</template>
