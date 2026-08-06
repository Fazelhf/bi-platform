import { ref } from "vue";
import { graphic } from "@/lib/echarts";
import { paletteByKey, SERIES_SLOTS, type Palette } from "./palettes";
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

/**
 * Reads a design token off <html>. ECharts draws to canvas, so it cannot use
 * CSS variables directly — every axis, tooltip and label colour has to be
 * resolved to a literal at option-build time. Going through the tokens (and
 * not a hardcoded light/dark pair) is what lets charts follow all three skins
 * instead of only کلاسیک.
 */
function token(name: string, fallback: string): string {
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(`--${name}`)
    .trim();
  return raw ? `rgb(${raw.replace(/\s+/g, ",")})` : fallback;
}

/** Back-compat colour accessor used by chart components. */
export const COLORS = new Proxy({} as Record<string, string>, {
  get(_t, key: string) {
    const p = activePalette();
    if (key === "ink") return token("c-ink", isDark() ? "#ececee" : "#1c1c1e");
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

/**
 * Categorical colour for multi-series charts, in fixed order.
 *
 * Past the last slot it returns the neutral rather than wrapping around.
 * Cycling is what put two bank accounts in the same blue on a fourteen-account
 * chart — colour stopped identifying anything, and no amount of palette work
 * fixes that. A chart with more entities than slots has to fold its tail into
 * «سایر» (see foldToSlots); the neutral is what that fold is painted in.
 */
export function seriesColor(i: number): string {
  themeTick.value;
  const p = activePalette();
  const ramp = isDark() ? p.seriesDark : p.series;
  return ramp[i] ?? p.slate;
}

/**
 * Rank-order N items and keep only as many as there are categorical slots,
 * summing the rest into one «سایر» row.
 *
 * `by` is read once per item — the value that decides who is big enough to
 * name. Ties keep input order, so the fold is stable across renders and a
 * legend does not reshuffle while someone is reading it.
 */
export function foldToSlots<T>(
  items: T[],
  by: (item: T) => number,
  merge: (tail: T[]) => T,
): T[] {
  if (items.length <= SERIES_SLOTS) return items;
  const ranked = [...items].sort((a, b) => by(b) - by(a));
  const keep = ranked.slice(0, SERIES_SLOTS - 1);
  const tail = ranked.slice(SERIES_SLOTS - 1);
  return [...keep, merge(tail)];
}

/**
 * Bumped whenever the light/dark mode flips or the skin changes. AXIS and
 * TOOLTIP read it inside getters, so any computed chart option that spreads
 * them registers a dependency and rebuilds itself on toggle — no page reload
 * needed.
 */
const themeTick = ref(0);
export function bumpChartTheme() {
  themeTick.value++;
}

/** The card colour a chart sits on — pie slice gaps must match it, not be
 *  hardcoded white (which turns into glaring outlines in dark mode). */
export function surfaceColor(): string {
  themeTick.value;
  // Not --c-surface: شیشه‌ای paints white at 9% over a dark page, so the
  // literal token would hand ECharts white. --c-chart-surface is the colour
  // the card actually resolves to on screen.
  return token("c-chart-surface", isDark() ? "#1e1e22" : "#ffffff");
}

/** Legend / secondary chart text. */
export function mutedColor(): string {
  themeTick.value;
  return token("c-slate-500", isDark() ? "#a3a3ad" : "#64748b");
}

/** Data labels drawn outside the chart body. */
export function labelColor(): string {
  themeTick.value;
  return token("c-slate-700", isDark() ? "#d6d6dd" : "#334155");
}

export const AXIS = {
  get category() {
    themeTick.value;
    return {
      type: "category" as const,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: mutedColor(), fontSize: 11 },
    };
  },
  get value() {
    themeTick.value;
    const dark = isDark();
    return {
      type: "value" as const,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: token("c-slate-400", dark ? "#8d8d97" : "#94a3b8"),
        fontSize: 10,
      },
      splitLine: {
        lineStyle: {
          color: token("c-slate-200", dark ? "#33333a" : "#eef0f2"),
          type: "dashed" as const,
        },
      },
    };
  },
};

// Property getters (not a plain object) so `{ ...TOOLTIP }` re-reads them.
export const TOOLTIP = {
  get backgroundColor() {
    themeTick.value;
    // --c-panel is the always-dark surface token, which every skin defines as
    // its own "floating dark chip" colour — exactly what a tooltip is.
    return token("c-panel", isDark() ? "#3b3b44" : "#1c1c1e");
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
