import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
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
