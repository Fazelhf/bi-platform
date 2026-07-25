import { defineStore } from "pinia";
import api from "@/api/client";
import { paletteByKey, type Palette } from "@/components/charts/palettes";
import { bumpChartTheme } from "@/components/charts/theme";

/**
 * Site-wide UI preferences. The chart theme is chosen by the CEO in
 * تنظیمات سایت and applied to every chart across every section.
 */
/** Dark mode is a per-device preference: it lives in localStorage, not on the
 *  server, so the same account can be light on the desktop and dark at night.
 *  The default stays the light theme — dark is opt-in, never inherited from
 *  the OS, so the site looks the way it does today until someone asks for it. */
function initialDark(): boolean {
  return localStorage.getItem("darkMode") === "1";
}

function applyDark(on: boolean) {
  document.documentElement.classList.toggle("dark", on);
}

export const useUiStore = defineStore("ui", {
  state: () => ({
    chartTheme: (localStorage.getItem("chartTheme") || "modern") as string,
    dark: initialDark(),
    companyName: "شرکت کاغذ حساس نمابر مهر",
    loaded: false,
  }),
  getters: {
    palette(): Palette {
      return paletteByKey(this.chartTheme);
    },
  },
  actions: {
    /** Called once at startup so the class matches the stored preference. */
    initDark() {
      applyDark(this.dark);
    },
    toggleDark() {
      this.dark = !this.dark;
      localStorage.setItem("darkMode", this.dark ? "1" : "0");
      applyDark(this.dark);
      bumpChartTheme(); // charts re-read their axis/tooltip colours
    },
    async fetch() {
      try {
        const { data } = await api.get("/executive/site-settings/");
        this.chartTheme = data.chart_theme;
        this.companyName = data.company_name;
        localStorage.setItem("chartTheme", data.chart_theme);
      } catch {
        /* not signed in yet — keep the cached value */
      } finally {
        this.loaded = true;
      }
    },
    async setTheme(key: string) {
      this.chartTheme = key;
      localStorage.setItem("chartTheme", key);
      await api.patch("/executive/site-settings/", { chart_theme: key });
    },
  },
});
