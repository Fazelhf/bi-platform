<script setup lang="ts">
/**
 * The two things an installed app has to say for itself, and nothing else.
 *
 *   «آفلاین» — the numbers on screen are the last ones that arrived, and
 *              nothing new can come in. This app caches no API response, so
 *              offline is a real state with real consequences and it is said
 *              out loud rather than left to a failed request somewhere.
 *   «نسخه‌ی جدید» — a new bundle is downloaded and waiting. This used to be a
 *              small bar at the bottom that could be ignored forever, and
 *              people did: they kept working on an old bundle against a new
 *              server and met bugs that were already fixed. It is now a
 *              full-screen dialog with one way out — updating.
 *
 * The offline bar sits at the bottom, above the home bar, under the page's
 * own toasts (z-100). The update dialog covers everything, toasts included.
 */
import { computed } from "vue";
import { usePwa } from "@/composables/usePwa";

const { online, needsUpdate, update } = usePwa();

// Offline first: while it is true, the reload an update needs could not even
// fetch the new page.
const mustUpdate = computed(() => online.value && needsUpdate.value);

function reload() {
  window.location.reload();
}
</script>

<template>
  <div
    v-if="mustUpdate"
    class="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
    dir="rtl"
    role="alertdialog"
    aria-modal="true"
    aria-labelledby="pwa-update-title"
  >
    <div class="pwa-in w-full max-w-md bg-surface rounded-card shadow-pop p-7 text-center">
      <div
        class="mx-auto mb-5 w-16 h-16 rounded-full bg-accent-500/10 text-accent-600
               flex items-center justify-center text-3xl"
      >↻</div>
      <h2 id="pwa-update-title" class="text-lg font-bold text-ink mb-2">
        نسخه‌ی جدید برنامه آماده است
      </h2>
      <p class="text-sm text-slate-500 leading-7 mb-6">
        برای ادامه‌ی کار، برنامه باید به‌روز شود. این کار چند ثانیه طول می‌کشد
        و صفحه دوباره باز می‌شود.
      </p>
      <button
        class="w-full rounded-xl bg-accent-500 hover:bg-accent-600 text-white font-medium
               py-3 text-base transition-colors"
        @click="update"
      >به‌روزرسانی</button>
    </div>
  </div>

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
    <div v-if="!online" class="pointer-events-auto w-full max-w-md pwa-in">
      <div
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
