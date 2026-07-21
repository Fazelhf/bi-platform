<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, RouterView, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const router = useRouter();

interface NavItem {
  name: string;
  label: string;
}

// The CEO sees all four dashboards; a department manager sees their own
// dashboard plus their data-entry page.
const navItems = computed<NavItem[]>(() => {
  if (auth.isExecutive) {
    return [
      { name: "overview", label: "نمای کلی" },
      { name: "sales-dashboard", label: "فروش همکار" },
      { name: "sales-org-dashboard", label: "فروش کلی" },
      { name: "production-dashboard", label: "تولید" },
    ];
  }
  switch (auth.department) {
    case "production":
      return [
        { name: "production-entry", label: "ورود اطلاعات تولید" },
        { name: "production-dashboard", label: "داشبورد تولید" },
      ];
    case "sales_org":
      return [
        { name: "sales-org-entry", label: "ورود فروش سازمانی" },
        { name: "sales-org-dashboard", label: "داشبورد فروش کلی" },
      ];
    case "sales_team":
      return [
        { name: "sales-entry", label: "ورود تیم فروش" },
        { name: "sales-dashboard", label: "داشبورد فروش همکار" },
      ];
    default:
      return [{ name: "overview", label: "نمای کلی" }];
  }
});

const roleLabel = computed(() => (auth.isExecutive ? "مدیرعامل" : "مدیر بخش"));

function logout() {
  auth.logout();
  router.push({ name: "login" });
}
</script>

<template>
  <div class="min-h-screen flex flex-col">
    <header class="bg-white border-b border-slate-200 shadow-sm">
      <div class="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
        <div class="flex items-center gap-6">
          <span class="font-bold text-brand-600 text-lg">داشبورد هوش تجاری</span>
          <nav class="flex items-center gap-1">
            <RouterLink
              v-for="item in navItems"
              :key="item.name"
              :to="{ name: item.name }"
              class="px-3 py-1.5 rounded-md text-sm hover:bg-slate-100"
              active-class="bg-brand-50 text-brand-700 font-medium"
            >{{ item.label }}</RouterLink>
          </nav>
        </div>
        <div class="flex items-center gap-3 text-sm text-slate-600">
          <span class="text-xs bg-slate-100 rounded-full px-2 py-0.5">{{ roleLabel }}</span>
          <span>{{ auth.username }}</span>
          <button class="text-red-600 hover:underline" @click="logout">خروج</button>
        </div>
      </div>
    </header>

    <main class="flex-1 max-w-7xl w-full mx-auto px-4 py-6">
      <RouterView />
    </main>
  </div>
</template>
