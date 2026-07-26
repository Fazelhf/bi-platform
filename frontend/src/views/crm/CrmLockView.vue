<script setup lang="ts">
import { nextTick, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useCrmStore } from "@/stores/crm";

/**
 * The «دمو CRM» lock screen.
 *
 * The CRM ships inside the main platform but stays closed behind its own
 * password, so it can be demonstrated to someone without handing over an
 * account — and so it does not sit in the sidebar as a live section before
 * it is meant to be.
 */
const crm = useCrmStore();
const router = useRouter();
const route = useRoute();

const password = ref("");
const error = ref("");
const busy = ref(false);
const field = ref<HTMLInputElement | null>(null);

onMounted(async () => {
  // Already unlocked (a refresh, or arriving from another CRM page)? Go in.
  if (await crm.checkGate()) {
    router.replace((route.query.next as string) || { name: "crm-dashboard" });
    return;
  }
  await nextTick();
  field.value?.focus();
});

async function submit() {
  if (!password.value || busy.value) return;
  busy.value = true;
  error.value = "";
  const message = await crm.unlock(password.value);
  busy.value = false;
  if (message) {
    error.value = message;
    password.value = "";
    field.value?.focus();
    return;
  }
  router.replace((route.query.next as string) || { name: "crm-dashboard" });
}
</script>

<template>
  <div class="flex items-start justify-center pt-6 sm:pt-16">
    <div class="w-full max-w-md">
      <div class="bg-surface rounded-card shadow-soft p-7 text-center">
        <div class="w-14 h-14 rounded-2xl bg-panel text-white mx-auto flex items-center justify-center">
          <svg class="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
        </div>

        <h1 class="text-lg font-bold text-ink mt-4">دمو CRM</h1>
        <p class="text-sm text-slate-400 mt-2 leading-6">
          این بخش نسخهٔ آزمایشی مدیریت ارتباط با مشتری است و رمز جداگانه دارد.
          <br />برای مشاهده، رمز دمو را وارد کنید.
        </p>

        <form class="mt-6 space-y-3" @submit.prevent="submit">
          <input
            ref="field"
            v-model="password"
            type="password"
            autocomplete="off"
            placeholder="رمز دمو"
            class="w-full bg-slate-100 rounded-xl px-4 py-3 text-sm text-ink text-center outline-none focus:ring-2 focus:ring-slate-300"
          />

          <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line">
            {{ error }}
          </p>

          <button
            type="submit"
            class="w-full bg-panel text-white rounded-xl py-3 text-sm font-medium disabled:opacity-50"
            :disabled="busy || !password"
          >{{ busy ? "در حال بررسی…" : "ورود به دمو" }}</button>
        </form>

        <button
          class="text-xs text-slate-400 hover:text-ink mt-5"
          @click="router.push({ name: 'home' })"
        >بازگشت به داشبورد اصلی</button>
      </div>

      <p class="text-center text-[11px] text-slate-300 mt-4 leading-5">
        رمز دمو مستقل از رمز حساب کاربری شماست و توسط مدیر سیستم تعیین می‌شود.
      </p>
    </div>
  </div>
</template>
