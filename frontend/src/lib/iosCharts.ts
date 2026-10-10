import { graphic, type EChartsOption } from "@/lib/echarts";

/**
 * The iOS skin's chart language, applied to every chart in the app at the
 * one place options reach ECharts (useChart and CrmChart).
 *
 * The other skins draw charts the way each component wrote them. In iOS they
 * are re-drawn the way Health, Stocks, Fitness and Swift Charts draw:
 *   • bars are capsules — fully rounded ends, narrow, flat fill, no gradient
 *   • lines are smooth 3pt strokes with no point markers, and a single line
 *     gets the soft colour wash that fades to nothing (the Stocks area)
 *   • pies become thick rings with gaps between rounded segments
 *   • gauges become Activity rings: a round-capped arc on a faint track
 *   • the grid is a few faint hairlines, values on the trailing edge
 *   • the tooltip is a white callout card, the pointer a thin scrub line
 *   • every Tailwind colour a component hard-coded is swapped for Apple's
 *     system colour of the same hue, so no chart keeps its old palette.
 *
 * It rewrites a deep copy; the component's own option is never touched, so
 * switching back to another skin redraws exactly what was there before.
 */

export function isIosSkin(): boolean {
  return document.documentElement.dataset.skin === "ios";
}

const dark = () => document.documentElement.classList.contains("dark");

/** Tailwind hues (300–800, the ones charts use) → Apple system colours. */
const LIGHT: Record<string, string> = {};
const DARK: Record<string, string> = {};
function hue(hexes: string[], light: string, darkHex: string) {
  for (const h of hexes) {
    LIGHT[h] = light;
    DARK[h] = darkHex;
  }
}
hue(["#3b6fed", "#2b57d4", "#2244ab", "#3b82f6", "#2563eb", "#1d4ed8", "#1e40af", "#60a5fa", "#93c5fd", "#0369a1"], "#007aff", "#0a84ff");
hue(["#10b981", "#059669", "#047857", "#34d399", "#22c55e", "#16a34a", "#15803d", "#4ade80", "#6ee7b7"], "#34c759", "#30d158");
hue(["#ef4444", "#dc2626", "#b91c1c", "#f87171", "#be123c"], "#ff3b30", "#ff453a");
hue(["#f43f5e", "#e11d48", "#fb7185", "#ec4899", "#db2777", "#f472b6"], "#ff2d55", "#ff375f");
hue(["#f59e0b", "#d97706", "#b45309", "#fbbf24", "#f97316", "#ea580c", "#fb923c"], "#ff9500", "#ff9f0a");
hue(["#eab308", "#ca8a04", "#facc15"], "#ffcc00", "#ffd60a");
hue(["#06b6d4", "#0891b2", "#22d3ee", "#0ea5e9", "#0284c7", "#38bdf8"], "#32ade6", "#64d2ff");
hue(["#14b8a6", "#0d9488", "#0f766e", "#2dd4bf"], "#30b0c7", "#40c8e0");
hue(["#6366f1", "#4f46e5", "#4338ca", "#818cf8"], "#5856d6", "#5e5ce6");
hue(["#8b5cf6", "#7c3aed", "#8b7cf6", "#a855f7", "#9333ea", "#a78bfa", "#c084fc"], "#af52de", "#bf5af2");
hue(["#64748b", "#475569", "#334155", "#94a3b8", "#6b7280", "#4b5563", "#9ca3af"], "#8e8e93", "#8e8e93");
hue(["#cbd5e1", "#d1d5db", "#e2e8f0", "#e5e7eb", "#c0c4cb", "#d8dbe0"], "#d1d1d6", "#3a3a3c");
hue(["#1c1c1e", "#1e293b", "#0f172a"], "#1c1c1e", "#f2f2f7");

function mapColor(c: unknown): unknown {
  if (typeof c !== "string") return c;
  const key = c.trim().toLowerCase();
  return (dark() ? DARK : LIGHT)[key] ?? c;
}

/** A gradient becomes the flat colour of its last stop: iOS fills are flat. */
function flatten(c: unknown): unknown {
  if (c && typeof c === "object" && Array.isArray((c as any).colorStops)) {
    const stops = (c as any).colorStops as { color: string }[];
    return mapColor(stops[stops.length - 1]?.color);
  }
  return mapColor(c);
}

