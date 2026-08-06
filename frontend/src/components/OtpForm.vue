<script setup lang="ts">
/**
 * The one-time-code step, shared by the login screen and the account-security
 * page — the two places a code is ever entered, and they should not drift.
 *
 * One six-digit field rather than six single-character boxes: the boxes look
 * smarter and behave worse in an RTL page, and they fight the paste that most
 * people use when the code is sitting in a notification.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{
  phoneMasked: string;
  /** Seconds until the code dies, as of the last server response. */
  expiresIn: number;
  /** Seconds until re-sending is allowed. */
  resendIn: number;
  sendsLeft: number;
  loading?: boolean;
  resending?: boolean;
  error?: string;
  /** Label of the confirm button — "ورود" on login, "تأیید" on enrolment. */
  submitLabel?: string;
}>();

const emit = defineEmits<{
  (e: "submit", code: string): void;
  (e: "resend"): void;
  (e: "cancel"): void;
}>();

const code = ref("");
const field = ref<HTMLInputElement | null>(null);
const expires = ref(props.expiresIn);
const cooldown = ref(props.resendIn);

// Persian digits in, Latin digits out — the numeric keypad on a Persian
// keyboard produces ۰-۹, and the API compares against 0-9.
const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩";
function onInput(event: Event) {
  const raw = (event.target as HTMLInputElement).value;
  code.value = raw
    .replace(/[۰-۹٠-٩]/g, (d) => String(FA_DIGITS.indexOf(d) % 10))
    .replace(/\D/g, "")
    .slice(0, 6);
}

const expired = computed(() => expires.value <= 0);
const canSubmit = computed(
  () => code.value.length === 6 && !props.loading && !expired.value,
);
const canResend = computed(
  () => cooldown.value <= 0 && props.sendsLeft > 0 && !props.resending,
);

function mmss(total: number): string {
  const m = Math.floor(Math.max(total, 0) / 60);
  const s = Math.max(total, 0) % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

let timer = 0;
onMounted(() => {
  field.value?.focus();
  timer = window.setInterval(() => {
    if (expires.value > 0) expires.value--;
    if (cooldown.value > 0) cooldown.value--;
  }, 1000);
});
onBeforeUnmount(() => window.clearInterval(timer));

// A fresh send restarts both clocks and clears whatever was half-typed.
watch(
  () => [props.expiresIn, props.resendIn],
  ([e, r]) => {
    expires.value = e;
    cooldown.value = r;
    code.value = "";
    field.value?.focus();
  },
);

function submit() {
  if (canSubmit.value) emit("submit", code.value);
}
</script>

<template>
  <form class="space-y-5" @submit.prevent="submit">
    <div>
      <h2 class="text-lg font-bold text-ink">کد تأیید</h2>
      <p class="text-sm text-slate-500 mt-1.5 leading-7">
        کد شش‌رقمی به شمارهٔ
        <span class="ltr-nums font-medium text-ink">{{ phoneMasked }}</span>
        پیامک شد.
      </p>
    </div>

    <div>
      <label for="otp-code" class="sr-only">کد تأیید</label>
      <input
        id="otp-code"
        ref="field"
        :value="code"
        inputmode="numeric"
        autocomplete="one-time-code"
        maxlength="6"
        dir="ltr"
        placeholder="------"
        class="w-full bg-surface border border-slate-200 rounded-xl px-3.5 py-3 text-center text-2xl font-bold tracking-[0.5em] text-ink placeholder:text-slate-300 placeholder:tracking-[0.4em] focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500 outline-none transition"
        @input="onInput"
      />
      <div class="flex items-center justify-between mt-2 text-xs">
        <span v-if="!expired" class="text-slate-400">
          اعتبار کد: <span class="ltr-nums">{{ mmss(expires) }}</span>
        </span>
        <span v-else class="text-amber-600">کد منقضی شد؛ کد تازه بگیرید.</span>

        <button
          type="button"
          :disabled="!canResend"
          class="text-brand-600 hover:text-brand-700 disabled:text-slate-400 disabled:cursor-default transition-colors"
          @click="emit('resend')"
        >
          <template v-if="sendsLeft <= 0">ارسال دوباره ممکن نیست</template>
          <template v-else-if="cooldown > 0">
            ارسال دوباره تا <span class="ltr-nums">{{ mmss(cooldown) }}</span>
          </template>
          <template v-else>{{ resending ? "در حال ارسال…" : "ارسال دوبارهٔ کد" }}</template>
        </button>
      </div>
    </div>

    <p
      v-if="error"
      class="text-red-600 text-sm bg-red-50 border border-red-100 rounded-xl px-3.5 py-2.5"
      role="alert"
    >{{ error }}</p>

    <div class="flex items-center gap-3">
      <button
        type="submit"
        :disabled="!canSubmit"
        class="flex-1 bg-brand-600 text-white rounded-xl py-3 font-medium hover:bg-brand-700 active:scale-[0.99] disabled:opacity-60 disabled:active:scale-100 transition shadow-soft"
      >
        {{ loading ? "در حال بررسی…" : (submitLabel || "تأیید و ورود") }}
      </button>
      <button
        type="button"
        class="px-4 py-3 text-sm text-slate-500 hover:text-ink transition-colors"
        @click="emit('cancel')"
      >انصراف</button>
    </div>
  </form>
</template>
