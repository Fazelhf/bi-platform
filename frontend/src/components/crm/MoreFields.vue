<script setup lang="ts">
import { ref } from "vue";
import NavIcon from "@/components/NavIcon.vue";

/**
 * «اطلاعات بیشتر» — the fold that keeps an entry form short.
 *
 * A rep entering a lead between two calls needs to answer two questions, not
 * fourteen. Every field the form *could* accept is still here; it is just not
 * in the way of the answer that matters. The pattern only works if the fold
 * is honest about what it hides, so a collapsed section that already holds
 * answers says how many — otherwise editing an existing record looks like it
 * lost half its data.
 */
const props = withDefaults(defineProps<{
  label?: string;
  /** How many of the fields inside already carry a value. */
  filled?: number;
  startOpen?: boolean;
}>(), { label: "اطلاعات بیشتر", filled: 0, startOpen: false });

const open = ref(props.startOpen);
const FA = new Intl.NumberFormat("fa-IR");
</script>

<template>
  <div class="border-t border-slate-100 pt-3">
    <button
      type="button"
      class="w-full flex items-center gap-2 text-sm text-slate-500 hover:text-ink transition-colors"
      :aria-expanded="open"
      @click="open = !open"
    >
      <NavIcon
        name="chevron" :size="16"
        class="transition-transform shrink-0"
        :class="open ? 'rotate-90' : ''"
      />
      <span>{{ label }}</span>
      <span
        v-if="!open && filled"
        class="text-[11px] bg-slate-100 text-slate-500 rounded-full px-2 py-0.5"
      >{{ FA.format(filled) }} مورد پر شده</span>
      <span class="flex-1"></span>
      <span class="text-xs text-slate-300">{{ open ? "بستن" : "باز کردن" }}</span>
    </button>

    <div v-if="open" class="mt-3 space-y-3">
      <slot />
    </div>
  </div>
</template>
