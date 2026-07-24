<script setup lang="ts">
/**
 * A single shimmering placeholder block. Compose several to sketch the shape
 * of the content that is loading — a KPI card, a chart, a table row.
 * Size and rounding come from the caller via `class` (e.g. class="h-4 w-24").
 */
withDefaults(defineProps<{ rounded?: string }>(), { rounded: "rounded-lg" });
</script>

<template>
  <div class="skeleton" :class="rounded"></div>
</template>
