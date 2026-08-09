<script setup lang="ts">
import { ref, watch } from "vue";
import { drillInto, type DrillResult, type WidgetConfig } from "@/api/dashboards";
import { byUnit } from "./format";

/** Same formatting as the chart the row came from — see `format.ts`. */
function cell(value: string | number | null, unit: string): string {
  if (value === null || value === "") return "—";
  if (unit && typeof value === "number") return byUnit(value, unit);
  return String(value);
}

/**
 * The rows behind one bar.
 *
 * A drawer rather than a page: the question «این عدد از کجا آمده؟» is asked
 * *while* reading the board, and answering it by navigating away means coming
 * back to a page that has re-fetched and re-laid-out itself. It also re-runs
 * the widget's own spec on the server, so the rows here always add up to the
 * bar that was clicked — a drill-down that rebuilds the filter by hand is how
 * two numbers on the same screen start disagreeing.
 */
const props = defineProps<{
  config: WidgetConfig;
  dataKey: string;
  label: string;
  title: string;
  period: number | null;
}>();

const emit = defineEmits<{ (e: "close"): void }>();

const result = ref<DrillResult | null>(null);
const loading = ref(true);
const error = ref("");

watch(
  () => [props.dataKey, props.config, props.period],
  async () => {
    loading.value = true;
    error.value = "";
    try {
      result.value = await drillInto(props.config, props.dataKey, props.period);
    } catch (e: any) {
      result.value = null;
      error.value = e?.response?.data?.detail || "جزئیات خوانده نشد.";
    } finally {
      loading.value = false;
    }
  },
  { immediate: true, deep: true },
);
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[72] flex" dir="rtl">
      <div class="flex-1 bg-black/40" @click="emit('close')"></div>

      <aside class="w-full max-w-3xl bg-surface shadow-pop flex flex-col h-full">
        <header class="px-5 py-4 border-b border-slate-100 flex items-start justify-between gap-3 shrink-0">
          <div class="min-w-0">
            <h2 class="font-bold text-ink truncate">{{ label }}</h2>
            <p class="text-xs text-slate-400 mt-0.5 truncate">
              {{ title }}
              <span v-if="result"> · {{ result.dimension.label }} · {{ result.dataset_label }}</span>
            </p>
          </div>
          <button class="text-slate-400 hover:text-ink text-2xl leading-none px-1" @click="emit('close')">×</button>
        </header>

        <div class="flex-1 overflow-auto">
          <div v-if="loading" class="p-5 space-y-2">
            <div v-for="i in 6" :key="i" class="h-6 bg-slate-100 rounded animate-pulse"></div>
          </div>

          <p v-else-if="error" class="p-6 text-sm text-red-500">{{ error }}</p>

          <p v-else-if="!result?.rows.length" class="p-6 text-sm text-slate-400">
            ردیفی پشت این عدد ثبت نشده است.
          </p>

          <table v-else class="w-full text-xs">
            <thead class="sticky top-0 bg-surface shadow-[0_1px_0_rgba(0,0,0,0.06)]">
              <tr class="text-slate-400">
                <th
                  v-for="c in result.columns" :key="c.key"
                  class="text-right font-medium px-3 py-2 whitespace-nowrap"
                >{{ c.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, i) in result.rows" :key="i"
                class="border-t border-slate-100 hover:bg-slate-50/60 transition-colors"
              >
                <td
                  v-for="c in result.columns" :key="c.key"
                  class="px-3 py-1.5 whitespace-nowrap max-w-[220px] truncate"
                  :class="c.unit ? 'text-left ltr-nums text-ink' : 'text-slate-600'"
                  :title="cell(row[c.key], c.unit)"
                >{{ cell(row[c.key], c.unit) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <footer v-if="result" class="px-5 py-2.5 border-t border-slate-100 text-xs text-slate-400 shrink-0">
          {{ result.rows.length }} ردیف از {{ result.total }}
          <span v-if="result.truncated"> — برای دیدن همه، ویجت را از نوع «جدول» بسازید.</span>
        </footer>
      </aside>
    </div>
  </Teleport>
</template>