function rgba(hex: string, a: number): string {
  const n = hex.replace("#", "");
  if (n.length !== 6) return hex;
  const r = parseInt(n.slice(0, 2), 16), g = parseInt(n.slice(2, 4), 16), b = parseInt(n.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

/** Deep copy that keeps functions (formatters) and ECharts graphic objects. */
function clone<T>(v: T): T {
  if (Array.isArray(v)) return v.map(clone) as T;
  if (v && typeof v === "object") {
    const proto = Object.getPrototypeOf(v);
    if (proto !== Object.prototype && proto !== null) return v; // gradients, Dates
    const out: any = {};
    for (const k of Object.keys(v as any)) out[k] = clone((v as any)[k]);
    return out;
  }
  return v;
}

/** Every `color` anywhere in the tree goes through the Apple palette. */
function recolour(node: any) {
  if (Array.isArray(node)) {
    node.forEach((n, i) => {
      if (typeof n === "string") node[i] = mapColor(n);
      else recolour(n);
    });
    return;
  }
  if (!node || typeof node !== "object" || Object.getPrototypeOf(node) !== Object.prototype) return;
  for (const k of Object.keys(node)) {
    const v = node[k];
    if (k === "color" || k === "borderColor" || k === "shadowColor") {
      node[k] = Array.isArray(v) ? v.map(flatten) : flatten(v);
    } else if (typeof v === "object") recolour(v);
  }
}

const arr = <T>(v: T | T[] | undefined): T[] => (v == null ? [] : Array.isArray(v) ? v : [v]);

function tokens() {
  const d = dark();
  return {
    label: d ? "#8e8e93" : "#8e8e93",
    text: d ? "#ffffff" : "#000000",
    hair: d ? "rgba(84,84,88,0.45)" : "rgba(60,60,67,0.12)",
    track: d ? "rgba(118,118,128,0.24)" : "rgba(118,118,128,0.12)",
    surface: d ? "#1c1c1e" : "#ffffff",
    font: getComputedStyle(document.body).fontFamily,
  };
}

function axis(a: any, t: ReturnType<typeof tokens>, isValue: boolean) {
  if (!a || typeof a !== "object") return a;
  const valueAxis = a.type === "value" || a.type === "log" || (isValue && a.type !== "category");
  a.axisLine = { ...(a.axisLine ?? {}), show: false };
  a.axisTick = { show: false };
  a.axisLabel = { ...(a.axisLabel ?? {}), color: t.label, fontSize: 11, fontFamily: t.font };
  if (valueAxis) {
    a.splitLine = { show: a.splitLine?.show !== false, lineStyle: { color: t.hair, type: "solid", width: 1 } };
    a.splitNumber = a.splitNumber ?? 3; // Health shows three or four values, never ten
  } else {
    a.splitLine = { show: false };
  }
  return a;
}

/**
 * Rewrite one option into the iOS chart language. Returns the input
 * unchanged in any other skin.
 */
export function iosChartOption<T extends EChartsOption | any>(option: T): T {
  if (!isIosSkin() || !option || typeof option !== "object") return option;
  const o: any = clone(option);
  const t = tokens();

  if (Array.isArray(o.color)) o.color = o.color.map(flatten);
  recolour(o.series);
  recolour(o.visualMap);
  recolour(o.legend);

  o.textStyle = { ...(o.textStyle ?? {}), fontFamily: t.font };
  o.animationDuration = 700;
  o.animationEasing = "cubicOut";
  o.animationDurationUpdate = 450;
  o.animationEasingUpdate = "cubicInOut";

  // --- axes & grid -------------------------------------------------------
  const horizontalBars = arr(o.yAxis).some((y: any) => y?.type === "category");
  o.xAxis = Array.isArray(o.xAxis)
    ? o.xAxis.map((a: any) => axis(a, t, horizontalBars))
    : axis(o.xAxis, t, horizontalBars);
  o.yAxis = Array.isArray(o.yAxis)
    ? o.yAxis.map((a: any) => axis(a, t, !horizontalBars))
    : axis(o.yAxis, t, !horizontalBars);
  for (const g of arr(o.grid)) {
    if (g && typeof g === "object") g.containLabel = g.containLabel ?? true;
  }

  // --- tooltip: a white callout, the pointer a scrub line -------------------
  if (o.tooltip !== undefined) {
    const tips = arr(o.tooltip);
    o.tooltip = tips.map((tip: any) => ({
      ...tip,
      backgroundColor: dark() ? "rgba(44,44,46,0.96)" : "rgba(255,255,255,0.98)",
      borderWidth: 0,
      padding: [8, 12],
      textStyle: { ...(tip?.textStyle ?? {}), color: t.text, fontSize: 12, fontFamily: t.font },
      extraCssText:
        "border-radius:12px;box-shadow:0 0 0 0.5px rgba(0,0,0,0.06),0 10px 30px -6px rgba(0,0,0,0.25);direction:rtl;",
      axisPointer:
        tip?.trigger === "axis"
          ? { type: "line", lineStyle: { color: dark() ? "rgba(235,235,245,0.35)" : "rgba(60,60,67,0.3)", width: 1, type: "solid" } }
          : tip?.axisPointer,
    }));
    if (!Array.isArray(option && (option as any).tooltip)) o.tooltip = o.tooltip[0];
  }

  // --- legend: small dots, grey text -------------------------------------
  for (const l of arr(o.legend)) {
    if (!l || typeof l !== "object") continue;
    l.icon = "circle";
    l.itemWidth = 8;
    l.itemHeight = 8;
    l.itemGap = 14;
    l.textStyle = { ...(l.textStyle ?? {}), color: t.label, fontSize: 11, fontFamily: t.font };
  }

  // --- series ------------------------------------------------------------
  const series = arr(o.series);
  const lines = series.filter((s: any) => s?.type === "line");
  series.forEach((s: any, i: number) => {
    if (!s || typeof s !== "object") return;
    s.animationDelay = (idx: number) => idx * 18 + i * 60; // bars grow in a wave

    if (s.type === "bar") {
      const stacked = !!s.stack;
      const r = stacked ? 3 : 999; // a capsule; stacked segments only soften
      s.itemStyle = { ...(s.itemStyle ?? {}), borderRadius: r, color: flatten(s.itemStyle?.color) };
      if (s.itemStyle.color === undefined) delete s.itemStyle.color;
      s.barMaxWidth = Math.min(Number(s.barMaxWidth) || 18, horizontalBars ? 14 : 18);
      s.barGap = s.barGap ?? "35%";
      s.barCategoryGap = s.barCategoryGap ?? "40%";
      if (!stacked && series.filter((x: any) => x?.type === "bar").length === 1) {
        s.showBackground = true; // the faint full-height track Health draws
        s.backgroundStyle = { color: t.track, borderRadius: 999 };
      }
      if (s.label?.show) s.label = { ...s.label, color: t.label, fontSize: 10, fontFamily: t.font };
      // Each bar's own colour (data items with itemStyle) gets the capsule too.
      if (Array.isArray(s.data)) {
        s.data = s.data.map((d: any) =>
          d && typeof d === "object" && !Array.isArray(d) && d.itemStyle
            ? { ...d, itemStyle: { ...d.itemStyle, borderRadius: r, color: flatten(d.itemStyle.color) } }
            : d,
        );
      }
    }

    if (s.type === "line") {
      const colour = (flatten(s.lineStyle?.color ?? s.itemStyle?.color) as string) || undefined;
      s.smooth = s.smooth ?? 0.35;
      s.symbol = "circle";
      s.symbolSize = 8;
      s.showSymbol = false; // markers only on the scrubbed point
      s.lineStyle = { ...(s.lineStyle ?? {}), width: 3, cap: "round", join: "round" };
      if (colour) s.lineStyle.color = colour;
      s.itemStyle = { ...(s.itemStyle ?? {}), borderColor: t.surface, borderWidth: 2 };
      if (colour) s.itemStyle.color = colour;
      s.emphasis = { ...(s.emphasis ?? {}), focus: "none", scale: 1.4 };
      const dashed = s.lineStyle.type && s.lineStyle.type !== "solid";
      // A target or reference line is dashed on purpose; it never gets a wash.
      if (dashed) s.lineStyle.width = 2;
      if (lines.length === 1 && colour && colour.startsWith("#") && !s.stack && !dashed) {
        s.areaStyle = {
          color: new graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: rgba(colour, dark() ? 0.35 : 0.25) },
            { offset: 1, color: rgba(colour, 0) },
          ]),
        };
      } else if (s.areaStyle) {
        s.areaStyle = { ...s.areaStyle, opacity: 0.08 };
      }
    }

    if (s.type === "pie") {
      const radius = arr(s.radius);
      const outer = radius[1] ?? radius[0] ?? "75%";
      s.radius = [typeof outer === "string" && outer.endsWith("%") ? `${parseFloat(outer) * 0.72}%` : "54%", outer];
      s.padAngle = 2.5;
      s.itemStyle = { ...(s.itemStyle ?? {}), borderRadius: 6, borderWidth: 0 };
      s.label = { ...(s.label ?? {}), color: t.label, fontSize: 11, fontFamily: t.font };
      s.labelLine = { ...(s.labelLine ?? {}), lineStyle: { color: t.hair } };
      s.emphasis = { ...(s.emphasis ?? {}), scaleSize: 4 };
    }

    if (s.type === "gauge") {
      const colour = (flatten(s.progress?.itemStyle?.color ?? s.itemStyle?.color) as string) || "#007aff";
      s.startAngle = s.startAngle ?? 90;
      s.endAngle = s.endAngle ?? -270;
      s.pointer = { show: false };
      s.progress = { show: true, roundCap: true, width: 16, itemStyle: { color: colour } };
      s.axisLine = { roundCap: true, lineStyle: { width: 16, color: [[1, t.track]] } };
      s.axisTick = { show: false };
      s.splitLine = { show: false };
      s.axisLabel = { show: false };
      s.anchor = { show: false };
      s.title = { ...(s.title ?? {}), color: t.label, fontSize: 12, fontFamily: t.font };
      s.detail = {
        ...(s.detail ?? {}),
        color: t.text,
        fontSize: 26,
        fontWeight: 700,
        fontFamily: `ui-rounded, ${t.font}`,
        offsetCenter: s.detail?.offsetCenter ?? [0, 0],
      };
    }

    if (s.type === "heatmap") {
      s.itemStyle = { ...(s.itemStyle ?? {}), borderRadius: 6, borderColor: t.surface, borderWidth: 3 };
    }

    if (s.markLine) {
      s.markLine = {
        ...s.markLine,
        symbol: "none",
        lineStyle: { ...(s.markLine.lineStyle ?? {}), type: [4, 4], width: 1.5 },
        label: { ...(s.markLine.label ?? {}), color: t.label, fontSize: 10, fontFamily: t.font },
      };
    }
  });

  return o as T;
}
