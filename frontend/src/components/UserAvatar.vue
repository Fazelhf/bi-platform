<script setup lang="ts">
import { computed } from "vue";

/**
 * The shape the office and CRM APIs serialise a person as. Passing it whole
 * as `user` is what most callers were already doing — but the prop did not
 * exist, so every avatar there fell through to a grey «؟».
 */
interface AvatarUser {
  name?: string;
  display_name_fa?: string;
  username?: string;
  initials?: string;
  avatar_color?: string;
  avatar_image?: string;
  is_online?: boolean;
}

const props = withDefaults(
  defineProps<{
    user?: AvatarUser | null;
    name?: string;
    initials?: string;
    color?: string;
    image?: string;
    online?: boolean;
    size?: number;
    showDot?: boolean;
    ring?: boolean;
  }>(),
  { size: 40, showDot: true, ring: false, online: undefined },
);

const displayName = computed(
  () => props.name || props.user?.name || props.user?.display_name_fa || props.user?.username || "",
);
const label = computed(
  () => props.initials || props.user?.initials || displayName.value.trim().slice(0, 2) || "؟",
);
const img = computed(() => props.image || props.user?.avatar_image || "");
const isOnline = computed(() => props.online ?? props.user?.is_online);

const style = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  backgroundColor: props.color || props.user?.avatar_color || "#64748b",
  fontSize: `${Math.round(props.size * 0.38)}px`,
}));

const dotSize = computed(() => Math.max(9, Math.round(props.size * 0.28)));
</script>

<template>
  <div class="relative inline-flex shrink-0" :title="displayName || undefined">
    <img
      v-if="img"
      :src="img"
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
      {{ label }}
    </div>
    <!-- Presence is only drawn when it is known. A grey dot on every avatar
         in a letter list said «offline» about people nobody had asked about. -->
    <span
      v-if="showDot && isOnline !== undefined"
      class="absolute -bottom-0.5 -left-0.5 rounded-full ring-2 ring-white"
      :class="isOnline ? 'bg-accent-500' : 'bg-slate-300'"
      :style="{ width: dotSize + 'px', height: dotSize + 'px' }"
    ></span>
  </div>
</template>
