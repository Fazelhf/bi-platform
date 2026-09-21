<script setup lang="ts">
/** A table header that sorts on click and says which way it is sorted. */
defineProps<{ label: string; dir: "asc" | "desc" | ""; align?: "right" | "left" }>();
defineEmits<{ (e: "sort"): void }>();
</script>

<template>
  <th class="font-medium px-3 py-3 select-none" :class="align === 'left' ? 'text-left' : 'text-right'">
    <button
      class="inline-flex items-center gap-1 hover:text-ink transition"
      :class="dir ? 'text-ink' : ''"
      :aria-sort="dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none'"
      @click="$emit('sort')"
    >
      {{ label }}
      <svg class="w-3 h-3" :class="dir ? 'opacity-100' : 'opacity-30'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <path v-if="dir === 'asc'" stroke-linecap="round" stroke-linejoin="round" d="M6 15l6-6 6 6" />
        <path v-else-if="dir === 'desc'" stroke-linecap="round" stroke-linejoin="round" d="M6 9l6 6 6-6" />
        <path v-else stroke-linecap="round" stroke-linejoin="round" d="M8 9l4-4 4 4M8 15l4 4 4-4" />
      </svg>
    </button>
  </th>
</template>
