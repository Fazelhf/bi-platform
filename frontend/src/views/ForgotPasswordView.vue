<script setup lang="ts">
/**
 * فراموشی رمز — three steps: who are you · the code · the new password.
 *
 * The last step signs the user straight in. Making them log in again with a
 * password they typed thirty seconds ago is a step that can only go wrong.
 */
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { apiMessage, recoveryApi } from "@/api/security";
import { useAuthStore } from "@/stores/auth";
import { homeRouteFor } from "@/router";
import { toast } from "@/composables/useUi";
import AuthShell from "@/components/AuthShell.vue";
import OtpForm from "@/components/OtpForm.vue";
import type { OtpChallenge } from "@/types";

const auth = useAuthStore();
const router = useRouter();

const identifier = ref("");
const otp = ref<OtpChallenge | null>(null);
/** The permit earned by the code; its presence is step 3. */
const permit = ref("");
const password = ref("");
const confirmPassword = ref("");
const showPassword = ref(false);

const loading = ref(false);
const resending = ref(false);
const error = ref("");

const mismatch = computed(
  () => !!confirmPassword.value && password.value !== confirmPassword.value,
);
const subtitle = computed(() => {
  if (permit.value) return "رمز عبور تازه‌ای برای حساب خود انتخاب کنید.";
  if (otp.value) return "کد پیامک‌شده را وارد کنید.";
  return "نام کاربری یا شمارهٔ موبایل خود را وارد کنید تا کد بازیابی برایتان پیامک شود.";
});

async function start() {
  error.value = "";
  loading.value = true;
  try {
    otp.value = await recoveryApi.resetStart(identifier.value);
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
    permit.value = await recoveryApi.resetVerify(otp.value!.challenge, code);
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
    otp.value = await recoveryApi.resend(otp.value!.challenge, "reset");
  } catch (e: any) {
    error.value = apiMessage(e, "ارسال دوبارهٔ کد ممکن نشد.");
    if ([410, 429].includes(e?.response?.status)) otp.value = null;
  } finally {
    resending.value = false;
  }
}

async function save() {
  error.value = "";
  loading.value = true;
  try {
    await auth.accept(await recoveryApi.resetConfirm(permit.value, password.value));
    toast.success("رمز عبور تغییر کرد.");
    router.push({ name: homeRouteFor(auth.department) });
  } catch (e: any) {
    error.value = apiMessage(e, "تغییر رمز عبور ممکن نشد.");
    // An expired permit cannot be revived — send them back to the start.
    if (e?.response?.data?.reset_token) {
      permit.value = "";
      otp.value = null;
    }
  } finally {
    loading.value = false;
  }
}

const inputClass =
  "w-full bg-surface border border-slate-200 rounded-xl px-3.5 py-3 text-sm text-ink placeholder:text-slate-400 focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500 outline-none transition";
</script>

<template>
  <AuthShell title="بازیابی رمز عبور" :subtitle="subtitle">
    <!-- Step 3: the new password -->
    <form v-if="permit" class="space-y-5" @submit.prevent="save">
      <div>
        <label for="new-password" class="block text-sm mb-1.5 text-slate-600">رمز عبور جدید</label>
        <div class="relative">
          <input
            id="new-password"
            v-model="password"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="new-password"
            placeholder="••••••••"
            :class="inputClass + ' pl-11'"
          />
          <button
            type="button"
            class="absolute inset-y-0 left-0 px-3 flex items-center text-slate-400 hover:text-ink transition-colors"
            :aria-label="showPassword ? 'پنهان‌کردن رمز' : 'نمایش رمز'"
            @click="showPassword = !showPassword"
          >{{ showPassword ? "🙈" : "👁" }}</button>
        </div>
        <p class="text-xs text-slate-400 mt-1.5">
          دست‌کم ۸ نویسه، و نه یک رمز خیلی رایج یا فقط عدد.
        </p>
      </div>

      <div>
        <label for="confirm-password" class="block text-sm mb-1.5 text-slate-600">تکرار رمز جدید</label>
        <input
          id="confirm-password"
          v-model="confirmPassword"
          type="password"
          autocomplete="new-password"
          placeholder="••••••••"
          :class="inputClass"
        />
        <p v-if="mismatch" class="text-xs text-red-600 mt-1.5">دو رمز یکسان نیستند.</p>
      </div>

      <p
        v-if="error"
        class="text-red-600 text-sm bg-red-50 border border-red-100 rounded-xl px-3.5 py-2.5"
        role="alert"
      >{{ error }}</p>

      <button
        type="submit"
        :disabled="loading || !password || mismatch"
        class="w-full bg-brand-600 text-white rounded-xl py-3 font-medium hover:bg-brand-700 active:scale-[0.99] disabled:opacity-60 disabled:active:scale-100 transition shadow-soft"
      >{{ loading ? "در حال ذخیره…" : "ثبت رمز جدید و ورود" }}</button>
    </form>

    <!-- Step 2: the code -->
    <OtpForm
      v-else-if="otp"
      :phone-masked="otp.phone_masked"
      :expires-in="otp.expires_in"
      :resend-in="otp.resend_in"
      :sends-left="otp.sends_left"
      :loading="loading"
      :resending="resending"
      :error="error"
      submit-label="تأیید کد"
      @submit="verify"
      @resend="resend"
      @cancel="otp = null"
    />

    <!-- Step 1: who are you -->
    <form v-else class="space-y-5" @submit.prevent="start">
      <div>
        <label for="reset-identifier" class="block text-sm mb-1.5 text-slate-600">
          نام کاربری یا شمارهٔ موبایل
        </label>
        <input
          id="reset-identifier"
          v-model="identifier"
          autocomplete="username"
          placeholder="مثلاً ali یا 09123456789"
          :class="inputClass"
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
      >{{ loading ? "در حال ارسال کد…" : "ارسال کد بازیابی" }}</button>
    </form>

    <template #footer>
      <RouterLink :to="{ name: 'login' }" class="text-brand-600 hover:text-brand-700">
        ← بازگشت به صفحهٔ ورود
      </RouterLink>
    </template>
  </AuthShell>
</template>
