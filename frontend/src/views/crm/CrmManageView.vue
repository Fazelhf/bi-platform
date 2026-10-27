<script setup lang="ts">
import { computed, defineAsyncComponent } from "vue";
import { useRoute, useRouter } from "vue-router";
import NavIcon from "@/components/NavIcon.vue";

/**
 * مدیریت فروش — the sales manager's own maintenance: customer groups and who
 * is responsible for which province. Separate from تنظیمات CRM, which is the
 * system admin's (imports, data checks, resets).
 */
const route = useRoute();
const router = useRouter();

const SECTIONS = [
  { key: "groups", label: "گروه‌های مشتری", icon: "team", view: defineAsyncComponent(() => import("./CustomerGroupsView.vue")) },
] as const;

const current = computed(() => SECTIONS.find((s) => s.key === route.query.section) ?? SECTIONS[0]);
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-1.5 flex gap-1 overflow-x-auto">
      <button
        v-for="s in SECTIONS" :key="s.key"
        class="flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm whitespace-nowrap transition"
        :class="current.key === s.key ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100 hover:text-ink'"
        @click="router.replace({ query: { section: s.key } })"
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
