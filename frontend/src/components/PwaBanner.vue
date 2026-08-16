<script setup lang="ts">
/**
 * The two things an installed app has to say for itself, and nothing else.
 *
 *   «آفلاین» — the numbers on screen are the last ones that arrived, and
 *              nothing new can come in. This app caches no API response, so
 *              offline is a real state with real consequences and it is said
 *              out loud rather than left to a failed request somewhere.
 *   «نسخه‌ی جدید» — a new bundle is already downloaded and waiting. Offered,
 *              never taken: reloading someone mid-form to install a fix is a
 *              worse bug than the one being fixed.
 *
 * Both sit at the bottom, above the home bar, out of the way of the sidebar
 * and the page's own toasts (which own z-100; these sit just under).
 */
import { computed } from "vue";
import { usePwa } from "@/composables/usePwa";

const { online, needsUpdate, update } = usePwa();

const show = computed(() => !online.value || needsUpdate.value);

function reload() {
  window.location.reload();
}
</script>

<template>
  <div
    class="fixed bottom-0 inset-x-0 z-[95] flex justify-center px-3 pointer-events-none"
    style="padding-bottom: calc(env(safe-area-inset-bottom, 0px) + 0.75rem)"
    dir="rtl"
  >
    <!-- Appears with a CSS animation and disappears at once, rather than
         through a <transition>. Vue's leave transition removes the element
         only when `transitionend` fires, and a backgrounded tab gets no
         animation frames — which is precisely the case here: the phone is in
         a pocket when the network comes back. That left an invisible card
         with `pointer-events-auto` parked over the bottom of the screen,
         eating taps. Nothing to get stuck now. -->
      <div v-if="show" class="pointer-events-auto w-full max-w-md pwa-in">
        <!-- Offline first: while it is true, an update offer is beside the
             point — the reload it asks for could not even fetch the page. -->
        <div
          v-if="!online"
          class="bg-amber-500 text-white rounded-2xl shadow-pop px-4 py-3
                 flex items-center gap-3"
        >
          <span class="w-2.5 h-2.5 rounded-full bg-white/90 animate-pulse shrink-0"></span>
          <span class="text-sm flex-1 leading-6">
            اتصال اینترنت قطع است — اعداد به‌روز نمی‌شوند.
          </span>
          <button
            class="text-xs bg-white/20 hover:bg-white/30 rounded-lg px-3 py-1.5 transition"
            @click="reload"
          >تلاش دوباره</button>
        </div>

        <div
          v-else
          class="bg-panel text-white rounded-2xl shadow-pop px-4 py-3
                 flex items-center gap-3"
        >
          <span class="text-base shrink-0">↻</span>
          <span class="text-sm flex-1 leading-6">نسخه‌ی جدید برنامه آماده است.</span>
          <button
            class="text-xs bg-white text-ink font-medium rounded-lg px-3 py-1.5
                   hover:bg-slate-100 transition"
            @click="update"
          >به‌روزرسانی</button>
        </div>
      </div>
  </div>
</template>

<style scoped>
.pwa-in {
  animation: pwa-rise 0.25s ease both;
}
@keyframes pwa-rise {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .pwa-in {
    animation: none;
  }
}
</style>
