<script setup lang="ts">
import { computed } from "vue";

/**
 * A numeric input that groups digits in threes as you type (Excel-like:
 * 12,000,000) to cut down on Rial data-entry errors. It displays the grouped
 * value but emits the RAW numeric string (digits only, optional dot/minus),
 * so callers keep binding/saving plain numbers. The caret is preserved across
 * reformatting so typing in the middle of a number feels natural.
 */
const props = withDefaults(defineProps<{
  modelValue: string | number | null;
  /** Whole numbers only — counts, and rials, which have no fraction. */
  integer?: boolean;
  /** Allow a leading minus (a loss); off for anything that cannot go below zero. */
  signed?: boolean;
}>(), { integer: false, signed: true });
const emit = defineEmits<{ (e: "update:modelValue", v: string): void }>();

/**
 * Persian and Arabic-Indic digits typed on a Persian keyboard used to be
 * stripped by the filter below, so «۱۲۰» became an empty cell without a word.
 * They are folded to ASCII first, and «٫» is the Persian decimal point.
 */
function toLatin(s: string): string {
  return s
    .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/٫/g, ".");
}

function clean(s: string): string {
  let v = toLatin(s).replace(props.integer ? /[^\d\-]/g : /[^\d.\-]/g, "");
  v = props.signed ? v.replace(/(?!^)-/g, "") : v.replace(/-/g, ""); // minus only at the start
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
  const digitsBefore = (toLatin(el.value.slice(0, caret)).match(/[\d]/g) || []).length;

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

/**
 * Most cells start at 0. Without this, clicking one and typing 5 leaves "05"
 * — the zero is a placeholder, not a digit anyone meant to keep. Selecting it
 * on focus makes the first keystroke replace it, while a field with a real
 * value is left alone so it can still be edited in place.
 */
function onFocus(e: FocusEvent) {
  const el = e.target as HTMLInputElement;
  if (Number(props.modelValue ?? 0) === 0) el.select();
}
</script>

<template>
  <input
    :value="display"
    type="text"
    :inputmode="integer ? 'numeric' : 'decimal'"
    dir="ltr"
    @input="onInput"
    @focus="onFocus"
  />
</template>
