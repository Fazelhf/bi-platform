<script setup lang="ts">
/**
 * تغییر رمز عبور — the signed-in user sets a new password by giving the
 * current one. The server checks the platform's password policy; its
 * messages are shown as they come back, in Persian.
 */
import { computed, ref } from "vue";
import { apiMessage, securityApi } from "@/api/security";
import { toast } from "@/composables/useUi";

const current = ref("");
const next = ref("");
const repeat = ref("");
const show = ref(false);
const busy = ref(false);
const error = ref("");

const mismatch = computed(() => !!repeat.value && next.value !== repeat.value);
const ready = computed(() => !!current.value && !!next.value && next.value === repeat.value);

async function submit() {
  if (!ready.value || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const res = await securityApi.changePassword(current.value, next.value);
    toast.success(res.detail || "رمز عبور تغییر کرد.");
    current.value = next.value = repeat.value = "";
  } catch (e: any) {
    error.value = apiMessage(e, "تغییر رمز ممکن نشد.");
  } finally {
    busy.value = false;
  }
}

const inputClass =
  "w-full bg-surface border border-slate-200 rounded-xl px-3.5 py-3 text-sm text-ink placeholder:text-slate-400 focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500 outline-none transition";
</script>

<template>
  <form class="bg-surface rounded-card shadow-soft p-5 space-y-4" @submit.prevent="submit">
    <div class="flex items-center justify-between gap-3">
      <p class="font-bold text-ink">تغییر رمز عبور</p>
      <button type="button" class="text-xs text-brand-600 hover:underline" @click="show = !show">
        {{ show ? "پنهان کردن رمزها" : "نمایش رمزها" }}
      </button>
    </div>

    <div>
      <label for="pw-current" class="block text-sm mb-1.5 text-slate-600">رمز عبور فعلی</label>
      <input id="pw-current" v-model="current" :type="show ? 'text' : 'password'"
        autocomplete="current-password" dir="ltr" :class="inputClass" />
    </div>
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <div>
        <label for="pw-new" class="block text-sm mb-1.5 text-slate-600">رمز عبور جدید</label>
        <input id="pw-new" v-model="next" :type="show ? 'text' : 'password'"
          autocomplete="new-password" dir="ltr" :class="inputClass" />
      </div>
      <div>
        <label for="pw-repeat" class="block text-sm mb-1.5 text-slate-600">تکرار رمز جدید</label>
        <input id="pw-repeat" v-model="repeat" :type="show ? 'text' : 'password'"
          autocomplete="new-password" dir="ltr" :class="inputClass" />
      </div>
    </div>
    <p v-if="mismatch" class="text-xs text-red-500">تکرار رمز با رمز جدید یکی نیست.</p>
    <p v-if="error" class="text-sm text-red-500">{{ error }}</p>

    <button
      type="submit"
      class="w-full py-3 rounded-xl bg-brand-500 hover:bg-brand-600 text-white text-sm font-medium transition disabled:opacity-50"
      :disabled="!ready || busy"
    >
      {{ busy ? "در حال ذخیره…" : "ذخیره‌ی رمز جدید" }}
    </button>
  </form>
</template>
