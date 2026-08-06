<script setup lang="ts">
/**
 * امنیت حساب — where a user turns two-step login on or off for themselves.
 *
 * Enrolment is a possession check, not a checkbox: the number is typed here,
 * a code goes to it, and 2FA only switches on once that code comes back. That
 * is also why no administrator screen can switch it *on* for someone else —
 * a wrong digit there would lock an account out with nobody able to prove the
 * number was never theirs.
 */
import { computed, onMounted, ref } from "vue";
import { apiMessage, securityApi } from "@/api/security";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/composables/useUi";
import OtpForm from "@/components/OtpForm.vue";
import type { OtpChallenge, TwoFactorStatus } from "@/types";

const auth = useAuthStore();

const status = ref<TwoFactorStatus | null>(null);
const loading = ref(true);
const busy = ref(false);
const resending = ref(false);
const error = ref("");

/** "off" → enter phone+password · "code" → confirm · "on" → enabled. */
const phone = ref("");
const password = ref("");
const otp = ref<OtpChallenge | null>(null);

const enabled = computed(() => !!status.value?.enabled);

async function load() {
  loading.value = true;
  try {
    status.value = await securityApi.status();
    phone.value = status.value.phone || "";
  } catch (e: any) {
    error.value = apiMessage(e);
  } finally {
    loading.value = false;
  }
}

async function start() {
  error.value = "";
  busy.value = true;
  try {
    otp.value = await securityApi.start(phone.value, password.value);
  } catch (e: any) {
    error.value = apiMessage(e, "ارسال کد ممکن نشد.");
  } finally {
    busy.value = false;
  }
}

async function confirm(code: string) {
  error.value = "";
  busy.value = true;
  try {
    status.value = await securityApi.confirm(otp.value!.challenge, code);
    otp.value = null;
    password.value = "";
    await auth.fetchMe();
    toast.success("ورود دو مرحله‌ای فعال شد.");
  } catch (e: any) {
    error.value = apiMessage(e, "کد واردشده درست نیست.");
    if ([410, 429].includes(e?.response?.status)) otp.value = null;
  } finally {
    busy.value = false;
  }
}

async function resend() {
  error.value = "";
  resending.value = true;
  try {
    otp.value = await securityApi.resend(otp.value!.challenge);
  } catch (e: any) {
    error.value = apiMessage(e, "ارسال دوبارهٔ کد ممکن نشد.");
    if ([410, 429].includes(e?.response?.status)) otp.value = null;
  } finally {
    resending.value = false;
  }
}

async function disable() {
  error.value = "";
  busy.value = true;
  try {
    status.value = await securityApi.disable(password.value);
    password.value = "";
    await auth.fetchMe();
    toast.success("ورود دو مرحله‌ای غیرفعال شد.");
  } catch (e: any) {
    error.value = apiMessage(e, "غیرفعال‌سازی ممکن نشد.");
  } finally {
    busy.value = false;
  }
}

const inputClass =
  "w-full bg-surface border border-slate-200 rounded-xl px-3.5 py-3 text-sm text-ink placeholder:text-slate-400 focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500 outline-none transition";

onMounted(load);
</script>

