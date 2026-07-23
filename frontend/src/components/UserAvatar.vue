<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    name?: string;
    initials?: string;
    color?: string;
    image?: string;
    online?: boolean;
    size?: number;
    showDot?: boolean;
    ring?: boolean;
  }>(),
  { size: 40, showDot: true, ring: false },
);

const style = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  backgroundColor: props.color || "#64748b",
  fontSize: `${Math.round(props.size * 0.38)}px`,
}));

const dotSize = computed(() => Math.max(9, Math.round(props.size * 0.28)));
</script>

<template>
  <div class="relative inline-flex shrink-0">
    <img
      v-if="image"
      :src="image"
      alt=""
      class="rounded-full object-cover select-none"
      :class="ring ? 'ring-2 ring-white' : ''"
      :style="{ width: `${size}px`, height: `${size}px` }"
    />
    <div
      v-else
      class="rounded-full flex items-center justify-center text-white font-semibold select-none"
      :class="ring ? 'ring-2 ring-white' : ''"
      :style="style"
    >
      {{ initials || (name ? name.slice(0, 2) : "؟") }}
    </div>
    <span
      v-if="showDot"
      class="absolute -bottom-0.5 -left-0.5 rounded-full ring-2 ring-white"
      :class="online ? 'bg-accent-500' : 'bg-slate-300'"
      :style="{ width: dotSize + 'px', height: dotSize + 'px' }"
    ></span>
  </div>
</template>
