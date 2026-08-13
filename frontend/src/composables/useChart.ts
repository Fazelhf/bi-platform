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

  // ECharts trusts the width it measured at init. `window.resize` misses every
  // other way a container changes size — data arriving, a rail collapsing, a
  // grid track settling — and a chart holding a width wider than the phone
  // screen drags the whole page sideways. Watch the element, not the window.
  let observer: ResizeObserver | null = null;

  onMounted(() => {
    if (!el.value) return;
    chart.value = init(el.value, undefined, { renderer: "canvas" });
    chart.value.setOption(option.value);
    ready.value = true;
    window.addEventListener("resize", resize);
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(resize);
      observer.observe(el.value);
    }
    // A chart that is wrong from its first frame never changes size, so the
    // observer has nothing to report. Re-measure once the page is laid out.
    requestAnimationFrame(() => requestAnimationFrame(resize));
  });

  watch(
    option,
    (o) => {
      chart.value?.setOption(o, true);
      resize();
    },
    { deep: true },
  );

  onBeforeUnmount(() => {
    window.removeEventListener("resize", resize);
    observer?.disconnect();
    observer = null;
    chart.value?.dispose();
    chart.value = null;
  });

  return { ready, chart };
}
