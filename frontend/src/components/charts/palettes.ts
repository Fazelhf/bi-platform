/**
 * Four chart design themes. The CEO picks one in تنظیمات سایت and every
 * chart in every section switches together, so the whole app stays coherent.
 *
 * Categorical ramps are validated, not chosen by eye. Every `series` and
 * `seriesDark` array below passed a six-check run — lightness band, chroma
 * floor, colour-blind separation between adjacent slots, a normal-vision
 * floor, and contrast against the chart surface. The previous ramps did not:
 * the default paired a desaturated slate against pink at ΔE 2.5 under
 * protanopia (indistinguishable), «سازمانی» ran three blues that scored 10
 * against each other in *normal* vision, and «تک‌رنگ» was a lightness ramp —
 * the tool for magnitude — used to tell one account from another.
 *
 * Themes differ in accent trio, gradient and corner radius. They deliberately
 * share the two validated categorical orders: which bank account is which is
 * a correctness question, and there is no version of it that should be
 * decided by the theme picker.
 */
export interface Palette {
  key: string;
  label: string;
  actual: string;   // واقعی
  target: string;   // مطلوب
  ideal: string;    // ایده‌آل
  /** Categorical ramp, light mode. Fixed order — never cycled (see seriesColor). */
  series: string[];
  /** The same ramp restepped for the dark surface, not an automatic flip. */
  seriesDark: string[];
  slate: string;    // neutral / inactive
  rose: string;     // cost / negative
  gradient: boolean;
  radius: number;
}

// Warm-led order: blue, orange, aqua, yellow, magenta, green, violet, red.
const WARM = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];
const WARM_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

// Cool-led order: blue, teal, violet, ochre, plum, green, cyan, brick.
const COOL = ["#2a78d6", "#0d9488", "#7c5cd6", "#c2761f", "#d1608f", "#3f8f3f", "#1f6f9e", "#b8433f"];
const COOL_DARK = ["#4a90e2", "#0f9b8c", "#8a74d8", "#c47f22", "#cd6d95", "#479f47", "#3d92c4", "#dd5f5b"];

export const PALETTES: Palette[] = [
  {
    key: "modern",
    label: "مدرن (پیش‌فرض)",
    actual: "#2a78d6", target: "#1baf7a", ideal: "#4a3aa7",
    series: WARM, seriesDark: WARM_DARK,
    slate: "#cbd5e1", rose: "#e34948", gradient: true, radius: 6,
  },
  {
    key: "corporate",
    label: "سازمانی (آبی آرام)",
    actual: "#2a78d6", target: "#0d9488", ideal: "#7c5cd6",
    series: COOL, seriesDark: COOL_DARK,
    slate: "#cbd5e1", rose: "#b8433f", gradient: false, radius: 3,
  },
  {
    key: "vivid",
    label: "پرکنتراست",
    actual: "#2a78d6", target: "#008300", ideal: "#e87ba4",
    series: WARM, seriesDark: WARM_DARK,
    slate: "#d1d5db", rose: "#e34948", gradient: true, radius: 10,
  },
  {
    key: "mono",
    label: "مینیمال (کم‌رنگ)",
    actual: "#2a78d6", target: "#0d9488", ideal: "#7c5cd6",
    series: COOL, seriesDark: COOL_DARK,
    slate: "#e5e7eb", rose: "#b8433f", gradient: false, radius: 2,
  },
];

/** How many distinct categorical slots exist before a chart must fold the
 *  tail into «سایر». Charts read this rather than hardcoding 8. */
export const SERIES_SLOTS = WARM.length;

export function paletteByKey(key: string | undefined): Palette {
  return PALETTES.find((p) => p.key === key) ?? PALETTES[0];
}
