<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { homeRouteFor } from "@/router";

const auth = useAuthStore();
const router = useRouter();

const username = ref("");
const password = ref("");
const error = ref("");
const loading = ref(false);

async function submit() {
  error.value = "";
  loading.value = true;
  try {
    await auth.login(username.value, password.value);
    router.push({ name: homeRouteFor(auth.department) });
  } catch {
    error.value = "نام کاربری یا رمز عبور نادرست است.";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-canvas px-4 relative overflow-hidden">
    <!-- soft brand glow accents -->
    <div class="pointer-events-none absolute -top-24 -right-24 w-80 h-80 rounded-full bg-brand-500/10 blur-3xl"></div>
    <div class="pointer-events-none absolute -bottom-24 -left-24 w-80 h-80 rounded-full bg-accent-500/10 blur-3xl"></div>

    <form
      class="relative bg-white p-8 rounded-card shadow-pop w-full max-w-sm space-y-5 animate-pop"
      @submit.prevent="submit"
    >
      <!-- Brand mark -->
      <div class="flex flex-col items-center gap-3">
        <div
          class="w-14 h-14 rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center shadow-soft"
        >
          <span class="text-white text-2xl font-black tracking-tight">N</span>
        </div>
        <div class="text-center">
          <h1 class="text-lg font-bold text-ink">شرکت کاغذ حساس نمابر مهر</h1>
          <p class="text-sm text-slate-400 mt-0.5">ورود به سامانه هوش تجاری</p>
        </div>
      </div>

      <div>
        <label class="block text-sm mb-1 text-slate-600">نام کاربری</label>
        <input
          v-model="username"
          placeholder="نام کاربری خود را وارد کنید"
          class="w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500 outline-none transition"
          autocomplete="username"
        />
      </div>
      <div>
        <label class="block text-sm mb-1 text-slate-600">رمز عبور</label>
        <input
          v-model="password"
          type="password"
          placeholder="••••••••"
          class="w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500 outline-none transition"
          autocomplete="current-password"
        />
      </div>

      <p v-if="error" class="text-red-600 text-sm bg-red-50 rounded-xl px-3 py-2">{{ error }}</p>

      <button
        type="submit"
        :disabled="loading"
        class="w-full bg-brand-600 text-white rounded-xl py-2.5 font-medium hover:bg-brand-700 active:scale-[0.99] disabled:opacity-60 transition"
      >
        {{ loading ? "در حال ورود…" : "ورود" }}
      </button>
    </form>
  </div>
</template>
