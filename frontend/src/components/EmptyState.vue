<script setup lang="ts">
/**
 * A friendly placeholder for empty lists/tables: an icon, a short title, and a
 * hint that tells the user what will fill this space. Pass an emoji via `icon`
 * or richer markup via the `icon` slot; use the `action` slot for a CTA button.
 */
withDefaults(
  defineProps<{ icon?: string; title?: string; hint?: string }>(),
  { icon: "📭", title: "چیزی برای نمایش نیست", hint: "" },
);
</script>

<template>
  <div class="flex flex-col items-center justify-center text-center px-6 py-12">
    <div
      class="w-14 h-14 rounded-2xl bg-canvas flex items-center justify-center text-3xl mb-4 select-none"
    >
      <slot name="icon">{{ icon }}</slot>
    </div>
    <p class="font-semibold text-ink">{{ title }}</p>
    <p v-if="hint" class="text-sm text-slate-400 mt-1 max-w-xs leading-6">{{ hint }}</p>
    <div v-if="$slots.action" class="mt-4">
      <slot name="action" />
    </div>
  </div>
</template>
