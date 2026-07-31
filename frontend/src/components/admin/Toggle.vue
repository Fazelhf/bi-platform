<script setup lang="ts">
defineProps<{
  modelValue: boolean;
  label?: string;
  hint?: string;
  disabled?: boolean;
}>();
const emit = defineEmits<{ (e: "update:modelValue", value: boolean): void }>();
</script>

<template>
  <label
    class="flex items-start gap-3 cursor-pointer select-none"
    :class="{ 'opacity-50 cursor-not-allowed': disabled }"
  >
    <button
      type="button"
      role="switch"
      :aria-checked="modelValue"
      :disabled="disabled"
      class="relative w-11 h-6 rounded-full transition-colors shrink-0 mt-0.5"
      :class="modelValue ? 'bg-accent-500' : 'bg-slate-300'"
      @click="!disabled && emit('update:modelValue', !modelValue)"
    >
      <!-- RTL: the knob rests at the start (right) when off and travels
           toward the end (left) when on. -->
      <span
        class="absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-all"
        :class="modelValue ? 'right-[22px]' : 'right-0.5'"
      ></span>
    </button>
    <span v-if="label || hint" class="min-w-0">
      <span v-if="label" class="block text-sm text-ink">{{ label }}</span>
      <span v-if="hint" class="block text-xs text-slate-400">{{ hint }}</span>
    </span>
  </label>
</template>
