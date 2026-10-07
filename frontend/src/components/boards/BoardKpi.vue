<script setup lang="ts">
import { computed } from "vue";
import type { QueryResult, WidgetOptions } from "@/api/dashboards";
import { byUnit } from "./format";
import { pct } from "@/utils/format";

/**
 * A single figure, and — when the manager gave it a second metric — something
 * to judge it by.
 *
 * A number on its own cannot answer "is this good?", which is the only
 * question a KPI tile exists to answer. So the second metric is not decoration:
 * picking «فروش» and «تارگت» turns the same card from a readout into a verdict.
 */
const props = withDefaults(defineProps<{
  kind: "kpi" | "progress";
  result: QueryResult;
  options?: WidgetOptions;
}>(), { options: () => ({}) });

const primary = computed(() => props.result.series[0] ?? null);
const secondary = computed(() => props.result.series[1] ?? null);

const value = computed(() => primary.value?.values[0] ?? 0);
const against = computed(() => secondary.value?.values[0] ?? 0);

const ratio = computed(() => (against.value ? (value.value / against.value) * 100 : null));

/** Traffic light, in the same bands the rest of the platform uses. */
const tone = computed(() => {
  const r = ratio.value;
  if (r === null) return "neutral";
  if (r >= 100) return "good";
  if (r >= 70) return "warn";
  return "bad";
});

const toneText = {
  good: "text-green-600",
  warn: "text-amber-600",
  bad: "text-red-500",
  neutral: "text-slate-400",
} as const;

const toneBar = {
  good: "bg-green-500",
  warn: "bg-amber-500",
  bad: "bg-red-500",
  neutral: "bg-brand-500",
} as const;
</script>

<template>
  <div class="h-full flex flex-col justify-center" :class="options.align === 'center' ? 'items-center text-center' : ''">
    <!-- «تحقق تارگت» leads with the percentage — that is its answer; the
         amounts behind it are the line underneath. -->
    <p
      class="font-extrabold ltr-nums leading-tight whitespace-nowrap truncate text-2xl 2xl:text-3xl"
      :class="kind === 'progress' && secondary ? toneText[tone] : 'text-ink'"
      :style="options.color ? { color: options.color } : {}"
    >
      <template v-if="kind === 'progress' && secondary">{{ ratio === null ? "—" : pct(ratio) }}</template>
      <template v-else>{{ primary ? byUnit(value, primary.unit) : "—" }}</template>
    </p>
    <p v-if="primary && !(kind === 'progress' && secondary)" class="text-xs text-slate-400 mt-1">{{ primary.name }}</p>

    <template v-if="secondary">
      <div v-if="kind === 'progress'" class="mt-3">
        <div class="h-2 rounded-full bg-slate-100 overflow-hidden">
          <div
            class="h-full rounded-full transition-all duration-500"
            :class="toneBar[tone]"
            :style="{ width: Math.min(Math.max(ratio ?? 0, 0), 100) + '%' }"
          ></div>
        </div>
        <div class="flex justify-between items-baseline mt-1.5 text-[11px]">
          <span class="ltr-nums text-slate-500">
            {{ primary!.name }} {{ byUnit(value, primary!.unit) }}
          </span>
          <span class="text-slate-400 ltr-nums">
            {{ secondary.name }} {{ byUnit(against, secondary.unit) }}
          </span>
        </div>
      </div>

      <p v-else class="text-xs mt-1.5 ltr-nums" :class="toneText[tone]">
        {{ ratio === null ? "" : `${pct(ratio)} از ${secondary.name}` }}
        <span class="text-slate-400">{{ byUnit(against, secondary.unit) }}</span>
      </p>
    </template>
  </div>
</template>
