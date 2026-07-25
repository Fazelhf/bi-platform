<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { salesApi } from "@/api/sales";
import { productionInputApi, type ProdInput } from "@/api/productionInput";
import { num } from "@/utils/format";
import MoneyInput from "@/components/MoneyInput.vue";
import ExportActions from "@/components/ExportActions.vue";

const periods = ref<{ id: number; label: string }[]>([]);
const selectedPeriod = ref<number | null>(null);
const data = ref<ProdInput | null>(null);
const loading = ref(true);
const saving = ref("");

async function load() {
  if (!selectedPeriod.value) return;
  loading.value = true;
  try {
    data.value = await productionInputApi.get(selectedPeriod.value);
  } finally {
    loading.value = false;
  }
}

// Live helpers so managers see totals while they type.
const totalCost = computed(() =>
  (data.value?.costs ?? []).reduce((s, c) => s + Number(c.amount_rial || 0), 0),
);
const printTotal = computed(() =>
  (data.value?.print_colors ?? []).reduce((s, c) => s + Number(c.area_sqm || 0), 0),
);
const revenueTotal = computed(() =>
  (data.value?.rolls ?? []).reduce(
    (s, r) => s + Number(r.quantity || 0) * Number(r.piece_rate_rial || 0), 0,
  ),
);

const CUT_COLS = [
  { key: "active_shifts", label: "شیفت فعال" },
  { key: "output_units", label: "تولید (شاخص)" },
  { key: "waste_pct", label: "ضایعات ٪" },
  { key: "repair_count", label: "تعمیری" },
  { key: "downtime_breakdown_shifts", label: "خواب/خرابی" },
  { key: "downtime_sizechange_shifts", label: "خواب/تغییر سایز" },
  { key: "downtime_nowork_shifts", label: "خواب/عدم سفارش" },
];
const COLOR_FA: Record<number, string> = { 1: "تک‌رنگ", 2: "دو‌رنگ", 3: "سه‌رنگ", 4: "چهار‌رنگ" };

function buildPayload(submit: boolean) {
  const d = data.value!;
  return {
    period: selectedPeriod.value,
    submit,
    total_headcount: d.benchmark.total_headcount,
    cutting: d.cutting,
    print: d.print,
    print_colors: d.print_colors,
    costs: d.costs,
    rolls: d.rolls,
  };
}

async function save(submit: boolean) {
  saving.value = submit ? "در حال ارسال…" : "در حال ذخیره…";
  try {
    await productionInputApi.save(buildPayload(submit));
    saving.value = submit ? "برای تایید ارسال شد ✓" : "ذخیره شد ✓";
    if (submit) await load();
  } catch (e: any) {
    saving.value = "خطا: " + (e?.response?.status === 403 ? "دسترسی ندارید" : "ذخیره نشد");
  }
}

onMounted(async () => {
  periods.value = await salesApi.periods();
  selectedPeriod.value = periods.value[0]?.id ?? null;
  await load();
});
watch(selectedPeriod, load);
</script>

