<script setup lang="ts">
import { ref } from "vue";
import { crmApi, type Drill } from "@/api/crm";
import { saveAsFile } from "@/utils/download";
import { toast } from "@/composables/useUi";
import { num } from "@/utils/format";

/**
 * «خروجی اکسل» for any CRM list.
 *
 * It sends the list's own filter params to the server and gets back a real
 * workbook covering every matching record — not the page the table happens
 * to be showing. The count in the tooltip is the promise being made, so the
 * button states it rather than leaving the reader to find out in Excel.
 */
const props = withDefaults(defineProps<{
  kind: Drill["kind"];
  params: Record<string, any>;
  title: string;
  total?: number;
  subtle?: boolean;
}>(), { total: 0, subtle: false });

const busy = ref(false);

async function run() {
  busy.value = true;
  try {
    const res = await crmApi.exportDrill({ kind: props.kind, params: props.params }, props.title);
    saveAsFile(res, `${props.title}.xlsx`);
  } catch {
    toast.error("خروجی اکسل گرفته نشد.");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <button
    class="flex items-center gap-1.5 text-xs rounded-xl px-3 py-2 disabled:opacity-50 transition no-print shrink-0"
    :class="subtle ? 'bg-slate-100 text-slate-600 hover:bg-slate-200' : 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100'"
    :disabled="busy || !total"
    :title="total ? `خروجی اکسل ${num(total)} رکورد` : 'رکوردی برای خروجی نیست'"
    @click="run"
  >
    <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
    <span>{{ busy ? "در حال ساخت…" : "خروجی اکسل" }}</span>
  </button>
</template>
