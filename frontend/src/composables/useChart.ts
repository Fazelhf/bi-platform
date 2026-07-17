import * as echarts from "echarts";
import { onBeforeUnmount, onMounted, ref, watch, type Ref } from "vue";

/**
 * Minimal ECharts wrapper: pass a ref to a DOM element and a reactive
 * option object; the chart initialises, resizes, and disposes itself.
 */
export function useChart(
  el: Ref<HTMLElement | null>,
  option: Ref<echarts.EChartsOption>,
) {
  let chart: echarts.ECharts | null = null;
  const ready = ref(false);

  function resize() {
    chart?.resize();
  }

  onMounted(() => {
    if (!el.value) return;
    chart = echarts.init(el.value, undefined, { renderer: "canvas" });
    chart.setOption(option.value);
    ready.value = true;
    window.addEventListener("resize", resize);
  });

  watch(
    option,
    (o) => chart?.setOption(o, true),
    { deep: true },
  );

  onBeforeUnmount(() => {
    window.removeEventListener("resize", resize);
    chart?.dispose();
    chart = null;
  });

  return { ready };
}
