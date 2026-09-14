import { init, type EChartsOption, type EChartsType } from "@/lib/echarts";
import { onBeforeUnmount, onMounted, ref, shallowRef, watch, type Ref } from "vue";

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
  //
  // Shallow, never deep. A plain `ref` wraps the ECharts instance in a deep
  // reactive proxy, so every property ECharts reads on itself — thousands per
  // frame — goes through Vue's tracking, and its methods run with `this` set
  // to the proxy instead of the chart. Only *which* instance exists needs to
  // be reactive, and shallowRef tracks exactly that.
  const chart = shallowRef<EChartsType | null>(null);
  const ready = ref(false);

  /**
   * One resize per frame, however many things ask for it.
   *
   * The window, the ResizeObserver, the option watcher and the first-layout
   * nudge all call this, often in the same tick. It used to resize on the
   * spot — including straight after `setOption(o, true)`, while ECharts was
   * still rebuilding the axes that option had just thrown away. The render
   * that followed found a bar series with no coordinate system, threw
   * `getBaseAxis` from inside its own animation loop, and kept throwing.
   * Deferred to a frame, the rebuild is always finished first.
   */
  let frame = 0;
  function resize() {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const instance = chart.value;
      if (!instance || instance.isDisposed()) return;
      try {
        instance.resize();
      } catch {
        // A failed re-measure leaves the old layout on screen; the next
        // resize or option change lays it out again.
      }
    });
  }

  /**
   * Replace the option, and recover in place if ECharts rejects it.
   *
   * Recovery reuses the same instance — `clear()` then set — rather than
   * disposing and re-creating it, because callers hang handlers on the
   * instance (BoardChart's drill-down click) and a new one would drop them.
   */
  function apply(instance: EChartsType, next: EChartsOption, notMerge: boolean) {
    try {
      instance.setOption(next, notMerge);
    } catch {
      try {
        instance.clear();
        instance.setOption(next, true);
      } catch {
        // Leave this one chart blank. A chart that cannot draw must never
        // be the reason the rest of the page cannot.
      }
    }
  }

  // ECharts trusts the width it measured at init. `window.resize` misses every
  // other way a container changes size — data arriving, a rail collapsing, a
  // grid track settling — and a chart holding a width wider than the phone
  // screen drags the whole page sideways. Watch the element, not the window.
  let observer: ResizeObserver | null = null;

  onMounted(() => {
    if (!el.value) return;
    chart.value = init(el.value, undefined, { renderer: "canvas" });
    apply(chart.value, option.value, false);
    ready.value = true;
    window.addEventListener("resize", resize);
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(resize);
      observer.observe(el.value);
    }
    // A chart that is wrong from its first frame never changes size, so the
    // observer has nothing to report. Re-measure once the page is laid out.
    requestAnimationFrame(resize);
  });

  watch(
    option,
    (o) => {
      const instance = chart.value;
      if (!instance || instance.isDisposed()) return;
      apply(instance, o, true);
      resize();
    },
    { deep: true },
  );

  onBeforeUnmount(() => {
    window.removeEventListener("resize", resize);
    observer?.disconnect();
    observer = null;
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    const instance = chart.value;
    chart.value = null;
    // Guarded because this runs inside Vue's unmount of the whole page. A
    // throw here aborts that patch half-way, the router never swaps the view,
    // and the user is left on تولید with the address bar saying they left.
    try {
      instance?.dispose();
    } catch {
      // The canvas goes with its element either way.
    }
  });

  return { ready, chart };
}
