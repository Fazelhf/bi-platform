/** @type {import('tailwindcss').Config} */
import colors from "tailwindcss/colors.js";

// Every themeable colour is a CSS variable holding space-separated RGB
// channels, so `<alpha-value>` keeps working (bg-surface/50, text-slate-400/70).
// Light and dark values live in src/style.css. Overriding the whole `slate`
// scale is deliberate: it makes the ~260 existing slate utilities (muted text,
// hairline borders, hover fills) theme-aware without touching a component.
//
// `white` stays literally white on purpose — it is only used for text and
// translucent overlays that sit on top of dark panels, which must not flip.
// Card backgrounds use `surface` instead.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
// Same, with the stock Tailwind value as the fallback: only a skin that sets
// the variable (iOS swaps in Apple's system colours) changes anything, so
// every other skin keeps the exact colours it always had.
const vf = (name, rgb) => `rgb(var(--${name}, ${rgb}) / <alpha-value>)`;
const sys = (hue, c500, c600) => ({
  500: vf(`c-${hue}-500`, c500),
  600: vf(`c-${hue}-600`, c600),
});

// ---- Status tints in dark mode ------------------------------------------
// `bg-red-50 text-red-700` is a pale chip with dark text, written hundreds of
// times across the app, and neither half can stay put on a dark page. One
// colour cannot flip for both jobs (bg-*-700 is a real dark button while
// text-*-700 has to turn pale), so the flip is per property: pale fills go
// dark, dark text goes pale, pale borders go dim. Light mode falls back to the
// stock value, so nothing changes there.
const HUES = ["red", "orange", "amber", "yellow", "lime", "green", "emerald", "teal",
  "cyan", "sky", "blue", "indigo", "violet", "purple", "fuchsia", "pink", "rose"];
const channels = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
/** `amount` of the hue over the dark card colour. */
const overDark = (hex, amount) =>
  channels(hex).map((c, i) => Math.round(c * amount + [30, 30, 34][i] * (1 - amount))).join(" ");

const FLIPS = {
  // property -> shade -> what it becomes in dark mode
  bg: { 50: (h) => overDark(h[500], 0.14), 100: (h) => overDark(h[500], 0.22), 200: (h) => overDark(h[500], 0.32) },
  text: { 600: (h) => channels(h[400]).join(" "), 700: (h) => channels(h[300]).join(" "),
    800: (h) => channels(h[200]).join(" "), 900: (h) => channels(h[100]).join(" ") },
  border: { 100: (h) => overDark(h[500], 0.25), 200: (h) => overDark(h[500], 0.38), 300: (h) => overDark(h[500], 0.52) },
};

/** The Tailwind colours of one property, each reading its dark variable. */
function flippedColors(prop) {
  return Object.fromEntries(HUES.map((hue) => [hue, Object.fromEntries(
    Object.keys(FLIPS[prop]).map((shade) => {
      const light = channels(colors[hue][shade]).join(" ");
      // Text-600 keeps the skin's own colour in light mode (iOS swaps it).
      const fallback = prop === "text" && shade === "600" ? `var(--c-${hue}-600, ${light})` : light;
      return [shade, `rgb(var(--dark-${prop}-${hue}-${shade}, ${fallback}) / <alpha-value>)`];
    }),
  )]));
}

const darkTints = Object.fromEntries(Object.entries(FLIPS).flatMap(([prop, shades]) =>
  HUES.flatMap((hue) => Object.entries(shades).map(([shade, make]) =>
    [`--dark-${prop}-${hue}-${shade}`, make(colors[hue])]))));

export default {
  content: ["./index.html", "./src/**/*.{vue,ts}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        // A variable so a skin can put its own face first — iOS leads with
        // the Apple system font (SF Pro / SF Arabic) where the OS has it.
        sans: "var(--font-sans)",
      },
      colors: {
        brand: {
          50: v("c-brand-50"),
          500: vf("c-brand-500", "59 111 237"),
          600: vf("c-brand-600", "43 87 212"),
          700: vf("c-brand-700", "34 68 171"),
        },
        // Design tokens taken from the reference mockup.
        surface: v("c-surface"), // card background — dark grey in dark mode
        canvas: v("c-canvas"), // page background
        ink: {
          DEFAULT: v("c-ink"), // primary text — flips light in dark mode
          soft: v("c-ink-soft"),
        },
        // Always-dark surface (hero cards, sticky action bars, active tabs).
        // Kept separate from `ink` because in dark mode `text-ink` must go
        // light while these panels must stay dark.
        panel: {
          DEFAULT: v("c-panel"),
          soft: v("c-panel-soft"),
        },
        slate: {
          50: v("c-slate-50"),
          100: v("c-slate-100"),
          200: v("c-slate-200"),
          300: v("c-slate-300"),
          400: v("c-slate-400"),
          500: v("c-slate-500"),
          600: v("c-slate-600"),
          700: v("c-slate-700"),
          800: v("c-slate-800"),
          900: v("c-slate-900"),
        },
        accent: {
          50: v("c-accent-50"),
          500: vf("c-accent-500", "16 185 129"), // green — online, success, primary actions
          600: vf("c-accent-600", "5 150 105"),
        },
        // The status hues, 500/600 only — the ones that carry meaning (badges,
        // buttons, coloured figures). Tailwind deep-merges these into its
        // own scales, so the 50/100 tints and the rest stay stock.
        red: sys("red", "239 68 68", "220 38 38"),
        orange: sys("orange", "249 115 22", "234 88 12"),
        amber: sys("amber", "245 158 11", "217 119 6"),
        yellow: sys("yellow", "234 179 8", "202 138 4"),
        green: sys("green", "34 197 94", "22 163 74"),
        emerald: sys("emerald", "16 185 129", "5 150 105"),
        teal: sys("teal", "20 184 166", "13 148 136"),
        sky: sys("sky", "14 165 233", "2 132 199"),
        blue: sys("blue", "59 130 246", "37 99 235"),
        indigo: sys("indigo", "99 102 241", "79 70 229"),
        violet: sys("violet", "139 92 246", "124 58 237"),
        purple: sys("purple", "168 85 247", "147 51 234"),
        pink: sys("pink", "236 72 153", "219 39 119"),
        rose: sys("rose", "244 63 94", "225 29 72"),
      },
      backgroundColor: flippedColors("bg"),
      textColor: {
        ...flippedColors("text"),
        // slate-300 and 400 double as hairline colours, and at that weight they
        // are unreadable as text on a dark card. Text takes the next step up.
        slate: {
          300: "rgb(var(--dark-text-slate-300, var(--c-slate-300)) / <alpha-value>)",
          400: "rgb(var(--dark-text-slate-400, var(--c-slate-400)) / <alpha-value>)",
        },
      },
      borderColor: flippedColors("border"),
      // Shape and depth are variables too, because that is what separates the
      // three skins more than colour does: کلاسیک leans on soft drop shadows,
      // شیشه‌ای on a lit top edge over blur, and متریال on a hairline outline
      // with almost no shadow at all.
      borderRadius: {
        card: "var(--r-card)", // 24px in کلاسیک — the mockup's card radius
      },
      boxShadow: {
        soft: "var(--shadow-soft)",
        pop: "var(--shadow-pop)",
      },
    },
  },
  plugins: [
    // Screen only: dark mode prints on white paper, in the light colours.
    ({ addBase }) => addBase({ "@media screen": { ".dark": {
      ...darkTints,
      "--dark-text-slate-300": "var(--c-slate-400)",
      "--dark-text-slate-400": "var(--c-slate-500)",
    } } }),
  ],
};
