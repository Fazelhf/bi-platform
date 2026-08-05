import { defineStore } from "pinia";
import { store } from "@/lib/storage";
import api from "@/api/client";
import { paletteByKey, type Palette } from "@/components/charts/palettes";
import { bumpChartTheme } from "@/components/charts/theme";
import { DEFAULT_SKIN, isSkinKey, type SkinKey } from "@/lib/skins";

/**
 * Site-wide UI preferences. The chart theme is chosen by the CEO in
 * تنظیمات سایت and applied to every chart across every section.
 */
/** Dark mode is a per-device preference: it lives in localStorage, not on the
 *  server, so the same account can be light on the desktop and dark at night.
 *  The default stays the light theme — dark is opt-in, never inherited from
 *  the OS, so the site looks the way it does today until someone asks for it. */
function initialDark(): boolean {
  return store.get("darkMode") === "1";
}

function applyDark(on: boolean) {
  document.documentElement.classList.toggle("dark", on);
}

/** The skin is a personal choice, so it follows dark mode's rules: stored
 *  per device in localStorage, never on the server, never inherited from a
 *  colleague. An unknown or missing value falls back to کلاسیک, which is
 *  what the app looked like before skins existed. */
function initialSkin(): SkinKey {
  const saved = store.get("skin");
  return isSkinKey(saved) ? saved : DEFAULT_SKIN;
}

function applySkin(key: SkinKey) {
  document.documentElement.dataset.skin = key;
}

export const useUiStore = defineStore("ui", {
  state: () => ({
    chartTheme: (store.get("chartTheme") || "modern") as string,
    dark: initialDark(),
    skin: initialSkin(),
    companyName: "شرکت کاغذ حساس نمابر مهر",
    loaded: false,
  }),
  getters: {
    palette(): Palette {
      return paletteByKey(this.chartTheme);
    },
  },
  actions: {
    /** Called once at startup so the class and attribute match the stored
     *  preferences. Both run before mount — the page must never flash the
     *  wrong skin or the wrong mode. */
    initAppearance() {
      applyDark(this.dark);
      applySkin(this.skin);
    },
    toggleDark() {
      this.dark = !this.dark;
      store.set("darkMode", this.dark ? "1" : "0");
      applyDark(this.dark);
      bumpChartTheme(); // charts re-read their axis/tooltip colours
    },
    setDark(on: boolean) {
      if (on !== this.dark) this.toggleDark();
    },
    setSkin(key: SkinKey) {
      this.skin = key;
      store.set("skin", key);
      applySkin(key);
      // Charts read --c-chart-surface and the slate ramp, both of which the
      // skin rewrites, so they have to rebuild the same way they do on a
      // light/dark flip.
      bumpChartTheme();
    },
    async fetch() {
      try {
        const { data } = await api.get("/executive/site-settings/");
        this.chartTheme = data.chart_theme;
        this.companyName = data.company_name;
        store.set("chartTheme", data.chart_theme);
      } catch {
        /* not signed in yet — keep the cached value */
      } finally {
        this.loaded = true;
      }
    },
    async setTheme(key: string) {
      this.chartTheme = key;
      store.set("chartTheme", key);
      await api.patch("/executive/site-settings/", { chart_theme: key });
    },
  },
});
