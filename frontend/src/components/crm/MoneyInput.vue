<script setup lang="ts">
import { computed } from "vue";

/**
 * A Rial box that groups as you type.
 *
 * Prices here run to nine and ten digits, and an ungrouped `450000000` is not
 * something a person can check at a glance — the mistake that gets made is
 * one zero, and one zero is exactly the mistake an unbroken run of digits
 * hides. Grouping is display only: the value handed back is plain digits.
 *
 * It also accepts Persian and Arabic digits, because a Persian keyboard
 * produces them and a box that silently ignored ۴۵ was reported as broken.
 */
const props = withDefaults(defineProps<{
  modelValue: string | number;
  placeholder?: string;
  invalid?: boolean;
  /** Compact styling for use inside the deal-lines table. */
  cell?: boolean;
}>(), { placeholder: "", invalid: false, cell: false });

const emit = defineEmits<{ (e: "update:modelValue", v: string): void }>();

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const AR_DIGITS = "٠١٢٣٤٥٦٧٨٩";

/** Anything that is not a digit is dropped, including the group separators. */
function raw(text: string): string {
  let out = "";
  for (const ch of text) {
    const fa = FA_DIGITS.indexOf(ch);
    const ar = AR_DIGITS.indexOf(ch);
    if (fa >= 0) out += String(fa);
    else if (ar >= 0) out += String(ar);
    else if (ch >= "0" && ch <= "9") out += ch;
  }
  // A single leading zero is a value; "007" is a typo on the way to "7".
  return out.replace(/^0+(?=\d)/, "");
}

const grouped = computed(() => {
  const digits = raw(String(props.modelValue ?? ""));
  return digits ? digits.replace(/\B(?=(\d{3})+(?!\d))/g, "٬") : "";
});

function onInput(e: Event) {
  const el = e.target as HTMLInputElement;
  const next = raw(el.value);
  // Re-render from the model so the separators land in the right places.
  el.value = next ? next.replace(/\B(?=(\d{3})+(?!\d))/g, "٬") : "";
  emit("update:modelValue", next || "0");
}

const full =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";
const compact = "w-full bg-slate-100 rounded-lg px-2 py-1.5 text-sm text-ink outline-none";
</script>

<template>
  <input
    :value="grouped"
    :class="[cell ? compact : full, invalid ? 'ring-2 ring-red-300' : '']"
    :placeholder="placeholder"
    dir="ltr"
    inputmode="numeric"
    @input="onInput"
  />
</template>