<template>
  <div class="space-y-4 pb-8">
    <!-- Header -->
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-lg font-bold text-ink">ورود اطلاعات تولید</h2>
        <p class="text-xs text-slate-400 mt-0.5">چهار جدول زیر را با دقت پر کنید؛ شاخص‌ها پس از تایید مدیرعامل محاسبه می‌شوند.</p>
      </div>
      <div class="flex items-center gap-3">
        <span class="text-sm" :class="saving.startsWith('خطا') ? 'text-red-500' : 'text-accent-600'">{{ saving }}</span>
        <ExportActions :excel="false" />
        <select v-model.number="selectedPeriod" class="bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm">
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <div v-if="loading || !data" class="text-slate-400">در حال بارگذاری…</div>

    <template v-else>
      <!-- Table 1: cutting lines -->
      <section class="bg-surface rounded-card shadow-soft p-5">
        <div class="flex items-center gap-2 mb-4">
          <span class="w-7 h-7 rounded-lg bg-panel text-white text-xs flex items-center justify-center font-bold">۱</span>
          <h3 class="font-bold text-ink">خطوط برش</h3>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[720px]">
            <thead>
              <tr class="text-slate-400 border-b border-slate-100">
                <th class="text-right font-medium py-2 pr-2">خط تولید</th>
                <th v-for="c in CUT_COLS" :key="c.key" class="font-medium py-2 px-2 text-center">{{ c.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in data.cutting" :key="m.machine" class="border-b border-slate-50">
                <td class="py-2 pr-2 font-medium whitespace-nowrap">{{ m.machine_name }}</td>
                <td v-for="c in CUT_COLS" :key="c.key" class="py-1.5 px-1">
                  <input
                    v-model="m[c.key]"
                    type="number" step="any"
                    class="w-full bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Table 2: resources & costs -->
      <section class="bg-surface rounded-card shadow-soft p-5">
        <div class="flex items-center gap-2 mb-4">
          <span class="w-7 h-7 rounded-lg bg-panel text-white text-xs flex items-center justify-center font-bold">۲</span>
          <h3 class="font-bold text-ink">منابع و هزینه‌ها</h3>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
          <label class="flex items-center justify-between gap-3">
            <span class="text-sm text-slate-600">تعداد کل نیروی انسانی (نفرروز)</span>
            <input v-model.number="data.benchmark.total_headcount" type="number"
              class="w-40 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-3 py-1.5 text-left ltr-nums outline-none" />
          </label>
          <label v-for="c in data.costs" :key="c.category" class="flex items-center justify-between gap-3">
            <span class="text-sm text-slate-600">{{ c.category_name }}</span>
            <MoneyInput v-model="c.amount_rial"
              class="w-40 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-3 py-1.5 text-left ltr-nums outline-none" />
          </label>
        </div>
        <div class="mt-4 pt-3 border-t border-slate-100 flex justify-between text-sm">
          <span class="text-slate-500">جمع کل هزینه</span>
          <span class="font-bold text-ink ltr-nums">{{ num(totalCost) }} ریال</span>
        </div>
      </section>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <!-- Table 3: print by colour -->
        <section class="bg-surface rounded-card shadow-soft p-5">
          <div class="flex items-center gap-2 mb-4">
            <span class="w-7 h-7 rounded-lg bg-panel text-white text-xs flex items-center justify-center font-bold">۳</span>
            <h3 class="font-bold text-ink">چاپ (متراژ به تفکیک رنگ)</h3>
          </div>
          <div class="space-y-2">
            <label v-for="c in data.print_colors" :key="c.color_count" class="flex items-center justify-between gap-3">
              <span class="text-sm text-slate-600">{{ COLOR_FA[c.color_count] }} (متر مربع)</span>
              <input v-model="c.area_sqm" type="number" step="any"
                class="w-40 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-3 py-1.5 text-left ltr-nums outline-none" />
            </label>
            <label v-if="data.print" class="flex items-center justify-between gap-3 pt-1">
              <span class="text-sm text-slate-600">تعداد شیفت چاپ</span>
              <input v-model="data.print.active_shifts" type="number" step="any"
                class="w-40 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-3 py-1.5 text-left ltr-nums outline-none" />
            </label>
          </div>
          <div class="mt-3 pt-3 border-t border-slate-100 flex justify-between text-sm">
            <span class="text-slate-500">مجموع متراژ چاپ</span>
            <span class="font-bold text-ink ltr-nums">{{ num(printTotal) }} م²</span>
          </div>
        </section>

        <!-- Table 4: roll counts -->
        <section class="bg-surface rounded-card shadow-soft p-5">
          <div class="flex items-center gap-2 mb-4">
            <span class="w-7 h-7 rounded-lg bg-panel text-white text-xs flex items-center justify-center font-bold">۴</span>
            <h3 class="font-bold text-ink">تعداد رول‌ها</h3>
          </div>
          <div class="space-y-2">
            <label v-for="r in data.rolls" :key="r.product" class="flex items-center justify-between gap-3">
              <span class="text-sm text-slate-600">
                {{ r.product_name }}
                <span class="text-xs text-slate-400 ltr-nums">(اجرت {{ num(r.piece_rate_rial) }})</span>
              </span>
              <input v-model="r.quantity" type="number" step="any"
                class="w-32 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-3 py-1.5 text-left ltr-nums outline-none" />
            </label>
          </div>
          <div class="mt-3 pt-3 border-t border-slate-100 flex justify-between text-sm">
            <span class="text-slate-500">درآمد اجرت (برآورد)</span>
            <span class="font-bold text-accent-600 ltr-nums">{{ num(revenueTotal) }} ریال</span>
          </div>
        </section>
      </div>

      <!-- Sticky action bar -->
      <div class="sticky bottom-4 bg-panel text-white rounded-card shadow-pop p-3 flex items-center justify-between">
        <span class="text-sm text-white/70 px-2">پس از تکمیل، برای تایید مدیرعامل ارسال کنید.</span>
        <div class="flex gap-2">
          <button class="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/20 text-sm" @click="save(false)">ذخیره پیش‌نویس</button>
          <button class="px-5 py-2 rounded-xl bg-accent-500 hover:bg-accent-600 text-sm font-medium" @click="save(true)">ذخیره و ارسال برای تایید</button>
        </div>
      </div>
    </template>
  </div>
</template>
