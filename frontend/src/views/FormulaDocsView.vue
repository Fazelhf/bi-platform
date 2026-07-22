<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { formulasApi, kpiApi } from "@/api/platform";
import { useAuthStore } from "@/stores/auth";
import type { Formula, KpiDefinition } from "@/types";

const auth = useAuthStore();

// A manager sees the formulas of their own domain.
const domain = computed(() =>
  auth.department === "production" ? "production" : "sales",
);

const kpis = ref<KpiDefinition[]>([]);
const formulas = ref<Formula[]>([]);
const loading = ref(true);
const message = ref("");

const SLOT_FA: Record<string, string> = { actual: "واقعی", target: "مطلوب", ideal: "ایده‌آل" };

function forKpi(kpiId: number) {
  return formulas.value
    .filter((f) => f.kpi === kpiId && f.is_active)
    .sort((a, b) => a.slot.localeCompare(b.slot));
}

async function load() {
  loading.value = true;
  try {
    [kpis.value, formulas.value] = await Promise.all([
      kpiApi.list(domain.value),
      formulasApi.list({ "kpi__domain": domain.value }),
    ]);
  } finally {
    loading.value = false;
  }
}

async function requestChange(f: Formula) {
  const note = window.prompt(`درخواست تغییر برای «${f.kpi_name_fa}» (${SLOT_FA[f.slot]}):\nتوضیح دهید چه تغییری لازم است؟`);
  if (note === null) return;
  const r = await formulasApi.requestChange(f.id, note);
  message.value = r.message;
  window.setTimeout(() => (message.value = ""), 5000);
}

onMounted(load);
</script>

<template>
  <div class="space-y-4">
    <div>
      <h2 class="text-lg font-bold text-ink">فرمول شاخص‌ها</h2>
      <p class="text-xs text-slate-400 mt-0.5">
        فرمول هر شاخص و چارت اینجا توضیح داده شده. نیازی به تغییر نیست؛ اگر لازم بود،
        «درخواست تغییر» بزنید تا برای مدیر سیستم ارسال شود.
      </p>
    </div>

    <p v-if="message" class="text-sm bg-accent-50 text-accent-600 rounded-xl p-3">{{ message }}</p>
    <div v-if="loading" class="text-slate-400">در حال بارگذاری…</div>

    <div v-else class="space-y-3">
      <div v-for="k in kpis" :key="k.id" class="bg-white rounded-card shadow-soft p-5">
        <div class="flex items-start justify-between gap-3">
          <div>
            <h3 class="font-bold text-ink">{{ k.name_fa }}</h3>
            <p class="text-xs text-slate-400 mt-1">{{ k.formula_note }}</p>
          </div>
          <span class="text-[11px] bg-slate-100 text-slate-500 rounded-full px-2 py-0.5 shrink-0">
            {{ k.unit }} · {{ k.direction === "higher" ? "بیشتر بهتر" : "کمتر بهتر" }}
          </span>
        </div>

        <div v-if="forKpi(k.id).length" class="mt-3 space-y-2">
          <div
            v-for="f in forKpi(k.id)"
            :key="f.id"
            class="flex items-center justify-between gap-3 bg-slate-50 rounded-xl px-3 py-2"
          >
            <div class="min-w-0">
              <span class="text-[11px] text-slate-400 ml-2">{{ SLOT_FA[f.slot] }}</span>
              <code class="text-sm text-ink" dir="ltr">{{ f.expression }}</code>
            </div>
            <button
              class="text-xs text-brand-600 hover:underline shrink-0"
              @click="requestChange(f)"
            >درخواست تغییر</button>
          </div>
        </div>
        <p v-else class="text-xs text-slate-400 mt-2">فرمولی ثبت نشده (محاسبه پیش‌فرض).</p>
      </div>
    </div>
  </div>
</template>
