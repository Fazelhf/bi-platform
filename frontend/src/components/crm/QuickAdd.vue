<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useCrmStore } from "@/stores/crm";
import { useClickOutside } from "@/composables/useClickOutside";
import NavIcon from "@/components/NavIcon.vue";
import CustomerForm from "./CustomerForm.vue";
import DealForm from "./DealForm.vue";
import ActivityForm from "./ActivityForm.vue";
import TaskForm from "./TaskForm.vue";

/**
 * «ثبت جدید» — one place to enter anything, from anywhere in the CRM.
 *
 * Entry used to be a property of the page you happened to be on: to log a
 * call you first navigated to پیگیری‌ها, to add a lead you first navigated to
 * مشتری‌ها. That is backwards for the person this section exists for. A rep
 * finishing a phone call has something to record *now*, and making them
 * first find the page that owns it is how a call ends up recorded nowhere.
 *
 * The four kinds are listed in the order a day actually produces them, and
 * each carries its shortcut so the menu teaches its own way out of itself.
 * Alt is used rather than Ctrl because every Ctrl+digit is already a browser
 * tab switch.
 */
const crm = useCrmStore();

const open = ref(false);
const root = ref<HTMLElement | null>(null);
const modal = ref<"activity" | "deal" | "customer" | "task" | null>(null);

useClickOutside(root, () => (open.value = false));

const ITEMS = [
  { key: "activity", label: "ثبت فعالیت", hint: "تماس، جلسه، اعلام قیمت", icon: "notes", digit: "1" },
  { key: "deal", label: "معامله جدید", hint: "فرصت فروش تازه", icon: "box", digit: "2" },
  { key: "customer", label: "مشتری جدید", hint: "سرنخ یا مشتری تازه", icon: "team", digit: "3" },
  { key: "task", label: "کار / یادآوری", hint: "پیگیری برای بعد", icon: "check", digit: "4" },
] as const;

function pick(key: typeof ITEMS[number]["key"]) {
  open.value = false;
  modal.value = key;
}

function onSaved() {
  modal.value = null;
  // The page underneath is showing data this save may have changed.
  crm.bump();
}

function onKey(e: KeyboardEvent) {
  if (!e.altKey || e.ctrlKey || e.metaKey) return;
  const hit = ITEMS.find((i) => i.digit === e.key);
  if (!hit) return;
  e.preventDefault();
  pick(hit.key);
}

onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <!-- Nothing to offer someone who cannot write. -->
  <div v-if="crm.canEdit" ref="root" class="relative shrink-0">
    <button
      class="flex items-center gap-1.5 bg-panel text-white rounded-xl px-3 py-2 text-sm
             hover:opacity-90 transition-opacity"
      title="ثبت جدید"
      @click="open = !open"
    >
      <NavIcon name="plus" :size="16" />
      <span class="hidden sm:inline">ثبت جدید</span>
    </button>

    <div
      v-if="open"
      class="absolute left-0 mt-2 w-64 bg-surface rounded-2xl shadow-pop
             border border-slate-100 p-1.5 z-50"
    >
      <button
        v-for="item in ITEMS" :key="item.key"
        class="w-full flex items-center gap-3 text-right px-3 py-2.5 rounded-xl
               hover:bg-slate-100 transition-colors"
        @click="pick(item.key)"
      >
        <span class="w-8 h-8 rounded-xl bg-slate-100 text-slate-500 grid place-items-center shrink-0">
          <NavIcon :name="item.icon" :size="16" />
        </span>
        <span class="flex-1 min-w-0">
          <span class="block text-sm text-ink">{{ item.label }}</span>
          <span class="block text-[11px] text-slate-400 truncate">{{ item.hint }}</span>
        </span>
        <kbd class="text-[10px] text-slate-400 bg-slate-100 rounded px-1.5 py-0.5 shrink-0" dir="ltr">
          Alt+{{ item.digit }}
        </kbd>
      </button>
    </div>

    <ActivityForm v-if="modal === 'activity'" @close="modal = null" @saved="onSaved" />
    <DealForm v-if="modal === 'deal'" @close="modal = null" @saved="onSaved" />
    <CustomerForm v-if="modal === 'customer'" @close="modal = null" @saved="onSaved" />
    <TaskForm v-if="modal === 'task'" @close="modal = null" @saved="onSaved" />
  </div>
</template>
