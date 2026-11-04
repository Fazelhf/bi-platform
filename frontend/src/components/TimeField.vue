<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { useClickOutside } from "@/composables/useClickOutside";

/**
 * ساعت، ۲۴ساعته — the browser's own time picker, minus its AM/PM.
 *
 * `<input type="time">` draws whatever clock the operating system uses, and on
 * most of the company's machines that is «08:30 AM». This keeps its look —
 * a field with a clock, opening two scrolling columns, hour then minute, the
 * chosen one in blue — on a 24-hour clock. The value stays "HH:mm", exactly
 * what the native input gave, so nothing that reads it changes.
 */
const props = withDefaults(defineProps<{
  modelValue: string;
  ariaLabel?: string;
  /** Classes for the field itself. */
  inputClass?: string;
}>(), { ariaLabel: "ساعت", inputClass: "" });
const emit = defineEmits<{ "update:modelValue": [value: string] }>();

const pad = (n: number) => String(n).padStart(2, "0");
const HOURS = Array.from({ length: 24 }, (_, i) => pad(i));
const MINUTES = Array.from({ length: 60 }, (_, i) => pad(i));

const parts = computed(() => {
  const m = /^(\d{1,2}):(\d{1,2})/.exec(props.modelValue || "");
  return m ? { h: pad(Math.min(23, +m[1])), m: pad(Math.min(59, +m[2])) } : { h: "09", m: "00" };
});

const open = ref(false);
const root = ref<HTMLElement | null>(null);
const hourCol = ref<HTMLElement | null>(null);
const minCol = ref<HTMLElement | null>(null);
useClickOutside(root, () => (open.value = false));

/** Bring the chosen hour and minute to the top of their columns, as the native picker does. */
function scrollToChosen() {
  for (const [col, v] of [[hourCol.value, parts.value.h], [minCol.value, parts.value.m]] as const) {
    const el = col?.querySelector<HTMLElement>(`[data-v="${v}"]`);
    if (col && el) col.scrollTop = el.offsetTop - col.offsetTop;
  }
}
async function toggle() {
  open.value = !open.value;
  if (open.value) { await nextTick(); scrollToChosen(); }
}
function setHour(h: string) { emit("update:modelValue", `${h}:${parts.value.m}`); }
function setMinute(m: string) { emit("update:modelValue", `${parts.value.h}:${m}`); }

/** Arrow keys step the hour (or, with Shift, the minute) without opening the list. */
function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") { open.value = false; return; }
  if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
  e.preventDefault();
  const d = e.key === "ArrowUp" ? 1 : -1;
  if (e.shiftKey) setMinute(pad((+parts.value.m + d + 60) % 60));
  else setHour(pad((+parts.value.h + d + 24) % 24));
}
</script>

<template>
  <div ref="root" class="relative" dir="ltr">
    <button
      type="button" :aria-label="ariaLabel" aria-haspopup="listbox" :aria-expanded="open"
      :class="['w-full flex items-center justify-between gap-2 text-left focus:outline-none focus:ring-2 focus:ring-sky-300',
               inputClass || 'bg-slate-100 rounded-xl px-3 py-2 text-sm']"
      @click="toggle" @keydown="onKey"
    >
      <span class="tabular-nums text-ink">{{ parts.h }}:{{ parts.m }}</span>
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9"
           stroke-linecap="round" stroke-linejoin="round" class="text-slate-500 shrink-0" aria-hidden="true">
        <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
      </svg>
    </button>

    <div v-if="open" class="absolute z-50 mt-1 left-0 flex gap-1 p-1 bg-surface rounded-xl shadow-pop border border-slate-200">
      <div ref="hourCol" class="h-56 w-12 overflow-y-auto overscroll-contain no-scrollbar" role="listbox" aria-label="ساعت">
        <button
          v-for="h in HOURS" :key="h" type="button" role="option" :data-v="h" :aria-selected="h === parts.h"
          class="block w-full rounded-md py-1.5 text-center text-sm tabular-nums"
          :class="h === parts.h ? 'bg-sky-500 text-white font-semibold' : 'text-ink hover:bg-slate-100'"
          @click="setHour(h)"
        >{{ h }}</button>
      </div>
      <div ref="minCol" class="h-56 w-12 overflow-y-auto overscroll-contain no-scrollbar" role="listbox" aria-label="دقیقه">
        <button
          v-for="m in MINUTES" :key="m" type="button" role="option" :data-v="m" :aria-selected="m === parts.m"
          class="block w-full rounded-md py-1.5 text-center text-sm tabular-nums"
          :class="m === parts.m ? 'bg-sky-500 text-white font-semibold' : 'text-ink hover:bg-slate-100'"
          @click="setMinute(m); open = false"
        >{{ m }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.no-scrollbar { scrollbar-width: thin; }
</style>
