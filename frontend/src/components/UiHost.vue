<script setup lang="ts">
import { useUi } from "@/composables/useUi";
const { state } = useUi();

const ICON = { success: "✓", error: "✕", info: "i" } as const;
const RING = {
  success: "border-r-4 border-emerald-500",
  error: "border-r-4 border-rose-500",
  info: "border-r-4 border-brand-500",
} as const;

function ok() {
  const d = state.dialog;
  d.open = false;
  d.resolve?.(d.mode === "prompt" ? d.value.trim() : true);
}
function cancel() {
  const d = state.dialog;
  d.open = false;
  d.resolve?.(d.mode === "prompt" ? null : false);
}
</script>

<template>
  <!-- Toasts -->
  <div class="fixed bottom-5 left-1/2 -translate-x-1/2 z-[100] flex flex-col items-center gap-2 pointer-events-none" dir="rtl">
    <transition-group name="toast">
      <div
        v-for="t in state.toasts"
        :key="t.id"
        class="pointer-events-auto bg-surface shadow-pop rounded-2xl px-4 py-3 flex items-center gap-3 min-w-[240px] max-w-[92vw]"
        :class="RING[t.type]"
      >
        <span
          class="w-6 h-6 rounded-full flex items-center justify-center text-white text-xs font-bold shrink-0"
          :class="t.type === 'success' ? 'bg-emerald-500' : t.type === 'error' ? 'bg-rose-500' : 'bg-brand-500'"
        >{{ ICON[t.type] }}</span>
        <span class="text-sm text-ink">{{ t.text }}</span>
      </div>
    </transition-group>
  </div>

  <!-- Confirm / prompt dialog -->
  <transition name="fade">
    <div v-if="state.dialog.open" class="fixed inset-0 z-[110] flex items-center justify-center p-4" dir="rtl">
      <div class="absolute inset-0 bg-black/40" @click="cancel"></div>
      <div class="relative bg-surface rounded-3xl shadow-pop w-full max-w-sm p-6 animate-pop">
        <h3 v-if="state.dialog.title" class="font-bold text-ink text-lg mb-2">{{ state.dialog.title }}</h3>
        <p v-if="state.dialog.message" class="text-sm text-slate-500 mb-4 leading-6">{{ state.dialog.message }}</p>
        <input
          v-if="state.dialog.mode === 'prompt'"
          v-model="state.dialog.value"
          :placeholder="state.dialog.placeholder"
          class="w-full bg-slate-50 border border-slate-200 focus:border-brand-500 rounded-xl px-3 py-2.5 text-sm outline-none mb-4"
          @keyup.enter="ok"
        />
        <div class="flex justify-end gap-2">
          <button class="px-4 py-2 rounded-xl text-sm text-slate-500 hover:bg-slate-100" @click="cancel">انصراف</button>
          <button
            class="px-5 py-2 rounded-xl text-sm font-medium text-white"
            :class="state.dialog.danger ? 'bg-rose-500 hover:bg-rose-600' : 'bg-brand-600 hover:bg-brand-700'"
            @click="ok"
          >{{ state.dialog.danger ? 'حذف' : 'تأیید' }}</button>
        </div>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.toast-enter-active, .toast-leave-active { transition: all .25s ease; }
.toast-enter-from { opacity: 0; transform: translateY(12px); }
.toast-leave-to { opacity: 0; transform: translateY(12px); }
.fade-enter-active, .fade-leave-active { transition: opacity .2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
