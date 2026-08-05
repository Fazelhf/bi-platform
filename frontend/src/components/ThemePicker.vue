<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from "vue";
import { useUiStore } from "@/stores/ui";
import { useClickOutside } from "@/composables/useClickOutside";
import { SKINS, type SkinKey } from "@/lib/skins";

/**
 * «ظاهر» — the per-user appearance picker, and the only control for it: the
 * light/dark switch lives inside this panel rather than as a second button
 * in the topbar.
 *
 * Two independent choices: the skin (کلاسیک / شیشه‌ای / شفق) and the mode
 * (روشن / شب). Both are per-device preferences, so the same account can be
 * glass-and-dark on a laptop and classic-and-light on the shop-floor terminal.
 *
 * The panel is teleported to <body> and positioned with `fixed`. It has to
 * be: in شیشه‌ای every card carries a backdrop-filter, and that makes the
 * card a stacking context — an absolutely-positioned child could not escape
 * it at any z-index, so the panel rendered *behind* the page content and was
 * impossible to click. Teleporting sidesteps the whole ancestor chain.
 *
 * The tiles preview themselves rather than describing themselves — each one
 * renders its own page colour, card colour and corner radius, in whichever
 * mode is currently selected, so the choice is visible before it is made.
 */
const ui = useUiStore();
const open = ref(false);
const root = ref<HTMLElement | null>(null);
const panel = ref<HTMLElement | null>(null);
const pos = ref({ top: 0, left: 0 });

const PANEL_W = 304; // 19rem, kept in sync with the class below
const GAP = 8;

/** Anchor the panel to the trigger, flipping above it when the viewport runs
 *  out below (the sign-in card sits near the bottom of its column). */
function place() {
  const el = root.value;
  if (!el) return;
  const r = el.getBoundingClientRect();
  const h = panel.value?.offsetHeight ?? 380;
  const below = window.innerHeight - r.bottom;
  const top = below > h + GAP ? r.bottom + GAP : Math.max(GAP, r.top - h - GAP);
  const left = Math.min(
    Math.max(GAP, r.left),
    window.innerWidth - PANEL_W - GAP,
  );
  pos.value = { top, left };
}

async function toggle() {
  open.value = !open.value;
  if (!open.value) return;
  place(); // rough placement first so the panel never flashes at 0,0
  await nextTick();
  place(); // then again, now that its real height is known
}

function close() {
  open.value = false;
}

useClickOutside(root, close, panel);

// A fixed panel does not travel with the page, so rather than recompute on
// every scroll frame, close it — the same thing a native menu does.
window.addEventListener("scroll", close, true);
window.addEventListener("resize", close);
onBeforeUnmount(() => {
  window.removeEventListener("scroll", close, true);
  window.removeEventListener("resize", close);
});

function pick(key: SkinKey) {
  ui.setSkin(key);
}
</script>

