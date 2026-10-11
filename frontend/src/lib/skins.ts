/**
 * The site skins. A skin is a whole visual language — colour, corner
 * radius, elevation, translucency — and it is orthogonal to light/dark:
 * every skin below ships both modes, so the sun/moon button keeps working
 * exactly as it does today whichever one is picked.
 *
 * The tokens themselves live in src/style.css under `html[data-skin="…"]`.
 * This file only carries what the picker needs to draw itself.
 */
export type SkinKey = "classic" | "ios" | "aurora";

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
    /** Aurora previews get the drifting colour pools behind the card. */
    aurora?: boolean;
    /** iOS previews draw the card as an inset-grouped list with hairlines. */
    ios?: boolean;
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
    key: "ios",
    label: "iOS",
    hint: "خاکستری گروه‌بندی‌شده، آبی سیستمی، گوشه‌های پیوسته و حرکت فنری — حس آیفون",
    preview: {
      canvas: "#f2f2f7",
      surface: "#ffffff",
      canvasDark: "#000000",
      surfaceDark: "#1c1c1e",
      accent: "#007aff",
      radius: "11px",
      ios: true,
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

/** Skins that were retired, and the skin that took each one's place. */
export const RETIRED_SKINS: Record<string, SkinKey> = {
  glass: "ios", // شیشه‌ای was folded into iOS, which does glass properly
};

export function isSkinKey(v: string | null): v is SkinKey {
  return !!v && SKINS.some((s) => s.key === v);
}

export function skinByKey(key: string): Skin {
  return SKINS.find((s) => s.key === key) ?? SKINS[0];
}
