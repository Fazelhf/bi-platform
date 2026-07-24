<script setup lang="ts">
import { computed } from "vue";

/**
 * A numeric input that groups digits in threes as you type (Excel-like:
 * 12,000,000) to cut down on Rial data-entry errors. It displays the grouped
 * value but emits the RAW numeric string (digits only, optional dot/minus),
 * so callers keep binding/saving plain numbers. The caret is preserved across
 * reformatting so typing in the middle of a number feels natural.
 */
const props = defineProps<{ modelValue: string | number | null }>();
const emit = defineEmits<{ (e: "update:modelValue", v: string): void }>();

function clean(s: string): string {
  let v = s.replace(/[^\d.\-]/g, "");
  v = v.replace(/(?!^)-/g, ""); // minus only at the start
  const dot = v.indexOf(".");
  if (dot !== -1) v = v.slice(0, dot + 1) + v.slice(dot + 1).replace(/\./g, "");
  return v;
}

function group(raw: string): string {
  if (raw === "" || raw === "-") return raw;
  const neg = raw.startsWith("-");
  let [int, frac] = raw.replace("-", "").split(".");
  int = int.replace(/^0+(?=\d)/, "") || "0";
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (neg ? "-" : "") + grouped + (frac !== undefined ? "." + frac : "");
}

const display = computed(() => group(clean(String(props.modelValue ?? ""))));

function onInput(e: Event) {
  const el = e.target as HTMLInputElement;
  const caret = el.selectionStart ?? el.value.length;
  const digitsBefore = (el.value.slice(0, caret).match(/[\d]/g) || []).length;

  const raw = clean(el.value);
  const formatted = group(raw);
  el.value = formatted;

  // Restore the caret after the same number of digits it was before.
  let pos = 0, seen = 0;
  while (pos < formatted.length && seen < digitsBefore) {
    if (/\d/.test(formatted[pos])) seen++;
    pos++;
  }
  el.setSelectionRange(pos, pos);

  emit("update:modelValue", raw);
}
</script>

<template>
  <input
    :value="display"
    type="text"
    inputmode="decimal"
    dir="ltr"
    @input="onInput"
  />
</template>
