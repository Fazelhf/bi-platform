/**
 * Four chart design themes. The CEO picks one in تنظیمات سایت and every
 * chart in every section switches together, so the whole app stays coherent.
 */
export interface Palette {
  key: string;
  label: string;
  actual: string;   // واقعی
  target: string;   // مطلوب
  ideal: string;    // ایده‌آل
  series: string[]; // multi-series categorical ramp
  slate: string;    // neutral / inactive
  rose: string;     // cost / negative
  gradient: boolean;
  radius: number;
}

export const PALETTES: Palette[] = [
  {
    key: "modern",
    label: "مدرن (پیش‌فرض)",
    actual: "#3b6fed", target: "#10b981", ideal: "#8b7cf6",
    series: ["#3b6fed", "#10b981", "#8b7cf6", "#f59e0b", "#06b6d4", "#ec4899", "#64748b"],
    slate: "#cbd5e1", rose: "#f43f5e", gradient: true, radius: 6,
  },
  {
    key: "corporate",
    label: "سازمانی (آبی آرام)",
    actual: "#1e40af", target: "#0891b2", ideal: "#7c3aed",
    series: ["#1e40af", "#0891b2", "#7c3aed", "#0f766e", "#4338ca", "#0369a1", "#475569"],
    slate: "#cbd5e1", rose: "#be123c", gradient: false, radius: 3,
  },
  {
    key: "vivid",
    label: "پرکنتراست",
    actual: "#2563eb", target: "#16a34a", ideal: "#db2777",
    series: ["#2563eb", "#16a34a", "#db2777", "#ea580c", "#7c3aed", "#0d9488", "#334155"],
    slate: "#d1d5db", rose: "#dc2626", gradient: true, radius: 10,
  },
  {
    key: "mono",
    label: "تک‌رنگ مینیمال",
    actual: "#1c1c1e", target: "#6b7280", ideal: "#9ca3af",
    series: ["#1c1c1e", "#4b5563", "#6b7280", "#9ca3af", "#c0c4cb", "#d8dbe0", "#e5e7eb"],
    slate: "#e5e7eb", rose: "#6b7280", gradient: false, radius: 2,
  },
];

/**
 * Apple's system colours, used whenever the iOS skin is on. Not in PALETTES:
 * it is part of the skin (a per-device choice), not one of the CEO's
 * site-wide chart themes, so the server never stores it. Flat fills and a
 * small corner, the way Swift Charts draws bars.
 */
export const IOS_PALETTE: Palette = {
  key: "ios",
  label: "iOS",
  actual: "#007aff", target: "#34c759", ideal: "#af52de",
  series: ["#007aff", "#34c759", "#ff9500", "#af52de", "#ff2d55", "#5ac8fa", "#8e8e93"],
  slate: "#d1d1d6", rose: "#ff3b30", gradient: false, radius: 5,
};

export function paletteByKey(key: string | undefined): Palette {
  return PALETTES.find((p) => p.key === key) ?? PALETTES[0];
}
