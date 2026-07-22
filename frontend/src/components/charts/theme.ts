import * as echarts from "echarts";

// Palette harmonised with the app (brand blue / accent green / soft violet).
export const COLORS = {
  actual: "#3b6fed", // واقعی — brand blue (where we are)
  target: "#10b981", // مطلوب — accent green (realistic goal)
  ideal: "#8b7cf6", // ایده‌آل — soft violet (aspiration)
  slate: "#cbd5e1", // neutral / inactive
  rose: "#f43f5e", // cost / negative
  ink: "#1c1c1e",
};

/** A soft top-to-bottom gradient for a bar, lighter at the top. */
export function barGradient(hex: string) {
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: mix(hex, "#ffffff", 0.22) },
    { offset: 1, color: hex },
  ]);
}

/** Shared axis styling: no hard lines, faint dashed splits. */
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

/** Compact Persian number for labels/axes (K/M/B). */
export function compact(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e9) return (v / 1e9).toFixed(1) + "B";
  if (abs >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (abs >= 1e3) return (v / 1e3).toFixed(0) + "K";
  return String(Math.round(v));
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
