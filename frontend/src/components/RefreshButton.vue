<script setup lang="ts">
/**
 * «تازه‌سازی» in the header.
 *
 * Installed from the home screen the app has no address bar and no reload
 * button, so the only way to see fresh figures — or pick up a new release —
 * was to kill the app and open it again. This is that button, and it also
 * installs a waiting release instead of reloading onto the old one.
 */
import { ref } from "vue";
import { usePwa } from "@/composables/usePwa";

const { refresh } = usePwa();
const busy = ref(false);

async function run() {
  if (busy.value) return;
  busy.value = true;
  await refresh();
}
</script>

<template>
  <button
    class="p-2 rounded-full hover:bg-slate-100 text-slate-600 transition-colors"
    title="تازه‌سازی"
    aria-label="تازه‌سازی"
    @click="run"
  >
    <svg
      xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
      stroke-linejoin="round" class="w-5 h-5" :class="busy ? 'animate-spin' : ''"
    >
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <path d="M21 3v6h-6" />
    </svg>
  </button>
</template>
