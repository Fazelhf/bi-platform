<script setup lang="ts">
import { ref } from "vue";
import api from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/composables/useUi";

/**
 * The small Excel / Print pair that sits in a dashboard header.
 * Excel is executive-only (the API enforces it too); printing is open to
 * anyone who can see the page.
 */
const props = withDefaults(
  defineProps<{ section?: string; period?: number | null; excel?: boolean }>(),
  { section: "", period: null, excel: true },
);

const auth = useAuthStore();
const busy = ref(false);

const canExport = () => props.excel && auth.isExecutive && !!props.section;

/** Charts need a beat to reflow into the print layout before the dialog. */
function print() {
  window.dispatchEvent(new Event("resize"));
  setTimeout(() => window.print(), 120);
}

async function downloadExcel() {
  if (!props.period) {
    toast.error("اول یک دوره را انتخاب کنید.");
    return;
  }
  busy.value = true;
  try {
    const res = await api.get("/executive/export/", {
      params: { period: props.period, section: props.section },
      responseType: "blob",
    });
    // Prefer the server's RFC 5987 filename so the Persian name survives.
    const disp = res.headers["content-disposition"] ?? "";
    const match = /filename\*=UTF-8''([^;]+)/.exec(disp);
    const name = match ? decodeURIComponent(match[1]) : "export.xlsx";

    const url = URL.createObjectURL(res.data as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  } catch {
    toast.error("خروجی اکسل گرفته نشد.");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="flex items-center gap-1.5 no-print">
    <button
      v-if="canExport()"
      class="flex items-center gap-1 text-xs bg-surface border border-slate-200 rounded-xl px-2.5 py-1.5 hover:bg-slate-50 disabled:opacity-50 transition-colors"
      :disabled="busy"
      title="خروجی اکسل"
      @click="downloadExcel"
    >
      <svg class="w-3.5 h-3.5 text-accent-600" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="7 10 12 15 17 10" />
        <line x1="12" y1="15" x2="12" y2="3" />
      </svg>
      <span>{{ busy ? "…" : "اکسل" }}</span>
    </button>

    <button
      class="flex items-center gap-1 text-xs bg-surface border border-slate-200 rounded-xl px-2.5 py-1.5 hover:bg-slate-50 transition-colors"
      title="پرینت این صفحه"
      @click="print"
    >
      <svg class="w-3.5 h-3.5 text-slate-500" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="6 9 6 2 18 2 18 9" />
        <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
        <rect x="6" y="14" width="12" height="8" />
      </svg>
      <span>پرینت</span>
    </button>
  </div>
</template>
