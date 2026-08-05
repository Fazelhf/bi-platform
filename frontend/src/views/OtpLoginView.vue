<script setup lang="ts">
/**
 * ورود با کد پیامکی — sign in with a code and no password.
 *
 * The first field takes either the username or the mobile number, because
 * someone reaching for this screen has usually forgotten one of the two.
 */
import { ref } from "vue";
import { useRouter } from "vue-router";
import { apiMessage, recoveryApi } from "@/api/security";
import { useAuthStore } from "@/stores/auth";
import { homeRouteFor } from "@/router";
import AuthShell from "@/components/AuthShell.vue";
import OtpForm from "@/components/OtpForm.vue";
import type { OtpChallenge } from "@/types";

const auth = useAuthStore();
const router = useRouter();

const identifier = ref("");
const otp = ref<OtpChallenge | null>(null);
const loading = ref(false);
const resending = ref(false);
const error = ref("");

async function start() {
  error.value = "";
  loading.value = true;
  try {
    otp.value = await recoveryApi.otpLoginStart(identifier.value);
  } catch (e: any) {
    error.value = apiMessage(e, "ارسال کد ممکن نشد.");
  } finally {
    loading.value = false;
  }
}

async function verify(code: string) {
  error.value = "";
  loading.value = true;
  try {
    await auth.accept(await recoveryApi.otpLoginVerify(otp.value!.challenge, code));
    router.push({ name: homeRouteFor(auth.department) });
  } catch (e: any) {
    error.value = apiMessage(e, "کد واردشده درست نیست.");
    if ([410, 429].includes(e?.response?.status)) otp.value = null;
  } finally {
    loading.value = false;
  }
}

async function resend() {
  error.value = "";
  resending.value = true;
  try {
    otp.value = await recoveryApi.resend(otp.value!.challenge, "otp_login");
  } catch (e: any) {
    error.value = apiMessage(e, "ارسال دوبارهٔ کد ممکن نشد.");
    if ([410, 429].includes(e?.response?.status)) otp.value = null;
  } finally {
    resending.value = false;
  }
}
</script>

<template>
  <AuthShell
    title="ورود با کد پیامکی"
    :subtitle="otp
      ? 'کد پیامک‌شده را وارد کنید تا وارد سامانه شوید.'
      : 'نام کاربری یا شمارهٔ موبایل خود را وارد کنید تا کد ورود برایتان پیامک شود.'"
  >
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
      @cancel="otp = null"
    />

    <form v-else class="space-y-5" @submit.prevent="start">
      <div>
        <label for="identifier" class="block text-sm mb-1.5 text-slate-600">
          نام کاربری یا شمارهٔ موبایل
        </label>
        <input
          id="identifier"
          v-model="identifier"
          autocomplete="username"
          placeholder="مثلاً ali یا 09123456789"
          class="w-full bg-surface border border-slate-200 rounded-xl px-3.5 py-3 text-sm text-ink placeholder:text-slate-400 focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500 outline-none transition"
        />
      </div>

      <p
        v-if="error"
        class="text-red-600 text-sm bg-red-50 border border-red-100 rounded-xl px-3.5 py-2.5"
        role="alert"
      >{{ error }}</p>

      <button
        type="submit"
        :disabled="loading || !identifier"
        class="w-full bg-brand-600 text-white rounded-xl py-3 font-medium hover:bg-brand-700 active:scale-[0.99] disabled:opacity-60 disabled:active:scale-100 transition shadow-soft"
      >{{ loading ? "در حال ارسال کد…" : "ارسال کد ورود" }}</button>
    </form>

    <template #footer>
      <RouterLink :to="{ name: 'login' }" class="text-brand-600 hover:text-brand-700">
        ← ورود با نام کاربری و رمز عبور
      </RouterLink>
    </template>
  </AuthShell>
</template>
