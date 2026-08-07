<script setup lang="ts">
/**
 * میانگین موجودی per period, each column split into the accounts that make
 * it up — so «کدام حساب پول را نگه داشته» is answerable from the same chart
 * that answers «چقدر نگه داشتیم».
 *
 * A period nobody has recorded yet is drawn hollow rather than as a real
 * zero, because "we held nothing" and "nobody has entered it" are different
 * statements and a solid zero column says the first while meaning the second.
 */
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { useMoney } from "@/composables/useMoney";
import { AXIS, TOOLTIP, seriesColor, labelColor } from "./theme";
import type { TrendRow } from "@/api/finance";

const props = withDefaults(defineProps<{
  title: string;
  rows: TrendRow[];
  /** Draw the closing balance as a line over the stacked averages. */
  showClosing?: boolean;
  height?: number;
}>(), { showClosing: true, height: 320 });

const el = ref<HTMLElement | null>(null);
const { toUnit, unitLabel, compact } = useMoney();

/** Every account that appears anywhere, so the stack keeps a stable order. */
const accounts = computed(() => {
  const seen = new Map<string, { key: string; title: string; color: string }>();
  for (const row of props.rows) {
    for (const slice of row.by_account) {
      const key = String(slice.id ?? "none");
      if (!seen.has(key)) {
        seen.set(key, { key, title: slice.title, color: slice.color });
      }
    }
  }
  return [...seen.values()];
});

const categories = computed(() => props.rows.map((r) => r.label));

const option = computed<EChartsOption>(() => {
  const list = accounts.value;
  const series: any[] = list.map((account, i) => ({
    name: account.title,
    type: "bar",
    stack: "balance",
    barMaxWidth: 46,
    itemStyle: {
      color: account.color || seriesColor(i),
      borderRadius: i === list.length - 1 ? [6, 6, 0, 0] : 0,
    },
    data: props.rows.map((row) => {
      if (row.has_data === false) return null;
      const slice = row.by_account.find(
        (s) => String(s.id ?? "none") === account.key,
      );
      return slice ? toUnit(slice.amount) : 0;
    }),
  }));

  if (props.showClosing) {
    series.push({
      name: "موجودی پایان دوره",
      type: "line",
      smooth: true,
      symbolSize: 7,
      lineStyle: { width: 2, type: "dashed" },
      itemStyle: { color: labelColor() },
      data: props.rows.map((r) =>
        r.has_data === false ? null : toUnit(r.closing_rial),
      ),
    });
  }

  return {
    grid: { top: 46, right: 16, bottom: 30, left: 58 },
    legend: {
      top: 4, type: "scroll", icon: "roundRect",
      itemWidth: 10, itemHeight: 10,
      textStyle: { color: labelColor(), fontSize: 11 },
    },
    tooltip: {
      ...TOOLTIP,
      trigger: "axis",
      axisPointer: { type: "shadow" },
      // A plain axis tooltip prints one row per series. With fourteen accounts
      // that is a fourteen-row wall, mostly zeros, taller than the chart — and
      // the question it should answer («کدام حساب پول را نگه داشته») is the
      // one thing it buries. So: the total first, then the accounts that
      // actually hold something, biggest first, and the long tail collapsed
      // into a single line.
      formatter: (params: any) => {
        const items = Array.isArray(params) ? params : [params];
        if (!items.length) return "";

        const closing = items.find((p: any) => p.seriesType === "line");
        const bars = items
          .filter((p: any) => p.seriesType !== "line")
          .filter((p: any) => Number(p.value) > 0)
          .sort((a: any, b: any) => Number(b.value) - Number(a.value));

        const total = bars.reduce((s: number, p: any) => s + Number(p.value), 0);
        const head = `<div style="font-weight:600;margin-bottom:4px">${items[0].axisValue}</div>`;

        if (!bars.length) {
          return head + '<div style="opacity:.7">ثبت نشده</div>';
        }

        const row = (dot: string, name: string, value: string, dim = false) =>
          `<div style="display:flex;align-items:center;gap:6px;${dim ? "opacity:.65;" : ""}">`
          + dot
          + `<span style="flex:1">${name}</span>`
          + `<span style="font-weight:600;direction:ltr">${value}</span></div>`;

        const SHOWN = 6;
        const top = bars.slice(0, SHOWN);
        const rest = bars.slice(SHOWN);

        const lines = top.map((p: any) =>
          row(p.marker, p.seriesName, compact(Number(p.value))),
        );

        if (rest.length) {
          const restSum = rest.reduce((s: number, p: any) => s + Number(p.value), 0);
          lines.push(row(
            '<span style="display:inline-block;width:10px"></span>',
            `${rest.length} حساب دیگر`,
            compact(restSum),
            true,
          ));
        }

        const totalRow = row(
          '<span style="display:inline-block;width:10px"></span>',
          "مجموع",
          compact(total),
        );
        const closingRow = closing && closing.value !== null && closing.value !== undefined
          ? row(closing.marker, closing.seriesName, compact(Number(closing.value)), true)
          : "";

        return head
          + `<div style="margin-bottom:4px;padding-bottom:4px;border-bottom:1px solid rgba(128,128,128,.25)">${totalRow}</div>`
          + lines.join("")
          + (closingRow
            ? `<div style="margin-top:4px;padding-top:4px;border-top:1px solid rgba(128,128,128,.25)">${closingRow}</div>`
            : "");
      },
    },
    xAxis: { ...AXIS.category, data: categories.value },
    yAxis: {
      ...AXIS.value,
      name: unitLabel.value,
      nameTextStyle: { color: labelColor(), fontSize: 10, padding: [0, 0, 0, 30] },
      axisLabel: {
        ...AXIS.value.axisLabel,
        formatter: (v: number) => compact(v),
      },
    },
    series,
  };
});

useChart(el, option);
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <div class="flex items-baseline justify-between gap-2 mb-1">
      <h3 class="font-semibold text-ink text-sm">{{ title }}</h3>
      <span class="text-[11px] text-slate-400">ارقام به {{ unitLabel }}</span>
    </div>
    <div v-if="!rows.length" class="py-12 text-center text-sm text-slate-400">
      داده‌ای برای نمایش نیست.
    </div>
    <div v-else ref="el" :style="{ height: `${height}px` }"></div>
  </div>
</template>
