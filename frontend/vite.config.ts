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
    // v2 (CRM) runs alongside v1 — different ports so both can be up at once.
    port: 5174,
    strictPort: true,
    proxy: {
      // Dev: proxy API to Django so there are no CORS surprises.
      "/api": { target: "http://127.0.0.1:8001", changeOrigin: true },
    },
  },
});
