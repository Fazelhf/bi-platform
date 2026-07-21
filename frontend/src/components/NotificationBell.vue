<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { notificationsApi } from "@/api/platform";
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
      class="relative p-2 rounded-full hover:bg-slate-100 text-slate-600"
      title="اعلان‌ها"
      @click="toggle"
    >
      🔔
      <span
        v-if="unread > 0"
        class="absolute -top-0.5 -left-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[11px] leading-[18px] text-center font-bold"
      >{{ unread > 99 ? "۹۹+" : unread }}</span>
    </button>

    <div
      v-if="open"
      class="absolute left-0 mt-2 w-96 max-h-[28rem] overflow-auto bg-white border border-slate-200 rounded-xl shadow-xl z-50"
    >
      <div class="flex items-center justify-between px-4 py-2 border-b border-slate-100">
        <span class="text-sm font-semibold text-slate-700">اعلان‌ها</span>
        <button class="text-xs text-brand-600 hover:underline" @click="markAll">
          همه خوانده شد
        </button>
      </div>
      <div v-if="!items.length" class="p-6 text-center text-sm text-slate-400">
        اعلانی ندارید.
      </div>
      <div
        v-for="n in items"
        :key="n.id"
        class="px-4 py-3 border-b border-slate-50 text-sm"
        :class="n.is_read ? 'bg-white' : 'bg-brand-50/50'"
      >
        <div class="flex gap-2">
          <span>{{ VERB_ICON[n.verb] ?? "🔹" }}</span>
          <div class="flex-1">
            <p class="text-slate-700 leading-6">{{ n.message }}</p>
            <p class="text-xs text-slate-400 mt-1">
              {{ n.actor_name }} · {{ since(n.created_at) }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
