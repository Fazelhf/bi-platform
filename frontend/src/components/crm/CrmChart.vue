<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { init, type EChartsOption, type EChartsType } from "@/lib/echarts";
import { useUiStore } from "@/stores/ui";
import { AXIS, TOOLTIP, barGradient, barRadius, compact, seriesColor } from "@/components/charts/theme";
import { rial } from "@/utils/format";

/**
 * The CRM's chart. Differs from the platform's SeriesChart in one way that
 * matters: **bars are clickable**. Every point carries the index of the row
 * that produced it, so the page can open the drill-down for exactly that
 * slice. A chart you cannot interrogate is the complaint that started this
 * whole rebuild.
 */
const props = withDefaults(defineProps<{
  categories: string[];
  series: { name: string; values: (number | null)[]; type?: "bar" | "line"; color?: string; stack?: string }[];
  kind?: "bar" | "line" | "pie" | "hbar";
  height?: number;
  format?: "rial" | "count" | "percent" | "days";
  horizontal?: boolean;
  showLegend?: boolean;
}>(), { kind: "bar", height: 260, format: "count", horizontal: false, showLegend: true });

const emit = defineEmits<{ (e: "pick", index: number, seriesName: string): void }>();

const ui = useUiStore();
const el = ref<HTMLElement | null>(null);
let chart: EChartsType | null = null;

function fmt(v: number): string {
  if (props.format === "rial") return rial(v);
  if (props.format === "percent") return `${Math.round(v * 10) / 10}٪`;
  if (props.format === "days") return `${Math.round(v * 10) / 10} روز`;
  return compact(v);
}

const option = computed<EChartsOption>(() => {
  void ui.chartTheme;
  void ui.dark;
  const multi = props.series.length > 1;

  if (props.kind === "pie") {
    return {
      tooltip: { ...TOOLTIP, trigger: "item", formatter: (p: any) => `${p.name}<br/>${fmt(p.value)} (${p.percent}٪)` },
      legend: { bottom: 0, itemWidth: 9, itemHeight: 9, textStyle: { fontSize: 10, color: "#94a3b8" } },
      series: [{
        type: "pie", radius: ["48%", "72%"], center: ["50%", "45%"],
        itemStyle: { borderRadius: 6, borderWidth: 2, borderColor: "transparent" },
        label: { show: false },
        data: props.categories.map((c, i) => ({
          name: c, value: props.series[0]?.values[i] ?? 0,
          itemStyle: { color: props.series[0]?.color ?? seriesColor(i) },
        })),
      }],
    };
  }

  const valueAxis = {
    ...AXIS.value,
    axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => fmt(v) },
  };
  const catAxis = {
    ...AXIS.category,
    data: props.categories,
    axisLabel: {
      ...AXIS.category.axisLabel,
      fontSize: 10,
      rotate: props.horizontal ? 0 : (props.categories.some((c) => c.length > 9) ? 32 : 0),
      width: props.horizontal ? 110 : undefined,
      overflow: props.horizontal ? ("truncate" as const) : undefined,
    },
  };

  return {
    grid: props.horizontal
      ? { top: 10, right: 60, bottom: 8, left: 8, containLabel: true }
      : { top: multi && props.showLegend ? 30 : 16, right: 12, bottom: 8, left: 8, containLabel: true },
    tooltip: { ...TOOLTIP, trigger: "axis", valueFormatter: (v: any) => fmt(Number(v)) },
    legend: multi && props.showLegend
      ? { top: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 10, color: "#94a3b8" } }
      : undefined,
    xAxis: props.horizontal ? valueAxis : catAxis,
    yAxis: props.horizontal ? { ...catAxis, inverse: true } : valueAxis,
    series: props.series.map((s, i) => {
      const color = s.color ?? seriesColor(i);
      const isLine = (s.type ?? (props.kind === "line" ? "line" : "bar")) === "line";
      return isLine
        ? {
            name: s.name, type: "line" as const, data: s.values, smooth: true,
            symbolSize: 7, lineStyle: { width: 2.5, color },
            itemStyle: { color }, areaStyle: multi ? undefined : { opacity: 0.12, color },
          }
        : {
            name: s.name, type: "bar" as const, data: s.values,
            stack: s.stack, barMaxWidth: props.horizontal ? 16 : 34,
            itemStyle: {
              color: s.stack ? color : barGradient(color),
              borderRadius: props.horizontal
                ? [0, barRadius(), barRadius(), 0]
                : [barRadius(), barRadius(), 0, 0],
            },
          };
    }),
  };
});

function mount() {
  if (!el.value) return;
  chart = init(el.value, undefined, { renderer: "canvas" });
  chart.setOption(option.value);
  chart.on("click", (p: any) => emit("pick", p.dataIndex, p.seriesName));
  // Show a pointer only where a click does something.
  chart.getZr().on("mousemove", (e: any) => {
    const hit = chart!.containPixel("grid", [e.offsetX, e.offsetY]);
    (el.value as HTMLElement).style.cursor = hit || props.kind === "pie" ? "pointer" : "default";
  });
}
function resize() { chart?.resize(); }

onMounted(() => { mount(); window.addEventListener("resize", resize); });
watch(option, (o) => chart?.setOption(o, true), { deep: true });
onBeforeUnmount(() => {
  window.removeEventListener("resize", resize);
  chart?.dispose();
  chart = null;
});
</script>

<template>
  <div ref="el" :style="{ height: height + 'px', width: '100%' }"></div>
</template>
