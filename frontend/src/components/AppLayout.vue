<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, RouterView, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import NotificationBell from "@/components/NotificationBell.vue";

const auth = useAuthStore();
const router = useRouter();

interface NavItem {
  name: string;
  label: string;
}

// The CEO sees all four dashboards + inbox + admin; a department manager
// sees their own entry/dashboard + inbox.
const navItems = computed<NavItem[]>(() => {
  if (auth.isExecutive) {
    return [
      { name: "overview", label: "نمای کلی" },
      { name: "sales-dashboard", label: "فروش همکار" },
      { name: "sales-org-dashboard", label: "فروش کلی" },
      { name: "production-dashboard", label: "تولید" },
      { name: "inbox", label: "کارتابل" },
    ];
  }
  switch (auth.department) {
    case "production":
      return [
        { name: "production-entry", label: "ورود اطلاعات تولید" },
        { name: "production-dashboard", label: "داشبورد تولید" },
        { name: "inbox", label: "کارتابل" },
      ];
    case "sales_org":
      return [
        { name: "sales-org-entry", label: "ورود فروش سازمانی" },
        { name: "sales-org-dashboard", label: "داشبورد فروش کلی" },
        { name: "inbox", label: "کارتابل" },
      ];
    case "sales_team":
      return [
        { name: "sales-entry", label: "ورود تیم فروش" },
        { name: "sales-dashboard", label: "داشبورد فروش همکار" },
        { name: "inbox", label: "کارتابل" },
      ];
    default:
      return [{ name: "overview", label: "نمای کلی" }];
  }
});

const adminItems: NavItem[] = [
  { name: "admin-users", label: "کاربران" },
  { name: "admin-dimensions", label: "داده‌های پایه" },
  { name: "admin-formulas", label: "فرمول‌ها" },
  { name: "admin-audit", label: "تاریخچه" },
];

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
        <div class="flex items-center gap-4">
          <span class="font-bold text-brand-600 text-lg whitespace-nowrap">هوش تجاری</span>
          <nav class="flex items-center gap-1">
            <RouterLink
              v-for="item in navItems"
              :key="item.name"
              :to="{ name: item.name }"
              class="px-3 py-1.5 rounded-md text-sm hover:bg-slate-100 whitespace-nowrap"
              active-class="bg-brand-50 text-brand-700 font-medium"
            >{{ item.label }}</RouterLink>

            <template v-if="auth.isExecutive">
              <span class="w-px h-5 bg-slate-200 mx-1"></span>
              <RouterLink
                v-for="item in adminItems"
                :key="item.name"
                :to="{ name: item.name }"
                class="px-3 py-1.5 rounded-md text-sm text-slate-500 hover:bg-slate-100 whitespace-nowrap"
                active-class="bg-slate-100 text-slate-800 font-medium"
              >{{ item.label }}</RouterLink>
            </template>
          </nav>
        </div>
        <div class="flex items-center gap-2 text-sm text-slate-600">
          <NotificationBell />
          <span class="text-xs bg-slate-100 rounded-full px-2 py-0.5 whitespace-nowrap">{{ roleLabel }}</span>
          <span class="whitespace-nowrap">{{ auth.username }}</span>
          <button class="text-red-600 hover:underline" @click="logout">خروج</button>
        </div>
      </div>
    </header>

    <main class="flex-1 max-w-7xl w-full mx-auto px-4 py-6">
      <RouterView />
    </main>
  </div>
</template>
