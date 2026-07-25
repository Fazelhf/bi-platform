<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";
import { homeRouteFor } from "@/router";

const auth = useAuthStore();
const ui = useUiStore();
const router = useRouter();

const username = ref("");
const password = ref("");
const showPassword = ref(false);
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

const YEAR = new Date().toLocaleDateString("fa-IR", { year: "numeric" });
</script>

<template>
  <div class="min-h-screen grid lg:grid-cols-[1.05fr_1fr] bg-canvas">
    <!-- ================= Brand panel (desktop only) ================= -->
    <!-- First in DOM, so in RTL it sits on the right. -->
    <aside class="relative hidden lg:flex flex-col justify-between overflow-hidden bg-panel p-12 text-white">
      <!-- soft depth: two blurred colour pools + a faint grid -->
      <div class="pointer-events-none absolute -top-32 -right-24 w-96 h-96 rounded-full bg-brand-500/25 blur-3xl"></div>
      <div class="pointer-events-none absolute -bottom-40 -left-24 w-[28rem] h-[28rem] rounded-full bg-accent-500/15 blur-3xl"></div>
      <div
        class="pointer-events-none absolute inset-0 opacity-[0.04]"
        style="background-image:linear-gradient(currentColor 1px,transparent 1px),linear-gradient(90deg,currentColor 1px,transparent 1px);background-size:44px 44px"
      ></div>

      <div class="relative flex items-center gap-3">
        <img src="/apple-touch-icon.png" alt="" class="w-11 h-11 rounded-xl shadow-soft" />
        <span class="font-bold text-lg">کاغذ حساس نمابر مهر</span>
      </div>

      <div class="relative">
        <h2 class="text-3xl font-extrabold leading-[1.7]">
          سامانه هوش تجاری
        </h2>
        <p class="text-white/60 mt-3 leading-8 max-w-md">
          فروش، تولید و شاخص‌های کلیدی سازمان — یک‌جا، به‌روز و قابل اتکا برای تصمیم‌گیری.
        </p>

        <div class="flex flex-wrap gap-2 mt-8">
          <span
            v-for="t in ['فروش همکار', 'فروش بانکی', 'فروش B2B', 'تولید']"
            :key="t"
            class="text-xs bg-white/10 rounded-full px-3 py-1.5"
          >{{ t }}</span>
        </div>
      </div>

      <p class="relative text-xs text-white/35 ltr-nums">© {{ YEAR }} — نمابر مهر</p>
    </aside>

    <!-- ===================== Sign-in form ===================== -->
    <main class="flex items-center justify-center p-6 sm:p-10">
      <form class="w-full max-w-sm space-y-6 animate-pop" @submit.prevent="submit">
        <!-- Compact brand mark, mobile only (the panel covers desktop) -->
        <div class="flex flex-col items-center gap-3 lg:hidden">
          <img src="/apple-touch-icon.png" alt="" class="w-16 h-16 rounded-2xl shadow-soft" />
          <h1 class="text-lg font-bold text-ink text-center">شرکت کاغذ حساس نمابر مهر</h1>
        </div>

        <div class="hidden lg:block">
          <h1 class="text-2xl font-bold text-ink">ورود به سامانه</h1>
          <p class="text-sm text-slate-400 mt-1.5">
            برای ادامه، نام کاربری و رمز عبور خود را وارد کنید.
          </p>
        </div>

        <div class="space-y-4">
          <div>
            <label for="username" class="block text-sm mb-1.5 text-slate-600">نام کاربری</label>
            <input
              id="username"
              v-model="username"
              placeholder="نام کاربری خود را وارد کنید"
              autocomplete="username"
              class="w-full bg-surface border border-slate-200 rounded-xl px-3.5 py-3 text-sm text-ink placeholder:text-slate-400 focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500 outline-none transition"
            />
          </div>

          <div>
            <label for="password" class="block text-sm mb-1.5 text-slate-600">رمز عبور</label>
            <div class="relative">
              <input
                id="password"
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                placeholder="••••••••"
                autocomplete="current-password"
                class="w-full bg-surface border border-slate-200 rounded-xl px-3.5 py-3 pl-11 text-sm text-ink placeholder:text-slate-400 focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500 outline-none transition"
              />
              <button
                type="button"
                class="absolute inset-y-0 left-0 px-3 flex items-center text-slate-400 hover:text-ink transition-colors"
                :title="showPassword ? 'پنهان‌کردن رمز' : 'نمایش رمز'"
                :aria-label="showPassword ? 'پنهان‌کردن رمز' : 'نمایش رمز'"
                @click="showPassword = !showPassword"
              >
                <svg v-if="showPassword" class="w-5 h-5" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                  <line x1="1" y1="1" x2="23" y2="23" />
                </svg>
                <svg v-else class="w-5 h-5" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              </button>
            </div>
          </div>
        </div>

        <p
          v-if="error"
          class="text-red-600 text-sm bg-red-50 border border-red-100 rounded-xl px-3.5 py-2.5"
          role="alert"
        >{{ error }}</p>

        <button
          type="submit"
          :disabled="loading"
          class="w-full bg-brand-600 text-white rounded-xl py-3 font-medium hover:bg-brand-700 active:scale-[0.99] disabled:opacity-60 disabled:active:scale-100 transition shadow-soft"
        >
          {{ loading ? "در حال ورود…" : "ورود" }}
        </button>

        <div class="flex items-center justify-between pt-1">
          <p class="text-xs text-slate-400">مشکلی در ورود دارید؟ با مدیر سیستم تماس بگیرید.</p>
          <button
            type="button"
            class="p-2 -m-2 rounded-full text-slate-400 hover:text-ink transition-colors"
            :title="ui.dark ? 'حالت روشن' : 'حالت شب'"
            :aria-label="ui.dark ? 'حالت روشن' : 'حالت شب'"
            @click="ui.toggleDark()"
          >
            <svg v-if="ui.dark" class="w-4 h-4" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
            </svg>
            <svg v-else class="w-4 h-4" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
            </svg>
          </button>
        </div>
      </form>
    </main>
  </div>
</template>
