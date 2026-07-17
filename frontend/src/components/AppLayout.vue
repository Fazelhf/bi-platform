<script setup lang="ts">
import { RouterLink, RouterView, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const router = useRouter();

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
              :to="{ name: 'dashboard' }"
              class="px-3 py-1.5 rounded-md text-sm hover:bg-slate-100"
              active-class="bg-brand-50 text-brand-700 font-medium"
            >داشبورد مدیریتی</RouterLink>
            <RouterLink
              :to="{ name: 'entry' }"
              class="px-3 py-1.5 rounded-md text-sm hover:bg-slate-100"
              active-class="bg-brand-50 text-brand-700 font-medium"
            >ورود اطلاعات</RouterLink>
          </nav>
        </div>
        <div class="flex items-center gap-3 text-sm text-slate-600">
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
