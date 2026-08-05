/**
 * The three site skins. A skin is a whole visual language — colour, corner
 * radius, elevation, translucency — and it is orthogonal to light/dark:
 * every skin below ships both modes, so the sun/moon button keeps working
 * exactly as it does today whichever one is picked.
 *
 * The tokens themselves live in src/style.css under `html[data-skin="…"]`.
 * This file only carries what the picker needs to draw itself.
 */
export type SkinKey = "classic" | "glass" | "aurora";

export interface Skin {
  key: SkinKey;
  label: string;
  hint: string;
  /** Miniature of the skin, drawn by ThemePicker: page → card → accent. */
  preview: {
    canvas: string;
    surface: string;
    surfaceDark: string;
    canvasDark: string;
    accent: string;
    radius: string;
    /** Glass previews get a blur + gradient wash instead of a flat fill. */
    glass?: boolean;
    /** Aurora previews get the drifting colour pools behind the card. */
    aurora?: boolean;
  };
}

export const SKINS: Skin[] = [
  {
    key: "classic",
    label: "کلاسیک",
    hint: "کارت‌های سفید با سایه‌ی نرم — همان ظاهر همیشگی",
    preview: {
      canvas: "#e9e8e4",
      surface: "#ffffff",
      canvasDark: "#121214",
      surfaceDark: "#1e1e22",
      accent: "#3b6fed",
      radius: "10px",
    },
  },
  {
    key: "glass",
    label: "شیشه‌ای",
    hint: "پنل‌های مات و شفاف روی پس‌زمینه‌ی رنگی — به سبک iOS",
    preview: {
      canvas: "#e8eefc",
      surface: "rgba(255,255,255,0.55)",
      canvasDark: "#090b16",
      surfaceDark: "rgba(255,255,255,0.10)",
      accent: "#6366f1",
      radius: "12px",
      glass: true,
    },
  },
  {
    key: "aurora",
    label: "شفق",
    hint: "پس‌زمینه‌ی رنگی متحرک و درخشش بنفش دور کارت‌ها — سرزنده و متفاوت",
    preview: {
      canvas: "#f6f3ff",
      surface: "#ffffff",
      canvasDark: "#0d091c",
      surfaceDark: "#1a1330",
      accent: "#a855f7",
      radius: "9px",
      aurora: true,
    },
  },
];

export const DEFAULT_SKIN: SkinKey = "classic";

export function isSkinKey(v: string | null): v is SkinKey {
  return !!v && SKINS.some((s) => s.key === v);
}

export function skinByKey(key: string): Skin {
  return SKINS.find((s) => s.key === key) ?? SKINS[0];
}
