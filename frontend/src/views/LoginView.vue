<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { homeRouteFor } from "@/router";
import { apiMessage } from "@/api/security";
import AuthShell from "@/components/AuthShell.vue";
import OtpForm from "@/components/OtpForm.vue";
import type { OtpChallenge } from "@/types";

const auth = useAuthStore();
const router = useRouter();

const username = ref("");
const password = ref("");
const showPassword = ref(false);
const error = ref("");
const loading = ref(false);

/** Non-null while the account owes a one-time code (ورود دو مرحله‌ای). */
const otp = ref<OtpChallenge | null>(null);
const resending = ref(false);

function enter() {
  router.push({ name: homeRouteFor(auth.department) });
}

async function submit() {
  error.value = "";
  loading.value = true;
  try {
    const result = await auth.login(username.value, password.value);
    if (result.otpRequired) {
      otp.value = result.challenge;
      password.value = "";
    } else {
      enter();
    }
  } catch (e: any) {
    // A wrong password is by far the common case, but a code that could not
    // be sent (no credit, sender line rejected, server IP not allow-listed)
    // arrives here too — and "نام کاربری یا رمز عبور نادرست است" would send
    // the user hunting for a problem that isn't theirs.
    error.value =
      e?.response?.status === 401
        ? "نام کاربری یا رمز عبور نادرست است."
        : apiMessage(e, "نام کاربری یا رمز عبور نادرست است.");
  } finally {
    loading.value = false;
  }
}

async function verify(code: string) {
  error.value = "";
  loading.value = true;
  try {
    await auth.verifyOtp(otp.value!.challenge, code);
    enter();
  } catch (e: any) {
    error.value = apiMessage(e, "کد واردشده درست نیست.");
    // 410/429 mean the challenge is dead — the only way on is a new password
    // step, so don't leave the user typing into a box that can't succeed.
    if ([410, 429].includes(e?.response?.status)) cancelOtp();
  } finally {
    loading.value = false;
  }
}

async function resend() {
  error.value = "";
  resending.value = true;
  try {
    otp.value = await auth.resendOtp(otp.value!.challenge);
  } catch (e: any) {
    error.value = apiMessage(e, "ارسال دوبارهٔ کد ممکن نشد.");
    if ([410, 429].includes(e?.response?.status)) otp.value = null;
  } finally {
    resending.value = false;
  }
}

function cancelOtp() {
  otp.value = null;
  password.value = "";
}
</script>

<template>
  <AuthShell
    title="ورود به سامانه"
    :subtitle="otp
      ? 'برای تکمیل ورود، کد پیامک‌شده را وارد کنید.'
      : 'برای ادامه، نام کاربری و رمز عبور خود را وارد کنید.'"
  >
    <!-- Step 2: the one-time code (only for accounts with 2FA on) -->
    <OtpForm
      v-if="otp"
      :phone-masked="otp.phone_masked"
      :expires-in="otp.expires_in"
      :resend-in="otp.resend_in"
      :sends-left="otp.sends_left"
      :loading="loading"
      :resending="resending"
      :error="error"
      @submit="verify"
      @resend="resend"
      @cancel="cancelOtp"
    />

    <!-- Step 1: username + password -->
    <form v-else class="space-y-6" @submit.prevent="submit">
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

      <!-- The two ways in that don't need the password -->
      <div class="flex items-center justify-between text-sm">
        <RouterLink
          :to="{ name: 'login-otp' }"
          class="text-brand-600 hover:text-brand-700 transition-colors"
        >ورود با کد پیامکی</RouterLink>
        <RouterLink
          :to="{ name: 'forgot-password' }"
          class="text-slate-500 hover:text-ink transition-colors"
        >رمز عبور را فراموش کرده‌اید؟</RouterLink>
      </div>
    </form>
  </AuthShell>
</template>
