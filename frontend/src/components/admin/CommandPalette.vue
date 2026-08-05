<script setup lang="ts">
/** Ctrl/⌘+K jump-to-section, plus the shortcut cheat-sheet. */
import { computed, nextTick, ref, watch } from "vue";
import NavIcon from "@/components/NavIcon.vue";
import type { AdminNavItem } from "@/types/admin";

const props = defineProps<{ open: boolean; items: AdminNavItem[] }>();
const emit = defineEmits<{
  (e: "update:open", value: boolean): void;
  (e: "go", name: string): void;
}>();

const query = ref("");
const cursor = ref(0);
const input = ref<HTMLInputElement | null>(null);

const matches = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return props.items;
  return props.items.filter((i) => i.label.toLowerCase().includes(q));
});

watch(() => props.open, async (open) => {
  if (!open) return;
  query.value = "";
  cursor.value = 0;
  await nextTick();
  input.value?.focus();
});
watch(matches, () => (cursor.value = 0));

function close() { emit("update:open", false); }
function choose(item: AdminNavItem) { emit("go", item.name); close(); }

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") return close();
  if (event.key === "ArrowDown") {
    event.preventDefault();
    cursor.value = (cursor.value + 1) % Math.max(matches.value.length, 1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    cursor.value = (cursor.value - 1 + matches.value.length) % Math.max(matches.value.length, 1);
  } else if (event.key === "Enter") {
    const item = matches.value[cursor.value];
    if (item) choose(item);
  }
}

const SHORTCUTS = [
  { keys: "Ctrl K", text: "جستجوی سریع بخش‌ها" },
  { keys: "g سپس ۱…۹", text: "پرش به بخش شماره n" },
  { keys: "g سپس b", text: "جمع/باز کردن منو" },
  { keys: "Esc", text: "بستن پنجره‌ها" },
];
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-[70] flex items-start justify-center pt-[12vh] px-4"
      dir="rtl"
      @click.self="close"
    >
      <div class="absolute inset-0 bg-black/40"></div>
      <div class="relative w-full max-w-lg bg-surface rounded-2xl shadow-pop overflow-hidden animate-pop">
        <div class="flex items-center gap-2 px-4 py-3 border-b border-slate-100">
          <NavIcon name="search" :size="18" class="text-slate-400" />
          <input
            ref="input"
            v-model="query"
            placeholder="نام بخش را بنویسید…"
            class="flex-1 bg-transparent outline-none text-sm text-ink"
            @keydown="onKeydown"
          />
          <kbd class="text-[10px] text-slate-400 border border-slate-200 rounded px-1">Esc</kbd>
        </div>

        <ul v-if="matches.length" class="max-h-72 overflow-y-auto py-1">
          <li v-for="(item, i) in matches" :key="item.name">
            <button
              class="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-right transition"
              :class="i === cursor ? 'bg-brand-50 text-brand-700' : 'text-ink hover:bg-slate-50'"
              @click="choose(item)"
              @mouseenter="cursor = i"
            >
              <NavIcon :name="item.icon" :size="17" class="text-slate-400 shrink-0" />
              <span class="flex-1">{{ item.label }}</span>
              <kbd
                v-if="i < 9"
                class="text-[10px] text-slate-400 border border-slate-200 rounded px-1"
              >g {{ i + 1 }}</kbd>
            </button>
          </li>
        </ul>
        <p v-else class="px-4 py-8 text-center text-sm text-slate-400">بخشی با این نام نبود.</p>

        <div class="border-t border-slate-100 px-4 py-2.5 bg-slate-50/60">
          <p class="text-[10px] text-slate-400 mb-1.5">میان‌برها</p>
          <div class="flex flex-wrap gap-x-4 gap-y-1">
            <span v-for="s in SHORTCUTS" :key="s.keys" class="text-[11px] text-slate-500">
              <kbd class="bg-surface border border-slate-200 rounded px-1 ltr-nums">{{ s.keys }}</kbd>
              {{ s.text }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
