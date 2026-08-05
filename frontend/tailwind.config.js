/** @type {import('tailwindcss').Config} */

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

export default {
  content: ["./index.html", "./src/**/*.{vue,ts}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Vazirmatn", "Tahoma", "system-ui", "sans-serif"],
      },
      colors: {
        brand: {
          50: v("c-brand-50"),
          500: "#3b6fed",
          600: "#2b57d4",
          700: "#2244ab",
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
          500: "#10b981", // green — online, success, primary actions
          600: "#059669",
        },
      },
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
  plugins: [],
};
