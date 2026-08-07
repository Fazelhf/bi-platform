import { init, type EChartsOption, type EChartsType } from "@/lib/echarts";
import { onBeforeUnmount, onMounted, ref, watch, type Ref } from "vue";

/**
 * Minimal ECharts wrapper: pass a ref to a DOM element and a reactive
 * option object; the chart initialises, resizes, and disposes itself.
 */
export function useChart(
  el: Ref<HTMLElement | null>,
  option: Ref<EChartsOption>,
) {
  // A ref, not a plain local: callers that want to attach their own handlers
  // (a click that opens a drill-down) need to know *when* the instance exists,
  // and onMounted has already run by the time they could check.
  const chart = ref<EChartsType | null>(null);
  const ready = ref(false);

  function resize() {
    chart.value?.resize();
  }

  onMounted(() => {
    if (!el.value) return;
    chart.value = init(el.value, undefined, { renderer: "canvas" });
    chart.value.setOption(option.value);
    ready.value = true;
    window.addEventListener("resize", resize);
  });

  watch(
    option,
    (o) => chart.value?.setOption(o, true),
    { deep: true },
  );

  onBeforeUnmount(() => {
    window.removeEventListener("resize", resize);
    chart.value?.dispose();
    chart.value = null;
  });

  return { ready, chart };
}
