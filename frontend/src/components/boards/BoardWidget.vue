<script setup lang="ts">
import { computed } from "vue";
import type { BoardWidget, QueryResult } from "@/api/dashboards";
import BoardChart from "./BoardChart.vue";
import BoardGauge from "./BoardGauge.vue";
import BoardKpi from "./BoardKpi.vue";
import BoardTable from "./BoardTable.vue";

/**
 * One card: the shell, and whichever renderer its kind calls for.
 *
 * Nothing here fetches. The board runs every widget's query in one batch and
 * hands the answer down, so fourteen cards do not open fourteen connections —
 * and so a card in the editor's preview and the same card on the live board
 * are rendered by exactly the same code.
 */
const props = withDefaults(defineProps<{
  widget: BoardWidget;
  result?: QueryResult | null;
  error?: string;
  loading?: boolean;
  editing?: boolean;
}>(), { result: null, error: "", loading: false, editing: false });

const emit = defineEmits<{
  (e: "edit"): void;
  (e: "remove"): void;
  (e: "duplicate"): void;
  (e: "drill", key: string, label: string): void;
}>();

/**
 * A click on a bar means "what is this made of?" — except while arranging the
 * board, where the same click is aimed at the card, not at the data.
 */
function drill(key: string, label: string) {
  if (props.editing) return;
  emit("drill", key, label);
}

const CHART_KINDS = ["bar", "hbar", "line", "area", "stacked", "pie", "donut"];

const isChart = computed(() => CHART_KINDS.includes(props.widget.kind));
const isStatic = computed(() =>
  props.widget.kind === "text" || props.widget.kind === "divider");

/**
 * "Nothing to draw" and "nothing happened" are different answers and a card
 * must not silently show the first as the second — an empty chart reads as a
 * month of zero sales rather than as a month nobody has keyed yet.
 */
const isEmpty = computed(() => {
  const r = props.result;
  if (!r) return false;
  if (isChart.value || props.widget.kind === "table") return !r.categories.length;
  return false;
});
</script>

<template>
  <!-- Layout kinds are not cards: a section title inside a white box would be
       a heading with a border around it. -->
  <div v-if="widget.kind === 'divider'" class="h-full flex items-end pb-1 group relative">
    <div class="w-full">
      <h3 class="text-sm font-bold text-ink">{{ widget.title }}</h3>
      <p v-if="widget.subtitle" class="text-xs text-slate-400 mt-0.5">{{ widget.subtitle }}</p>
      <div class="h-px bg-slate-200 mt-2"></div>
    </div>
    <div v-if="editing" class="absolute top-0 left-0 flex gap-1">
      <button class="board-act" title="ویرایش" @click.stop="emit('edit')">✎</button>
      <button class="board-act" title="حذف" @click.stop="emit('remove')">🗑</button>
    </div>
  </div>

  <div
    v-else
    class="bg-surface rounded-card shadow-soft h-full flex flex-col overflow-hidden relative group"
    :class="editing ? 'ring-1 ring-slate-200' : ''"
  >
    <!-- Header: kept out of the way when there is nothing to say -->
    <div
      v-if="widget.title || widget.subtitle || editing"
      class="px-4 pt-3 pb-1 flex items-start justify-between gap-2 shrink-0"
    >
      <div class="min-w-0">
        <h3 v-if="widget.title" class="text-sm font-semibold text-ink truncate" :title="widget.title">
          {{ widget.title }}
        </h3>
        <p v-if="widget.subtitle" class="text-[11px] text-slate-400 truncate">{{ widget.subtitle }}</p>
      </div>
      <div
        v-if="editing"
        class="flex gap-1 shrink-0 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity no-print"
      >
        <button class="board-act" title="ویرایش" @click.stop="emit('edit')">✎</button>
        <button class="board-act" title="تکثیر" @click.stop="emit('duplicate')">⧉</button>
        <button class="board-act hover:text-red-500" title="حذف" @click.stop="emit('remove')">🗑</button>
      </div>
    </div>

    <div class="flex-1 min-h-0 px-4 pb-3" :class="widget.kind === 'kpi' ? 'pt-0' : ''">
      <!-- text -->
      <p
        v-if="widget.kind === 'text'"
        class="text-sm text-slate-600 whitespace-pre-line leading-6 h-full overflow-auto"
      >{{ widget.options.text || "…" }}</p>

      <!-- loading / error / empty -->
      <div v-else-if="loading" class="h-full flex items-center justify-center">
        <div class="w-full space-y-2">
          <div class="h-2.5 bg-slate-100 rounded animate-pulse w-2/3"></div>
          <div class="h-2.5 bg-slate-100 rounded animate-pulse w-full"></div>
          <div class="h-2.5 bg-slate-100 rounded animate-pulse w-4/5"></div>
        </div>
      </div>
      <p
        v-else-if="error"
        class="h-full flex items-center justify-center text-xs text-red-500 text-center px-2"
      >{{ error }}</p>
      <p
        v-else-if="isEmpty"
        class="h-full flex items-center justify-center text-xs text-slate-400 text-center px-2"
      >برای این بازه داده‌ای ثبت نشده است.</p>

      <!-- the real thing -->
      <template v-else-if="result">
        <BoardKpi
          v-if="widget.kind === 'kpi' || widget.kind === 'progress'"
          :kind="widget.kind as 'kpi' | 'progress'"
          :result="result"
          :options="widget.options"
        />
        <BoardGauge v-else-if="widget.kind === 'gauge'" :result="result" :options="widget.options" />
        <BoardTable
          v-else-if="widget.kind === 'table'"
          :result="result" :options="widget.options" @drill="drill"
        />
        <BoardChart
          v-else-if="isChart"
          :kind="widget.kind" :result="result" :options="widget.options" @drill="drill"
        />
      </template>

      <p v-else-if="!isStatic" class="h-full flex items-center justify-center text-xs text-slate-400">
        هنوز داده‌ای انتخاب نشده است.
      </p>
    </div>

    <!-- The provenance line: which month, and whether it is approved data.
         Without it a card is a number with no story behind it. -->
    <p
      v-if="result && !isStatic"
      class="px-4 pb-2 text-[10px] text-slate-300 truncate shrink-0"
      :title="`${result.dataset_label} — ${result.period_label}`"
    >
      {{ result.period_label }}<span v-if="result.approved_only"> · فقط تاییدشده</span>
    </p>
  </div>
</template>

<style scoped>
.board-act {
  @apply w-6 h-6 rounded-lg bg-slate-100 text-slate-500 text-xs leading-none
         flex items-center justify-center hover:bg-slate-200 hover:text-ink transition;
}
</style>