<template>
  <div ref="root" class="relative no-print">
    <button
      class="p-2 rounded-full hover:bg-slate-100 text-slate-500 hover:text-ink transition-colors"
      title="ظاهر سایت"
      aria-label="ظاهر سایت"
      :aria-expanded="open"
      @click="toggle"
    >
      <!-- Painter's palette -->
      <svg
        class="w-5 h-5" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
      >
        <path d="M12 3a9 9 0 0 0 0 18h1.5a2 2 0 0 0 1.5-3.3 2 2 0 0 1 1.5-3.2H19a3 3 0 0 0 3-3A9 9 0 0 0 12 3z" />
        <circle cx="7.5" cy="11.5" r="1.1" fill="currentColor" stroke="none" />
        <circle cx="10.5" cy="7.5" r="1.1" fill="currentColor" stroke="none" />
        <circle cx="15.5" cy="8.5" r="1.1" fill="currentColor" stroke="none" />
      </svg>
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        ref="panel"
        class="fixed w-[19rem] bg-surface rounded-2xl shadow-pop border border-slate-100 p-3 z-[200] animate-pop no-print"
        :style="{ top: pos.top + 'px', left: pos.left + 'px' }"
        dir="rtl"
        role="dialog"
        aria-label="ظاهر سایت"
      >
        <p class="text-sm font-semibold text-ink px-1 mb-2">ظاهر سایت</p>

        <!-- Mode ----------------------------------------------------- -->
        <div class="flex bg-slate-100 rounded-full p-1 mb-3" role="group" aria-label="حالت روشن یا شب">
          <button
            class="flex-1 flex items-center justify-center gap-1.5 text-xs font-medium rounded-full py-1.5 transition-colors"
            :class="!ui.dark ? 'bg-surface text-ink shadow-soft' : 'text-slate-500 hover:text-ink'"
            :aria-pressed="!ui.dark"
            aria-label="حالت روشن"
            @click="ui.setDark(false)"
          >
            <svg
              class="w-4 h-4" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
            >
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
            </svg>
            روشن
          </button>
          <button
            class="flex-1 flex items-center justify-center gap-1.5 text-xs font-medium rounded-full py-1.5 transition-colors"
            :class="ui.dark ? 'bg-surface text-ink shadow-soft' : 'text-slate-500 hover:text-ink'"
            :aria-pressed="ui.dark"
            aria-label="حالت شب"
            @click="ui.setDark(true)"
          >
            <svg
              class="w-4 h-4" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
            >
              <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
            </svg>
            شب
          </button>
        </div>

        <!-- Skins ---------------------------------------------------- -->
        <div class="space-y-1.5">
          <button
            v-for="s in SKINS"
            :key="s.key"
            class="w-full flex items-center gap-3 p-2 rounded-2xl border-2 text-right transition"
            :class="ui.skin === s.key
              ? 'border-accent-500 bg-accent-50/60'
              : 'border-transparent hover:bg-slate-100'"
            :aria-pressed="ui.skin === s.key"
            :aria-label="`تم ${s.label}`"
            @click="pick(s.key)"
          >
            <!-- Self-preview: page, floating card, accent dot -->
            <span
              class="relative w-16 h-11 shrink-0 rounded-xl overflow-hidden border border-slate-200"
              :style="{
                background: ui.dark ? s.preview.canvasDark : s.preview.canvas,
                backgroundImage: s.preview.glass
                  ? 'radial-gradient(120% 90% at 90% 0%, ' + s.preview.accent + '66, transparent 60%), radial-gradient(110% 80% at 0% 100%, #38bdf866, transparent 60%)'
                  : s.preview.aurora
                    ? 'radial-gradient(90% 80% at 10% 5%, ' + s.preview.accent + '80, transparent 60%), radial-gradient(80% 70% at 95% 100%, #f472b680, transparent 60%), radial-gradient(80% 70% at 85% 0%, #2dd4bf66, transparent 60%)'
                    : 'none',
              }"
            >
              <span
                class="absolute inset-x-2 bottom-1.5 top-3 border"
                :style="{
                  background: ui.dark ? s.preview.surfaceDark : s.preview.surface,
                  borderRadius: s.preview.radius,
                  backdropFilter: s.preview.glass ? 'blur(4px)' : 'none',
                  borderColor: s.preview.glass
                    ? 'rgba(255,255,255,0.45)'
                    : (ui.dark ? 'rgba(255,255,255,0.10)' : 'rgba(20,20,25,0.08)'),
                  boxShadow: s.preview.aurora
                    ? '0 3px 10px -3px ' + s.preview.accent
                    : s.preview.glass || ui.dark
                      ? 'none'
                      : '0 2px 6px -2px rgba(20,20,25,0.28)',
                }"
              ></span>
              <span
                class="absolute top-1.5 right-2 w-2 h-2 rounded-full"
                :style="{ background: s.preview.accent }"
              ></span>
            </span>

            <span class="min-w-0 flex-1">
              <span class="flex items-center gap-1.5">
                <span class="text-sm font-semibold text-ink">{{ s.label }}</span>
                <span
                  v-if="ui.skin === s.key"
                  class="text-[10px] bg-accent-500 text-white rounded-full px-1.5 py-0.5"
                >فعال</span>
              </span>
              <span class="block text-[11px] text-slate-400 leading-snug mt-0.5">{{ s.hint }}</span>
            </span>
          </button>
        </div>
      </div>
    </Teleport>
  </div>
</template>
