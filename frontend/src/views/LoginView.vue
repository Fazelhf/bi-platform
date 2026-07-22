<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { homeRouteFor } from "@/router";

const auth = useAuthStore();
const router = useRouter();

const username = ref("ceo");
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
  <div class="min-h-screen flex items-center justify-center bg-slate-100">
    <form
      class="bg-white p-8 rounded-2xl shadow-lg w-full max-w-sm space-y-5"
      @submit.prevent="submit"
    >
      <h1 class="text-xl font-bold text-center text-brand-600">شرکت کاغذ حساس نمابر مهر</h1>
      <p class="text-center text-sm text-slate-500 -mt-2">ورود به سامانه</p>

      <div>
        <label class="block text-sm mb-1 text-slate-600">نام کاربری</label>
        <input
          v-model="username"
          class="w-full border border-slate-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-brand-500 outline-none"
          autocomplete="username"
        />
      </div>
      <div>
        <label class="block text-sm mb-1 text-slate-600">رمز عبور</label>
        <input
          v-model="password"
          type="password"
          class="w-full border border-slate-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-brand-500 outline-none"
          autocomplete="current-password"
        />
      </div>

      <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>

      <button
        type="submit"
        :disabled="loading"
        class="w-full bg-brand-600 text-white rounded-lg py-2.5 font-medium hover:bg-brand-700 disabled:opacity-60"
      >
        {{ loading ? "در حال ورود…" : "ورود" }}
      </button>
    </form>
  </div>
</template>
