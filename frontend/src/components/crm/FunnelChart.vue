<script setup lang="ts">
/**
 * قیف فروش — vertical, compact, and clickable end to end.
 *
 * Three things this shape has to get right, each of which an earlier version
 * got wrong:
 *
 * **It must narrow.** Per-stage counts are a distribution, not a funnel —
 * drawn as widths they are one wide bar and eight slivers, in no useful
 * order. The width here is `remaining`: open deals at this stage *or past
 * it*, which falls monotonically by construction. That fall is the drop-off,
 * and it is the only reason to draw a funnel instead of a table.
 *
 * **The whole row must be clickable.** When the coloured band was the only
 * click target and the stage name sat in a column beside it, people clicked
 * the name — the part that reads like a row — and nothing happened. A row is
 * one `<button>` now: name, band and numbers together.
 *
 * **It must stay small.** Nine stages at a comfortable band height come to
 * ~490px and drag every card in the row to match. Each row is one line tall
 * here, so the whole funnel fits the height of an ordinary chart, and
 * everything still has a number next to it.
 */
import { computed } from "vue";
import type { ReportRow } from "@/api/crm";
import { num } from "@/utils/format";

export type Stage = ReportRow;

const props = withDefaults(defineProps<{
  stages: Stage[];
  /** Height of one stage's band. The row is this plus its gap. */
  rowHeight?: number;
}>(), { rowHeight: 24 });

const emit = defineEmits<{ (e: "pick", stage: Stage): void }>();

const GAP = 3;
/** Enough that the last stage stays a visible shape, not a hairline. */
const MIN_W = 12;

function measure(s: Stage, key: "count" | "remaining" | "remaining_pct"): number {
  return Number(s?.[key] ?? 0);
}

const widest = computed(() => measure(props.stages[0], "remaining") || 1);

/** Half-width of the funnel at row `i`'s top edge, as a percentage. */
function halfAt(i: number): number {
  const s = props.stages[i];
  if (!s) return MIN_W / 2;
  return Math.max(MIN_W, (measure(s, "remaining") / widest.value) * 100) / 2;
}

/**
 * One stage as a trapezoid in its own 0..100 box: its own width at the top,
 * the next stage's at the bottom. Consecutive rows share an edge value, so
 * the segments line up and read as a single shape despite being separate
 * elements — which is what lets each row be its own button.
 */
function segment(i: number): string {
  const top = halfAt(i);
  const bottom = i + 1 < props.stages.length ? halfAt(i + 1) : top * 0.82;
  return [
    `M ${50 - top} 0`,
    `L ${50 + top} 0`,
    `L ${50 + bottom} 100`,
    `L ${50 - bottom} 100`,
    "Z",
  ].join(" ");
}

/**
 * Violet, deepening toward the close. Only lightness moves, so the ramp
 * survives greyscale and colour-vision differences.
 */
function fill(i: number): string {
  const t = props.stages.length > 1 ? i / (props.stages.length - 1) : 0;
  return `hsl(258 72% ${70 - t * 28}%)`;
}
</script>

<template>
  <p v-if="!stages.length" class="text-xs text-slate-400">داده‌ای نیست</p>

  <div v-else class="space-y-[3px]">
    <button
      v-for="(s, i) in stages"
      :key="String(s.id)"
      class="w-full flex items-center gap-2 rounded-lg px-1 text-right
             hover:bg-slate-50 transition-colors group"
      :style="{ height: `${rowHeight + GAP}px` }"
      :title="`${s.label} — ${num(measure(s, 'remaining'))} رسیده، ${num(measure(s, 'count'))} همین‌جا`"
      @click="emit('pick', s)"
    >
      <span class="w-[38%] shrink-0 text-[11px] text-ink truncate leading-none">
        {{ s.label }}
      </span>

      <!-- preserveAspectRatio="none" stretches one 0..100 box to the column's
           real size, so consecutive segments meet flush. -->
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        :height="rowHeight"
        class="flex-1 min-w-0 block"
        aria-hidden="true"
      >
        <path
          :d="segment(i)"
          :fill="fill(i)"
          class="transition-opacity group-hover:opacity-75"
        />
      </svg>

      <span class="w-[4.6rem] shrink-0 text-left leading-none ltr-nums">
        <span class="text-[11px] font-medium text-ink">
          {{ num(measure(s, "remaining")) }}
        </span>
        <span class="text-[10px] text-slate-400">
          · {{ num(measure(s, "count")) }}
        </span>
      </span>
    </button>
  </div>
</template>
