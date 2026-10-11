<script setup lang="ts">
/**
 * A rial figure with its sign, laid out right in an RTL page.
 *
 * «+۴۷۰٫۹ میلیارد» has to keep its sign beside its digits: left to the bidi
 * algorithm, the plus sign drifts to the far side of the number. The number
 * and sign are isolated left-to-right; the unit word stays in the sentence.
 */
import { computed } from "vue";
import { useMoney } from "@/composables/useMoney";

const props = withDefaults(defineProps<{ value: number; signed?: boolean; pct?: number | null }>(), {
  signed: false,
  pct: null,
});
const { money } = useMoney();
const FA = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });

const parts = computed(() => {
  const text = money(Math.abs(props.value), false);
  const i = text.indexOf(" ");
  return i < 0 ? [text, ""] : [text.slice(0, i), text.slice(i + 1)];
});
const sign = computed(() =>
  props.value > 0 ? (props.signed ? "+" : "") : props.value < 0 ? "−" : "",
);
const pctText = computed(() =>
  props.pct === null || props.pct === undefined
    ? ""
    : `${props.pct > 0 ? "+" : props.pct < 0 ? "−" : ""}${FA.format(Math.abs(props.pct))}٪`,
);
</script>

<template>
  <span class="whitespace-nowrap"><bdi dir="ltr">{{ sign }}{{ parts[0] }}</bdi><template v-if="parts[1]">&nbsp;{{ parts[1] }}</template><template v-if="pctText">&nbsp;<bdi dir="ltr" class="text-[0.85em] opacity-90">({{ pctText }})</bdi></template></span>
</template>
