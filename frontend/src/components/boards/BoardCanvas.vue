<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import type { QueryResult } from "@/api/dashboards";
import BoardWidget from "./BoardWidget.vue";
import { COLUMNS, ROW_HEIGHT, GAP, compact, type DraftWidget } from "./layout";

/**
 * The canvas: a twelve-column grid the manager drags cards around on.
 *
 * Positions are grid units, not pixels — the whole layout is four small
 * integers per card, which is what makes a board round-trip through JSON and
 * come back identical on someone else's screen. The pixel maths below exists
 * only to translate a pointer into those integers.
 *
 * On a narrow screen the grid collapses to one column in reading order. That
 * is not a fallback: a report laid out for a desk is unreadable at 390px, and
 * a manager checking a figure on their phone wants the cards, not the layout.
 */
const props = withDefaults(defineProps<{
  widgets: DraftWidget[];
  results?: Record<string, { data?: QueryResult; error?: string }>;
  loading?: boolean;
  editing?: boolean;
}>(), { results: () => ({}), loading: false, editing: false });

const emit = defineEmits<{
  (e: "update:widgets", value: DraftWidget[]): void;
  (e: "edit", uid: string): void;
  (e: "remove", uid: string): void;
  (e: "duplicate", uid: string): void;
  (e: "drill", uid: string, key: string, label: string): void;
}>();

const root = ref<HTMLElement | null>(null);
const width = ref(1200);
const rtl = ref(true);

/** One column, in pixels — the unit every drag is rounded to. */
const colWidth = computed(() => (width.value - GAP * (COLUMNS - 1)) / COLUMNS);
/** Below this the grid is meaningless; cards stack instead. */
const narrow = computed(() => width.value < 820);

let observer: ResizeObserver | null = null;

function measure() {
  if (root.value) width.value = root.value.clientWidth;
}

onMounted(() => {
  if (!root.value) return;
  rtl.value = getComputedStyle(root.value).direction === "rtl";
  observer = new ResizeObserver(([entry]) => {
    width.value = entry.contentRect.width;
  });
  observer.observe(root.value);
  // The observer catches the sidebar collapsing, which no window event
  // reports; the window listener catches the rest, including the case where
  // the observer's callbacks are throttled with the frames they ride on.
  window.addEventListener("resize", measure);
  measure();
});

onBeforeUnmount(() => {
  observer?.disconnect();
  window.removeEventListener("resize", measure);
});

// ---------------------------------------------------------------- dragging
type Mode = "move" | "resize";
const active = ref<{ uid: string; mode: Mode } | null>(null);
let start = { px: 0, py: 0, x: 0, y: 0, w: 0, h: 0 };

function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(v, max));
}

function begin(event: PointerEvent, widget: DraftWidget, mode: Mode) {
  if (!props.editing || narrow.value) return;
  // Only the primary button, and never on top of the card's own controls.
  if (event.button !== 0) return;
  event.preventDefault();
  active.value = { uid: widget.uid, mode };
  start = {
    px: event.clientX, py: event.clientY,
    x: widget.x, y: widget.y, w: widget.w, h: widget.h,
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp, { once: true });
}

function onMove(event: PointerEvent) {
  const state = active.value;
  if (!state) return;
  // In RTL, column 1 is the rightmost — moving the pointer left increases x.
  const sign = rtl.value ? -1 : 1;
  const dCol = Math.round((sign * (event.clientX - start.px)) / (colWidth.value + GAP));
  const dRow = Math.round((event.clientY - start.py) / (ROW_HEIGHT + GAP));

  const next = props.widgets.map((w) => {
    if (w.uid !== state.uid) return w;
    if (state.mode === "move") {
      const width_ = w.w;
      return {
        ...w,
        x: clamp(start.x + dCol, 0, COLUMNS - width_),
        y: Math.max(0, start.y + dRow),
      };
    }
    const newW = clamp(start.w + dCol, 2, COLUMNS - w.x);
    return { ...w, w: newW, h: Math.max(2, start.h + dRow) };
  });
  emit("update:widgets", next);
}

function onUp() {
  window.removeEventListener("pointermove", onMove);
  const state = active.value;
  active.value = null;
  if (!state) return;
  // Settle everything upward, with the card just dropped claiming its row
  // first — otherwise it loses the spot it was dragged onto.
  emit("update:widgets", compact(props.widgets, state.uid));
}

function styleFor(widget: DraftWidget) {
  if (narrow.value) {
    return {
      gridColumn: "1 / -1",
      gridRow: `auto / span ${Math.max(widget.h, 3)}`,
    };
  }
  return {
    gridColumn: `${widget.x + 1} / span ${widget.w}`,
    gridRow: `${widget.y + 1} / span ${widget.h}`,
  };
}

const ordered = computed(() =>
  narrow.value
    ? [...props.widgets].sort((a, b) => a.y - b.y || a.x - b.x)
    : props.widgets,
);
</script>

<template>
  <div
    ref="root"
    class="grid w-full"
    :style="{
      gridTemplateColumns: `repeat(${COLUMNS}, minmax(0, 1fr))`,
      gridAutoRows: `${ROW_HEIGHT}px`,
      gap: `${GAP}px`,
    }"
  >
    <div
      v-for="widget in ordered"
      :key="widget.uid"
      class="relative min-w-0 group"
      :style="styleFor(widget)"
      :class="active?.uid === widget.uid ? 'z-20 opacity-90' : ''"
    >
      <BoardWidget
        :widget="widget"
        :result="results[widget.uid]?.data ?? null"
        :error="results[widget.uid]?.error ?? ''"
        :loading="loading"
        :editing="editing"
        @edit="emit('edit', widget.uid)"
        @remove="emit('remove', widget.uid)"
        @duplicate="emit('duplicate', widget.uid)"
        @drill="(key, label) => emit('drill', widget.uid, key, label)"
      />

      <!-- Edit-mode furniture. The grip is a strip, not the whole card, so a
           chart stays hoverable (and its tooltip readable) while editing. -->
      <template v-if="editing && !narrow">
        <div
          class="absolute top-0 right-0 h-8 w-[calc(100%-92px)] cursor-move"
          title="برای جابه‌جایی بکشید"
          @pointerdown="begin($event, widget, 'move')"
        ></div>
        <div
          class="absolute bottom-0 left-0 w-5 h-5 cursor-nesw-resize opacity-0 group-hover:opacity-100
                 hover:opacity-100 transition-opacity"
          title="برای تغییر اندازه بکشید"
          @pointerdown="begin($event, widget, 'resize')"
        >
          <svg viewBox="0 0 20 20" class="w-full h-full text-slate-400">
            <path d="M4 16h12M8 16v-4" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" />
          </svg>
        </div>
      </template>
    </div>
  </div>
</template>
