<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { notificationsApi } from "@/api/platform";
import { confirm, toast } from "@/composables/useUi";
import type { AppNotification } from "@/types";

const open = ref(false);
const unread = ref(0);
const items = ref<AppNotification[]>([]);
let timer: number | undefined;

const VERB_ICON: Record<string, string> = {
  submitted: "📥",
  approved: "✅",
  rejected: "❌",
  revision: "✏️",
};

async function refreshCount() {
  try {
    unread.value = await notificationsApi.unreadCount();
  } catch {
    /* token may be refreshing; next poll will catch up */
  }
}

async function toggle() {
  open.value = !open.value;
  if (open.value) {
    items.value = await notificationsApi.list();
  }
}

async function markAll() {
  await notificationsApi.markAllRead();
  unread.value = 0;
  items.value = items.value.map((n) => ({ ...n, is_read: true }));
}

const hasRead = computed(() => items.value.some((n) => n.is_read));

/** Remove one notification. Optimistic — the list is cheap to re-fetch. */
async function remove(n: AppNotification) {
  items.value = items.value.filter((i) => i.id !== n.id);
  if (!n.is_read) unread.value = Math.max(0, unread.value - 1);
  try {
    await notificationsApi.remove(n.id);
  } catch {
    toast.error("حذف نشد.");
    items.value = await notificationsApi.list();
    await refreshCount();
  }
}

async function clearRead() {
  const n = await notificationsApi.clearRead();
  items.value = items.value.filter((i) => !i.is_read);
  toast.success(n ? `${n} اعلان خوانده‌شده پاک شد.` : "اعلان خوانده‌شده‌ای نبود.");
}

async function clearAll() {
  const ok = await confirm({
    title: "پاک‌کردن همه اعلان‌ها",
    message: "همه‌ی اعلان‌ها — از جمله خوانده‌نشده‌ها — حذف می‌شوند. مطمئنید؟",
    danger: true,
  });
  if (!ok) return;
  await notificationsApi.clearAll();
  items.value = [];
  unread.value = 0;
  toast.success("همه اعلان‌ها پاک شد.");
}

function since(iso: string): string {
  const mins = Math.max(1, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins} دقیقه پیش`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} ساعت پیش`;
  return `${Math.round(hours / 24)} روز پیش`;
}

onMounted(() => {
  refreshCount();
  timer = window.setInterval(refreshCount, 30_000);
});
onBeforeUnmount(() => window.clearInterval(timer));
</script>

<template>
  <div class="relative">
    <button
      class="relative p-2 rounded-full hover:bg-slate-100 text-slate-600 transition-colors"
      title="اعلان‌ها"
      @click="toggle"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
        stroke-linejoin="round" class="w-5 h-5"
      >
        <path d="M18 8A6 6 0 1 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.73 21a2 2 0 0 1-3.46 0" />
      </svg>
      <span
        v-if="unread > 0"
        class="absolute -top-0.5 -left-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[11px] leading-[18px] text-center font-bold ltr-nums"
      >{{ unread > 99 ? "۹۹+" : unread }}</span>
    </button>

    <div
      v-if="open"
      class="absolute left-0 mt-2 w-96 max-h-[28rem] overflow-auto bg-surface rounded-card shadow-pop z-50 animate-pop"
    >
      <div class="flex items-center justify-between gap-2 px-4 py-2 border-b border-slate-100">
        <span class="text-sm font-semibold text-ink">اعلان‌ها</span>
        <div class="flex items-center gap-2 text-xs">
          <button v-if="unread" class="text-brand-600 hover:underline" @click="markAll">
            همه خوانده شد
          </button>
          <button v-if="hasRead" class="text-slate-500 hover:underline" @click="clearRead">
            پاک‌کردن خوانده‌شده‌ها
          </button>
          <button v-if="items.length" class="text-red-500 hover:underline" @click="clearAll">
            پاک‌کردن همه
          </button>
        </div>
      </div>
      <div v-if="!items.length" class="p-6 text-center text-sm text-slate-400">
        اعلانی ندارید.
      </div>
      <div
        v-for="n in items"
        :key="n.id"
        class="group flex gap-2 px-4 py-3 border-b border-slate-50 text-sm"
        :class="n.is_read ? 'bg-surface' : 'bg-brand-50/50'"
      >
        <span>{{ VERB_ICON[n.verb] ?? "🔹" }}</span>
        <div class="flex-1 min-w-0">
          <p class="text-slate-700 leading-6">{{ n.message }}</p>
          <p class="text-xs text-slate-400 mt-1">
            {{ n.actor_name }} · {{ since(n.created_at) }}
          </p>
        </div>
        <button
          class="shrink-0 self-start w-6 h-6 rounded-full text-slate-300 hover:text-red-500 hover:bg-red-50 transition-colors leading-none"
          title="حذف این اعلان"
          @click="remove(n)"
        >✕</button>
      </div>
    </div>
  </div>
</template>
