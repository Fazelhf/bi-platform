<script setup lang="ts">
import Skeleton from "@/components/Skeleton.vue";

/** Placeholder that mirrors a dashboard's shape while its data loads. */
withDefaults(
  defineProps<{ cards?: number; charts?: number; rows?: number; table?: boolean }>(),
  { cards: 4, charts: 2, rows: 6, table: true },
);
</script>

<template>
  <div class="space-y-6" aria-hidden="true">
    <!-- KPI cards -->
    <div v-if="cards" class="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <div
        v-for="i in cards"
        :key="i"
        class="bg-surface rounded-card shadow-soft p-4"
      >
        <Skeleton class="h-3.5 w-24 mb-3" />
        <Skeleton class="h-7 w-28 mb-2" />
        <Skeleton class="h-2.5 w-16" />
      </div>
    </div>

    <!-- Charts -->
    <div v-if="charts" class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div
        v-for="i in charts"
        :key="i"
        class="bg-surface rounded-card shadow-soft p-4"
      >
        <Skeleton class="h-3.5 w-40 mb-4" />
        <Skeleton class="h-48 w-full" rounded="rounded-xl" />
      </div>
    </div>

    <!-- Table -->
    <div v-if="table" class="bg-surface rounded-card shadow-soft p-4">
      <Skeleton class="h-3.5 w-48 mb-4" />
      <div class="space-y-3">
        <div v-for="i in rows" :key="i" class="flex items-center gap-4">
          <Skeleton class="h-3 w-6" />
          <Skeleton class="h-3 flex-1" />
          <Skeleton class="h-3 w-20" />
        </div>
      </div>
    </div>
  </div>
</template>
