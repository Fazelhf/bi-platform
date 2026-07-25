<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import AdminUsersView from "@/views/admin/AdminUsersView.vue";
import AdminDimensionsView from "@/views/admin/AdminDimensionsView.vue";
import AdminFormulasView from "@/views/admin/AdminFormulasView.vue";
import AdminAuditView from "@/views/admin/AdminAuditView.vue";
import AdminAppearanceView from "@/views/admin/AdminAppearanceView.vue";

const route = useRoute();
const router = useRouter();

const tabs = [
  { key: "users", label: "کاربران", comp: AdminUsersView },
  { key: "dimensions", label: "داده‌های پایه", comp: AdminDimensionsView },
  { key: "formulas", label: "فرمول‌ها", comp: AdminFormulasView },
  { key: "appearance", label: "طرح گرافیکی", comp: AdminAppearanceView },
  { key: "audit", label: "تاریخچه", comp: AdminAuditView },
];

const active = computed(() => (route.query.tab as string) || "users");
const activeComp = computed(() => tabs.find((t) => t.key === active.value)?.comp ?? tabs[0].comp);

function select(key: string) {
  router.replace({ name: "settings", query: { tab: key } });
}
</script>

<template>
  <div class="space-y-4">
    <h1 class="text-xl font-bold text-ink">تنظیمات سایت</h1>

    <!-- Sub-tabs (all the former admin items live here now).
         Scrolls horizontally on narrow screens instead of wrapping. -->
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
  </div>
</template>
