import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    vue(),
    /**
     * Installable app + instant start, without ever showing stale numbers.
     *
     * Two things are being bought here, and they are worth separating:
     *
     * 1. **Installable.** The سرپرست opens this on a phone in the workshop and
     *    the CEO opens it between meetings. Installed, it starts from the home
     *    screen with no address bar and no «کدام تب بود؟».
     * 2. **Instant start.** The shell — code, styles, fonts — is precached, so
     *    opening the app costs no round trip to Tehran before anything paints.
     *
     * What is deliberately NOT bought: cached API responses. This is a BI
     * platform, and a figure that is quietly six hours old is worse than no
     * figure at all — someone decides on it. `/api/` is never cached; offline,
     * requests fail and the app says so (see PwaBanner). The one exception is
     * the Vazirmatn font from the CDN, where the stale copy is the same bytes
     * as the fresh one and the alternative is Persian rendered in a fallback
     * Latin face.
     */
    VitePWA({
      // Prompt, never auto-reload. Auto would swap the bundle underneath
      // someone half-way through keying a month of production figures.
      registerType: "prompt",
      // Keep the URL the old hand-written manifest already used, so nothing
      // that points at /site.webmanifest has to change.
      manifestFilename: "site.webmanifest",
      includeAssets: [
        "favicon.ico",
        "favicon-16x16.png",
        "favicon-32x32.png",
        "apple-touch-icon.png",
      ],
      manifest: {
        id: "/",
        name: "شرکت کاغذ حساس نمابر مهر",
        short_name: "NTP",
        description: "داشبورد مدیریتی، اتوماسیون اداری و CRM شرکت کاغذ حساس نمابر مهر",
        lang: "fa",
        dir: "rtl",
        display: "standalone",
        orientation: "portrait-primary",
        start_url: "/",
        scope: "/",
        theme_color: "#1c1c1e",
        background_color: "#e9e8e4",
        icons: [
          { src: "/android-chrome-192x192.png", sizes: "192x192", type: "image/png" },
          { src: "/android-chrome-512x512.png", sizes: "512x512", type: "image/png" },
          // The artwork is full-bleed dark with the logo inside the middle
          // 50%, so it survives Android's circle/squircle crop as-is — no
          // separate padded file needed.
          {
            src: "/android-chrome-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
        // Long-press the installed icon. These are the two things people open
        // the app *for* rather than browse to.
        shortcuts: [
          {
            name: "اتوماسیون اداری",
            short_name: "اتوماسیون",
            url: "/office",
            icons: [{ src: "/android-chrome-192x192.png", sizes: "192x192" }],
          },
          {
            name: "کارتابل",
            url: "/inbox",
            icons: [{ src: "/android-chrome-192x192.png", sizes: "192x192" }],
          },
        ],
      },
      workbox: {
        // echarts alone is half a megabyte; the default 2 MiB ceiling would
        // silently drop it from the precache and the charts page would be the
        // one screen that needs the network.
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        globPatterns: ["**/*.{js,css,html,ico,png,svg,woff,woff2}"],
        // Deep links (/office/tasks, /crm/deals) are client-side routes: the
        // server has no such file, so the shell answers for all of them.
        navigateFallback: "/index.html",
        // …except these, which are the server's to answer and must not be
        // shadowed by a cached page.
        navigateFallbackDenylist: [/^\/api\//, /^\/admin\//, /^\/static\//],
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          {
            // Vazirmatn's stylesheet and font files from jsDelivr. Versioned
            // URLs, so a cached copy can never be wrong — only old, which for
            // a font means identical.
            urlPattern: ({ url }) =>
              url.origin === "https://cdn.jsdelivr.net" ||
              url.origin === "https://fonts.gstatic.com",
            handler: "CacheFirst",
            options: {
              cacheName: "ntp-fonts",
              expiration: { maxEntries: 30, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // Said plainly, because it is the rule that matters: numbers are
            // never served from a cache.
            urlPattern: ({ url }) => url.pathname.startsWith("/api/"),
            handler: "NetworkOnly",
          },
        ],
      },
      devOptions: {
        // The service worker off during `npm run dev`: a precache in front of
        // HMR is a morning lost to «چرا تغییرم نمی‌آید؟».
        enabled: false,
      },
    }),
  ],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        // Split the two heavy libraries into their own chunks so the initial
        // load (login/dashboard shell) stays small and they're cached apart.
        manualChunks(id) {
          if (id.includes("node_modules")) {
            if (id.includes("echarts") || id.includes("zrender")) return "echarts";
            if (id.includes("ag-grid")) return "aggrid";
            if (id.includes("vue") || id.includes("pinia") || id.includes("@vue")) return "vue";
            return "vendor";
          }
        },
      },
    },
  },
  server: {
    // v2 runs alongside the v1 platform on the same machine, so it owns its
    // own pair of ports: 5174 here, Django on 8001. strictPort matters — with
    // the default, a port already in use is silently swapped for the next
    // free one, and the dev server comes up looking healthy while pointing at
    // nothing. That is how two trees ended up serving each other's frontends
    // against each other's databases.
    port: 5174,
    strictPort: true,
    proxy: {
      // Dev: proxy API to Django so there are no CORS surprises.
      "/api": { target: "http://127.0.0.1:8001", changeOrigin: true },
    },
  },
});
