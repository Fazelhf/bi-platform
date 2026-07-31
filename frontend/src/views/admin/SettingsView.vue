<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import AdminFormulasView from "@/views/admin/AdminFormulasView.vue";
import AdminAppearanceView from "@/views/admin/AdminAppearanceView.vue";
import AdminPeriodsView from "@/views/admin/AdminPeriodsView.vue";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

// User management, base data and the audit trail moved to the Admin Panel
// (/admin) — they are system administration, not the CEO's business controls.
// What stays here is what the CEO genuinely owns: the reporting calendar,
// the KPI formulas behind the numbers, and how the platform looks.
const tabs = [
  { key: "appearance", label: "طرح گرافیکی", comp: AdminAppearanceView },
  { key: "periods", label: "دوره‌ها", comp: AdminPeriodsView },
  { key: "formulas", label: "فرمول‌ها", comp: AdminFormulasView },
];

const active = computed(() => (route.query.tab as string) || "appearance");
const activeComp = computed(() => tabs.find((t) => t.key === active.value)?.comp ?? tabs[0].comp);

function select(key: string) {
  router.replace({ name: "settings", query: { tab: key } });
}
</script>

<template>
  <div class="space-y-4">
    <h1 class="text-xl font-bold text-ink">تنظیمات سایت</h1>

    <!-- Sub-tabs. Scrolls horizontally on narrow screens instead of wrapping. -->
    <div class="flex gap-1 bg-surface rounded-2xl shadow-soft p-1.5 max-w-full overflow-x-auto md:w-fit">
      <button
        v-for="t in tabs"
        :key="t.key"
        class="px-4 py-2 rounded-xl text-sm transition whitespace-nowrap shrink-0"
        :class="active === t.key ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
        @click="select(t.key)"
      >{{ t.label }}</button>
    </div>

    <component :is="activeComp" />

    <p v-if="auth.isAdminPanelUser" class="text-xs text-slate-400">
      مدیریت کاربران، داده‌های پایه و تاریخچه رخدادها به
      <RouterLink :to="{ name: 'admin-dashboard' }" class="text-brand-600 hover:underline">پنل مدیریت</RouterLink>
      منتقل شده است.
    </p>
  </div>
</template>