<template>
  <div class="max-w-xl space-y-4">
    <div>
      <h1 class="text-xl font-bold text-ink">امنیت حساب</h1>
      <p class="text-sm text-slate-500 mt-1.5 leading-7">
        با فعال‌کردن ورود دو مرحله‌ای، پس از رمز عبور یک کد شش‌رقمی به موبایل شما
        پیامک می‌شود و ورود فقط با آن کامل می‌گردد.
      </p>
    </div>

    <div v-if="loading" class="bg-surface rounded-card shadow-soft p-5 text-sm text-slate-400">
      در حال بارگذاری…
    </div>

    <div v-else class="bg-surface rounded-card shadow-soft p-5 space-y-5">
      <!-- Current state -->
      <div class="flex items-center justify-between gap-3">
        <div>
          <p class="font-bold text-ink">ورود دو مرحله‌ای</p>
          <p v-if="enabled" class="text-sm text-slate-500 mt-1">
            فعال — کد به
            <span class="ltr-nums">{{ status?.phone_masked }}</span>
            ارسال می‌شود.
          </p>
          <p v-else class="text-sm text-slate-500 mt-1">غیرفعال است.</p>
        </div>
        <span
          class="text-xs rounded-full px-3 py-1.5 font-medium"
          :class="enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'"
        >{{ enabled ? "فعال" : "غیرفعال" }}</span>
      </div>

      <p
        v-if="!status?.sms_configured"
        class="text-sm text-amber-700 bg-amber-50 border border-amber-100 rounded-xl px-3.5 py-2.5"
      >
        سرویس پیامک روی سرور پیکربندی نشده است؛ تا آن زمان فعال‌سازی ممکن نیست.
        با مدیر سیستم تماس بگیرید.
      </p>

      <p
        v-if="error"
        class="text-red-600 text-sm bg-red-50 border border-red-100 rounded-xl px-3.5 py-2.5"
        role="alert"
      >{{ error }}</p>

      <!-- Step 2 of enrolment -->
      <OtpForm
        v-if="otp"
        :phone-masked="otp.phone_masked"
        :expires-in="otp.expires_in"
        :resend-in="otp.resend_in"
        :sends-left="otp.sends_left"
        :loading="busy"
        :resending="resending"
        submit-label="تأیید و فعال‌سازی"
        @submit="confirm"
        @resend="resend"
        @cancel="otp = null"
      />

      <!-- Turn it off -->
      <form v-else-if="enabled" class="space-y-4" @submit.prevent="disable">
        <div>
          <label for="pw-off" class="block text-sm mb-1.5 text-slate-600">
            برای غیرفعال‌کردن، رمز عبور خود را وارد کنید
          </label>
          <input
            id="pw-off"
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="••••••••"
            :class="inputClass"
          />
        </div>
        <button
          type="submit"
          :disabled="busy || !password"
          class="rounded-xl px-4 py-2.5 text-sm font-medium text-red-600 border border-red-200 hover:bg-red-50 disabled:opacity-60 transition"
        >{{ busy ? "در حال انجام…" : "غیرفعال‌کردن ورود دو مرحله‌ای" }}</button>
      </form>

      <!-- Turn it on -->
      <form v-else class="space-y-4" @submit.prevent="start">
        <div>
          <label for="otp-phone" class="block text-sm mb-1.5 text-slate-600">شمارهٔ موبایل</label>
          <input
            id="otp-phone"
            v-model="phone"
            inputmode="tel"
            dir="ltr"
            placeholder="09123456789"
            :class="inputClass + ' ltr-nums'"
          />
          <p class="text-xs text-slate-400 mt-1.5">
            کد تأیید به همین شماره ارسال می‌شود؛ آن را با دقت وارد کنید.
          </p>
        </div>
        <div>
          <label for="pw-on" class="block text-sm mb-1.5 text-slate-600">رمز عبور فعلی</label>
          <input
            id="pw-on"
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="••••••••"
            :class="inputClass"
          />
        </div>
        <button
          type="submit"
          :disabled="busy || !phone || !password || !status?.sms_configured"
          class="bg-brand-600 text-white rounded-xl px-5 py-2.5 text-sm font-medium hover:bg-brand-700 disabled:opacity-60 transition shadow-soft"
        >{{ busy ? "در حال ارسال کد…" : "فعال‌سازی و ارسال کد" }}</button>
      </form>
    </div>

    <p class="text-xs text-slate-400 leading-6">
      اگر دسترسی به موبایل خود را از دست دادید، مدیر سیستم می‌تواند ورود دو
      مرحله‌ای حساب شما را از «مدیریت کاربران» غیرفعال کند.
    </p>
  </div>
</template>
