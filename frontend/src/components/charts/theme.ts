import { ref } from "vue";
import { graphic } from "@/lib/echarts";
import { paletteByKey, type Palette } from "./palettes";
import { store } from "@/lib/storage";

/**
 * Live chart theme. Reads the palette the CEO selected (stored in the ui
 * store / localStorage) so every chart in every section changes together.
 */
export function activePalette(): Palette {
  return paletteByKey(store.get("chartTheme") || "modern");
}

/** True when the app is in dark mode — charts read this at render time. */
export function isDark(): boolean {
  return document.documentElement.classList.contains("dark");
}

/** Back-compat colour accessor used by chart components. */
export const COLORS = new Proxy({} as Record<string, string>, {
  get(_t, key: string) {
    const p = activePalette();
    if (key === "ink") return isDark() ? "#ececee" : "#1c1c1e";
    return (p as any)[key] ?? "#3b6fed";
  },
});

/** A soft gradient for a bar (flat fill when the theme disables gradients). */
export function barGradient(hex: string) {
  if (!activePalette().gradient) return hex;
  return new graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: mix(hex, "#ffffff", 0.22) },
    { offset: 1, color: hex },
  ]);
}

/** Corner radius from the active theme. */
export function barRadius(): number {
  return activePalette().radius;
}

/** Categorical colour for multi-series charts. */
export function seriesColor(i: number): string {
  const s = activePalette().series;
  return s[i % s.length];
}

/**
 * Bumped whenever the light/dark theme flips. AXIS and TOOLTIP read it inside
 * getters, so any computed chart option that spreads them registers a
 * dependency and rebuilds itself on toggle — no page reload needed.
 */
const themeTick = ref(0);
export function bumpChartTheme() {
  themeTick.value++;
}

export const AXIS = {
  get category() {
    themeTick.value;
    return {
      type: "category" as const,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: isDark() ? "#a3a3ad" : "#64748b", fontSize: 11 },
    };
  },
  get value() {
    themeTick.value;
    const dark = isDark();
    return {
      type: "value" as const,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: dark ? "#8d8d97" : "#94a3b8", fontSize: 10 },
      splitLine: {
        lineStyle: { color: dark ? "#33333a" : "#eef0f2", type: "dashed" as const },
      },
    };
  },
};

// Property getters (not a plain object) so `{ ...TOOLTIP }` re-reads them.
export const TOOLTIP = {
  get backgroundColor() {
    themeTick.value;
    return isDark() ? "#3b3b44" : "#1c1c1e";
  },
  borderWidth: 0,
  get textStyle() {
    themeTick.value;
    return { color: "#fff", fontSize: 12 };
  },
  padding: [6, 10],
  // ECharts' default shadow pointer is a light grey band, which reads as a
  // glaring white block behind the hovered label in dark mode.
  get axisPointer() {
    themeTick.value;
    return {
      type: "shadow" as const,
      shadowStyle: {
        color: isDark() ? "rgba(255,255,255,0.06)" : "rgba(150,150,150,0.15)",
      },
    };
  },
};

/** Compact number for labels/axes (K/M/B). */
export function compact(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e9) return (v / 1e9).toFixed(1) + "B";
  if (abs >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (abs >= 1e3) return (v / 1e3).toFixed(0) + "K";
  return String(Math.round(v * 100) / 100);
}

function mix(a: string, b: string, t: number): string {
  const pa = hexToRgb(a), pb = hexToRgb(b);
  const r = Math.round(pa[0] + (pb[0] - pa[0]) * t);
  const g = Math.round(pa[1] + (pb[1] - pa[1]) * t);
  const bl = Math.round(pa[2] + (pb[2] - pa[2]) * t);
  return `rgb(${r},${g},${bl})`;
}
function hexToRgb(h: string): [number, number, number] {
  const n = h.replace("#", "");
  return [parseInt(n.slice(0, 2), 16), parseInt(n.slice(2, 4), 16), parseInt(n.slice(4, 6), 16)];
}
