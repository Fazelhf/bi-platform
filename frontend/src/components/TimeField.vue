<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useClickOutside } from "@/composables/useClickOutside";
import { faDigits } from "@/utils/jalali";

/**
 * ساعت، ۲۴ساعته.
 *
 * `<input type="time">` draws whatever clock the operating system uses, and on
 * most of the company's machines that is «08:00 PM». So the time is typed
 * here (۱۴:۳۰, 1430, ۹ — Persian or Latin digits) or picked from a list in
 * 15-minute steps, and the value stays "HH:mm", exactly what the native input
 * gave, so nothing that reads it changes.
 */
const props = withDefaults(defineProps<{
  modelValue: string;
  /** Minutes between the suggestions in the list. */
  step?: number;
  ariaLabel?: string;
  inputClass?: string;
}>(), { step: 15, ariaLabel: "ساعت", inputClass: "" });
const emit = defineEmits<{ "update:modelValue": [value: string] }>();

const pad = (n: number) => String(n).padStart(2, "0");
const LATIN = (s: string) => s.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)));

/** What was typed → "HH:mm", or null if it is not a time. */
function parse(raw: string): string | null {
  const s = LATIN(raw).trim().replace(/[٫.,\s]/g, ":");
  let h: number, m: number;
  const parts = /^(\d{1,2}):(\d{1,2})$/.exec(s);
  if (parts) { h = +parts[1]; m = +parts[2]; }
  else if (/^\d{1,2}$/.test(s)) { h = +s; m = 0; }
  else if (/^\d{3,4}$/.test(s)) { h = +s.slice(0, -2); m = +s.slice(-2); }
  else return null;
  return h <= 23 && m <= 59 ? `${pad(h)}:${pad(m)}` : null;
}

const text = ref("");
watch(() => props.modelValue, (v) => { text.value = v ? faDigits(v) : ""; }, { immediate: true });

function commit() {
  const t = parse(text.value);
  if (t) emit("update:modelValue", t);
  text.value = faDigits(t ?? props.modelValue ?? "");
}

const open = ref(false);
const root = ref<HTMLElement | null>(null);
const list = ref<HTMLElement | null>(null);
useClickOutside(root, () => { if (open.value) { open.value = false; commit(); } });
const options = computed(() => {
  const out: string[] = [];
  for (let m = 0; m < 24 * 60; m += props.step) out.push(`${pad(Math.floor(m / 60))}:${pad(m % 60)}`);
  return out;
});
async function show() {
  open.value = true;
  await nextTick();
  // Start the list at the current value, or the nearest step before it.
  const cur = props.modelValue || "09:00";
  const i = Math.max(0, options.value.findIndex((o) => o >= cur) - 1);
  const el = list.value?.children[i] as HTMLElement | undefined;
  if (el && list.value) list.value.scrollTop = el.offsetTop - 4;
}
function pick(t: string) {
  emit("update:modelValue", t);
  text.value = faDigits(t);
  open.value = false;
}
</script>

<template>
  <div ref="root" class="relative">
    <input
      v-model="text" type="text" inputmode="numeric" dir="ltr" autocomplete="off" :aria-label="ariaLabel"
      placeholder="۱۴:۳۰" maxlength="5"
      :class="['text-center ltr-nums', inputClass || 'w-full bg-slate-100 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-300']"
      @focus="show" @click="!open && show()" @blur="commit" @keydown.enter.prevent="commit(); open = false" @keydown.escape="open = false"
    />
    <div v-if="open" ref="list" class="absolute z-50 mt-1 w-full max-h-56 overflow-y-auto bg-surface rounded-xl shadow-pop py-1 text-sm" role="listbox">
      <button
        v-for="o in options" :key="o" type="button" role="option" :aria-selected="o === modelValue"
        class="block w-full px-3 py-1.5 text-center ltr-nums hover:bg-slate-50"
        :class="o === modelValue ? 'bg-sky-50 text-sky-700 font-semibold' : 'text-ink'"
        @mousedown.prevent="pick(o)"
      >{{ faDigits(o) }}</button>
    </div>
  </div>
</template>
