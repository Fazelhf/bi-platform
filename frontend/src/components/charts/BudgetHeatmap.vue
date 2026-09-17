<script setup lang="ts">
/**
 * نقشهٔ انحراف — every budget group against every month.
 *
 * Coloured by verdict, not by sign: green is good news for that side of the
 * ledger (collected more, spent less), red is bad news, and the depth of the
 * colour is how far off plan it was, capped at ±50% so one wild month does not
 * wash the rest of the grid out. Months nobody has keyed yet stay grey rather
 * than showing a false «everything under budget».
 */
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { useUiStore } from "@/stores/ui";
import { AXIS, COLORS, TOOLTIP, compact, labelColor, mutedColor, surfaceColor } from "./theme";
import type { Verdict } from "@/api/budget";

const props = defineProps<{
  title: string;
  months: { period_id: number; label: string; has_actuals: boolean }[];
  groups: { key: string; label: string; direction: "in" | "out" }[];
  cells: {
    group: string;
    period_id: number;
    budget_rial: string;
    actual_rial: string;
    variance_pct: number | null;
    verdict: Verdict;
  }[];
}>();

const ui = useUiStore();
const el = ref<HTMLElement | null>(null);
const FA = new Intl.NumberFormat("fa-IR");

const yGroups = computed(() => [...props.groups].reverse()); // first group on top
const height = computed(() => Math.max(220, 90 + props.groups.length * 34));

const option = computed<EChartsOption>(() => {
  void ui.chartTheme;
  const monthIndex = new Map(props.months.map((m, i) => [m.period_id, i]));
  const groupIndex = new Map(yGroups.value.map((g, i) => [g.key, i]));
  const keyed = new Map(props.months.map((m) => [m.period_id, m.has_actuals]));
  const lookup = new Map(props.cells.map((c) => [`${c.group}|${c.period_id}`, c]));

  const data = props.cells
    .filter((c) => monthIndex.has(c.period_id) && groupIndex.has(c.group))
    .map((c) => {
      const x = monthIndex.get(c.period_id)!;
      const y = groupIndex.get(c.group)!;
      if (!keyed.get(c.period_id) || c.variance_pct === null) return [x, y, "-"];
      const size = Math.min(Math.abs(c.variance_pct), 50);
      const score = c.verdict === "good" ? size : c.verdict === "bad" ? -size : 0;
      return [x, y, Math.round(score * 10) / 10];
    });

  return {
    grid: { top: 10, right: 16, bottom: 58, left: 8, containLabel: true },
    tooltip: {
      ...TOOLTIP,
      formatter: (p: any) => {
        const [x, y] = p.data as [number, number, number | string];
        const month = props.months[x];
        const group = yGroups.value[y];
        const cell = lookup.get(`${group?.key}|${month?.period_id}`);
        if (!month || !group || !cell) return "";
        if (!month.has_actuals) return `${group.label} · ${month.label}<br/>هنوز رقم واقعی ثبت نشده`;
        const pct = cell.variance_pct === null ? "—" : `${cell.variance_pct > 0 ? "+" : ""}${FA.format(Math.round(cell.variance_pct * 10) / 10)}٪`;
        const word = cell.verdict === "good" ? "مطلوب" : cell.verdict === "bad" ? "نامطلوب" : "طبق برنامه";
        return `${group.label} · ${month.label}<br/>بودجه ${compact(Number(cell.budget_rial))} · واقعی ${compact(Number(cell.actual_rial))}<br/>${pct} — ${word}`;
      },
    },
    xAxis: {
      ...AXIS.category,
      type: "category",
      data: props.months.map((m) => m.label),
      splitArea: { show: false },
      axisLabel: { ...AXIS.category.axisLabel, fontSize: 10 },
    },
    yAxis: {
      ...AXIS.category,
      type: "category",
      data: yGroups.value.map((g) => g.label),
      axisLabel: { ...AXIS.category.axisLabel, fontSize: 11 },
    },
    visualMap: {
      min: -50,
      max: 50,
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemWidth: 12,
      itemHeight: 160,
      text: ["مطلوب", "نامطلوب"],
      textStyle: { color: mutedColor(), fontSize: 11 },
      inRange: { color: [COLORS.rose, surfaceColor(), COLORS.target] },
      outOfRange: { color: COLORS.slate },
    },
    series: [{
      type: "heatmap",
      data,
      label: {
        show: true,
        fontSize: 10,
        color: labelColor(),
        formatter: (p: any) => {
          const v = (p.data as [number, number, number | string])[2];
          return v === "-" ? "" : `${FA.format(Math.abs(Number(v)))}٪`;
        },
      },
      itemStyle: { borderColor: surfaceColor(), borderWidth: 2, borderRadius: 4 },
      emphasis: { itemStyle: { shadowBlur: 6, shadowColor: "rgba(0,0,0,0.2)" } },
    }],
  };
});

useChart(el, option);
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink mb-1 text-center">{{ title }}</h3>
    <p class="text-[11px] text-slate-400 text-center mb-1">
      رنگ سبز یعنی به نفع نقدینگی، قرمز یعنی به ضرر؛ عدد، درصد فاصله از بودجه است (تا ۵۰٪). خاکستری: هنوز ثبت نشده.
    </p>
    <p v-if="!groups.length" class="text-xs text-slate-400 text-center py-10">این بودجه هنوز سرفصلی ندارد.</p>
    <div v-show="groups.length" ref="el" :style="{ height: height + 'px' }"></div>
  </div>
</template>
