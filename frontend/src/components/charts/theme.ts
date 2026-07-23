import { graphic } from "@/lib/echarts";
import { paletteByKey, type Palette } from "./palettes";

/**
 * Live chart theme. Reads the palette the CEO selected (stored in the ui
 * store / localStorage) so every chart in every section changes together.
 */
export function activePalette(): Palette {
  return paletteByKey(localStorage.getItem("chartTheme") || "modern");
}

/** Back-compat colour accessor used by chart components. */
export const COLORS = new Proxy({} as Record<string, string>, {
  get(_t, key: string) {
    const p = activePalette();
    if (key === "ink") return "#1c1c1e";
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

export const AXIS = {
  category: {
    type: "category" as const,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: "#64748b", fontSize: 11 },
  },
  value: {
    type: "value" as const,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: "#94a3b8", fontSize: 10 },
    splitLine: { lineStyle: { color: "#eef0f2", type: "dashed" as const } },
  },
};

export const TOOLTIP = {
  backgroundColor: "#1c1c1e",
  borderWidth: 0,
  textStyle: { color: "#fff", fontSize: 12 },
  padding: [6, 10],
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
