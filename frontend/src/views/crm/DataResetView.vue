<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { crmApi, type WipeInfo } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num } from "@/utils/format";
import Skeleton from "@/components/Skeleton.vue";
import NavIcon from "@/components/NavIcon.vue";

/**
 * پاک‌سازی داده — empty CRM before loading it again from آرپا and دیدار.
 *
 * It says exactly what goes and what stays before anything happens, and asks
 * for a typed phrase rather than a click: a button alone is one slip away
 * from deleting the company's sales record. Customers and products stay —
 * see `apps.crm.wipe` for why.
 */
const crm = useCrmStore();
const info = ref<WipeInfo | null>(null);
const typed = ref("");
const busy = ref(false);
const error = ref("");
const done = ref<Record<string, number> | null>(null);

async function load() {
  info.value = await crmApi.wipeInfo();
}
onMounted(load);

const total = computed(() => info.value?.remove.reduce((a, r) => a + r.count, 0) ?? 0);
const ready = computed(() => !!info.value && typed.value.trim() === info.value.confirm);

async function run() {
  if (!ready.value) return;
  busy.value = true;
  error.value = "";
  try {
    const res = await crmApi.wipe(typed.value.trim());
    done.value = res.removed;
    info.value = res;
    typed.value = "";
    crm.bump();
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? "پاک‌سازی انجام نشد.";
  } finally {
    busy.value = false;
  }
}

const card = "bg-surface rounded-card shadow-soft p-4 min-w-0";
</script>

<template>
  <div class="space-y-4 max-w-3xl">
    <div v-if="done" class="flex items-start gap-3 bg-emerald-50 text-emerald-800 rounded-xl px-4 py-3 text-sm">
      <NavIcon name="check" :size="20" />
      <div>
        <p class="font-semibold">CRM خالی شد. حالا از «ورود از آرپا» و «ورود از دیدار» داده را وارد کنید.</p>
        <p class="text-xs mt-1">
          <span v-for="(n, label) in done" :key="label" class="inline-block ml-3">{{ label }}: {{ num(n) }}</span>
        </p>
      </div>
    </div>

    <div :class="card" class="space-y-4">
      <div class="flex items-start gap-3">
        <span class="w-10 h-10 rounded-2xl bg-red-50 text-red-500 grid place-items-center shrink-0">
          <NavIcon name="trash" :size="20" />
        </span>
        <div>
          <h2 class="font-bold text-ink">خالی کردن CRM برای ورود دوباره</h2>
          <p class="text-xs text-slate-500 mt-1 leading-6">
            هرچه با ورود فایل دوباره می‌آید پاک می‌شود. این کار برگشت ندارد.
          </p>
        </div>
      </div>

      <Skeleton v-if="!info" class="h-40 rounded-xl" />
      <template v-else>
        <div class="grid sm:grid-cols-2 gap-4">
          <div class="rounded-xl border border-red-100 bg-red-50/40 p-3">
            <p class="text-xs font-semibold text-red-600 mb-2">پاک می‌شود — {{ num(total) }} ردیف</p>
            <ul class="text-sm space-y-1">
              <li v-for="r in info.remove" :key="r.key" class="flex justify-between gap-2">
                <span :class="r.count ? 'text-ink' : 'text-slate-400'">{{ r.label }}</span>
                <span :class="r.count ? 'text-red-600 font-medium' : 'text-slate-300'">{{ num(r.count) }}</span>
              </li>
            </ul>
          </div>
          <div class="rounded-xl border border-emerald-100 bg-emerald-50/40 p-3">
            <p class="text-xs font-semibold text-emerald-700 mb-2">می‌ماند</p>
            <ul class="text-sm space-y-2 text-ink">
              <li class="flex justify-between gap-2"><span>مشتری‌ها (با کد آرپا و دیدارشان)</span><span class="font-medium">{{ num(info.keep.customers) }}</span></li>
              <li class="text-slate-600">محصولات — قیمت و بهای فروش ۲ به آن‌ها وصل است</li>
              <li class="text-slate-600">صف بازبینی تطبیق</li>
            </ul>
          </div>
        </div>

        <div class="space-y-2">
          <label class="text-sm text-slate-600 block">
            برای تأیید، عبارت <b class="text-red-600">«{{ info.confirm }}»</b> را بنویسید:
          </label>
          <div class="flex flex-wrap gap-2">
            <input
              v-model="typed"
              class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-red-300 w-56"
              :placeholder="info.confirm"
              @keydown.enter="run"
            />
            <button
              class="bg-red-600 text-white rounded-xl px-5 py-2 text-sm disabled:opacity-40"
              :disabled="!ready || busy || !total"
              @click="run"
            >{{ busy ? "در حال پاک‌سازی…" : "پاک کردن" }}</button>
          </div>
          <p v-if="!total" class="text-xs text-slate-400">چیزی برای پاک کردن نیست.</p>
          <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
        </div>
      </template>
    </div>
  </div>
</template>
