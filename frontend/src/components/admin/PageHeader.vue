<script setup lang="ts">
defineProps<{ title: string; description?: string }>();
</script>

<template>
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div class="min-w-0">
      <h1 class="text-lg font-bold text-ink">{{ title }}</h1>
      <p v-if="description" class="text-sm text-slate-400 mt-0.5">{{ description }}</p>
    </div>
    <div class="flex items-center gap-2 flex-wrap"><slot name="actions" /></div>
  </div>
</template>
