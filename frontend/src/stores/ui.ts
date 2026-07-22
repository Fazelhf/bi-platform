import { defineStore } from "pinia";
import api from "@/api/client";
import { paletteByKey, type Palette } from "@/components/charts/palettes";

/**
 * Site-wide UI preferences. The chart theme is chosen by the CEO in
 * تنظیمات سایت and applied to every chart across every section.
 */
export const useUiStore = defineStore("ui", {
  state: () => ({
    chartTheme: (localStorage.getItem("chartTheme") || "modern") as string,
    companyName: "شرکت کاغذ حساس نمابر مهر",
    loaded: false,
  }),
  getters: {
    palette(): Palette {
      return paletteByKey(this.chartTheme);
    },
  },
  actions: {
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
