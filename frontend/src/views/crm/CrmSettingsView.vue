<script setup lang="ts">
import { computed, defineAsyncComponent } from "vue";
import { useRoute, useRouter } from "vue-router";
import NavIcon from "@/components/NavIcon.vue";

/**
 * تنظیمات CRM — everything about *what is in* CRM, in one place, for the
 * system admin: where the data comes from (آرپا، دیدار، تیم‌یار), whether it is
 * right (کنترل داده، بازبینی تطبیق) and starting over (پاک‌سازی).
 *
 * The section is in the URL (`?section=`) so a link from کنترل داده lands on
 * the right tab — and the آرپا page keeps its own `?tab=` inside it.
 */
const route = useRoute();
const router = useRouter();

const SECTIONS = [
  { key: "checks", label: "کنترل داده", icon: "shield", view: defineAsyncComponent(() => import("./DataChecksView.vue")) },
  { key: "arpa", label: "ورود از آرپا", icon: "upload", view: defineAsyncComponent(() => import("./ArpaImportView.vue")) },
  { key: "didar", label: "ورود از دیدار", icon: "download", view: defineAsyncComponent(() => import("./DidarImportView.vue")) },
  { key: "customers", label: "ورود مشتریان", icon: "team", view: defineAsyncComponent(() => import("./TeamyarImportView.vue")) },
  { key: "match", label: "بازبینی تطبیق", icon: "check", view: defineAsyncComponent(() => import("./MatchReviewView.vue")) },
  { key: "reset", label: "پاک‌سازی داده", icon: "trash", view: defineAsyncComponent(() => import("./DataResetView.vue")) },
] as const;

const current = computed(
  () => SECTIONS.find((s) => s.key === route.query.section) ?? SECTIONS[0],
);

function go(key: string) {
  router.replace({ query: { section: key } });
}
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-1.5 flex gap-1 overflow-x-auto">
      <button
        v-for="s in SECTIONS" :key="s.key"
        class="flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm whitespace-nowrap transition"
        :class="current.key === s.key ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100 hover:text-ink'"
        @click="go(s.key)"
      >
        <NavIcon :name="s.icon" :size="16" />
        {{ s.label }}
      </button>
    </div>
    <KeepAlive>
      <component :is="current.view" :key="current.key" />
    </KeepAlive>
  </div>
</template>
