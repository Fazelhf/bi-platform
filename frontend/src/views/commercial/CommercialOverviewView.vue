<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { foreignApi, type CommercialOverview } from "@/api/commercialForeign";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import SeriesChart from "@/components/charts/SeriesChart.vue";
import Skeleton from "@/components/Skeleton.vue";

/**
 * نمای کلی بازرگانی — the CEO's whole view of the section.
 *
 * Four questions, in the order someone asks them: how much are we spending,
 * where is it stuck, what is bleeding, and how much is actually moving.
 *
 * Deliberately no table of PI numbers and no links into individual files. The
 * moment this page can be drilled into it has become the working page again,
 * which is the thing it exists to replace.
 */
const { exact, toUnit, unitLabel } = useMoney();

const data = ref<CommercialOverview | null>(null);
const loading = ref(true);
const error = ref("");

const FA = new Intl.NumberFormat("fa-IR");

onMounted(async () => {
  await loadMoneySettings();
  try {
    data.value = await foreignApi.overview();
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
});

const spendChart = computed(() => {
  const rows = data.value?.money.monthly_spend ?? [];
  return {
    categories: rows.map((r) => r.label),
    series: [{
      name: `خرید داخلی (${unitLabel.value})`,
      values: rows.map((r) => (r.has_data ? toUnit(r.amount_rial) : null)),
    }],
  };
});

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "";
  const sign = v > 0 ? "▲" : v < 0 ? "▼" : "";
  return `${sign} ${FA.format(Math.abs(Number(v.toFixed(1))))}٪`;
}
</script>

<template>
  <div class="space-y-5">
    <div v-if="loading" class="space-y-3">
      <Skeleton v-for="i in 4" :key="i" class="h-32 rounded-card" />
    </div>

    <p v-else-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">
      {{ error }}
    </p>

    <template v-else-if="data">
      <!-- ۱. پول -->
      <section>
        <h2 class="text-sm font-bold text-slate-500 mb-2 px-1">
          پول — چقدر خریدیم
        </h2>
        <div class="grid md:grid-cols-3 gap-3">
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">خرید داخلی — {{ data.month.label }}</p>
            <p class="text-2xl font-bold text-ink ltr-nums mt-1">
              {{ exact(data.money.domestic_month_rial, true) }}
            </p>
            <p class="text-xs mt-1"
               :class="(data.money.domestic_change_pct ?? 0) > 0
                 ? 'text-red-500' : 'text-emerald-600'">
              {{ pct(data.money.domestic_change_pct) }}
              <span class="text-slate-400">نسبت به ماه قبل ·
                {{ num(data.money.domestic_order_count) }} سفارش</span>
            </p>
          </div>

          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">ارزش واردات</p>
            <div class="mt-1 space-y-0.5">
              <p
                v-for="c in data.money.foreign_by_currency" :key="c.currency"
                class="text-2xl font-bold text-ink ltr-nums"
              >
                {{ FA.format(Number(c.amount)) }}
                <span class="text-sm text-slate-400">{{ c.currency }}</span>
              </p>
              <p v-if="!data.money.foreign_by_currency.length" class="text-slate-400">—</p>
            </div>
            <p class="text-xs text-slate-400 mt-1">مجموع پرونده‌های باز و بسته</p>
          </div>

          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">بدهی به فروشنده خارجی</p>
            <p class="text-2xl font-bold text-ink ltr-nums mt-1">
              {{ FA.format(Number(data.money.foreign_outstanding)) }}
              <span class="text-sm text-slate-400">USD</span>
            </p>
            <p class="text-xs text-red-500 mt-1 ltr-nums">
              + {{ FA.format(Number(data.money.foreign_interest)) }} سود دیرکرد
            </p>
          </div>
        </div>

        <div
          v-if="spendChart.categories.length"
          class="bg-surface rounded-card shadow-soft p-4 mt-3"
        >
          <SeriesChart
            title="روند خرید داخلی"
            :categories="spendChart.categories"
            :series="spendChart.series"
            :height="200"
          />
        </div>
      </section>

      <!-- ۲. گیر -->
      <section>
        <h2 class="text-sm font-bold text-slate-500 mb-2 px-1">
          گیر — کجا خوابیده
        </h2>
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">در صف تخصیص ارز</p>
            <p class="text-2xl font-bold text-ink ltr-nums mt-1">
              {{ num(data.stuck.in_queue) }}
            </p>
            <p class="text-xs text-slate-400 ltr-nums">
              {{ FA.format(Number(data.stuck.queue_amount)) }} USD
            </p>
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">میانگین انتظار</p>
            <p class="text-2xl font-bold ltr-nums mt-1"
               :class="data.stuck.queue_avg_days > 100 ? 'text-amber-600' : 'text-ink'">
              {{ FA.format(data.stuck.queue_avg_days) }} روز
            </p>
            <p class="text-xs text-slate-400 ltr-nums">
              بیشترین {{ FA.format(data.stuck.queue_max_days) }} روز
            </p>
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">فراتر از مهلت بانک</p>
            <p class="text-2xl font-bold text-amber-600 ltr-nums mt-1">
              {{ num(data.stuck.queue_overdue) }}
            </p>
            <p class="text-xs text-slate-400">پرونده</p>
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">پرونده بدون اقدام</p>
            <p class="text-2xl font-bold ltr-nums mt-1"
               :class="data.stuck.idle_files ? 'text-red-600' : 'text-ink'">
              {{ num(data.stuck.idle_files) }}
            </p>
            <p class="text-xs text-slate-400 ltr-nums">
              از {{ num(data.stuck.live_files) }} پرونده فعال
            </p>
          </div>
        </div>

        <div
          v-if="data.stuck.by_bank.length"
          class="bg-surface rounded-card shadow-soft p-4 mt-3"
        >
          <p class="text-xs text-slate-400 mb-2">
            بیشترین پول گیرکرده، به تفکیک بانک — سهم بر اساس مبلغ
          </p>
          <div class="space-y-2">
            <div v-for="b in data.stuck.by_bank" :key="b.id ?? 'none'">
              <div class="flex items-baseline justify-between text-sm">
                <span class="text-ink">{{ b.name }}</span>
                <span class="ltr-nums text-slate-500">
                  {{ FA.format(Number(b.amount)) }} USD ·
                  میانگین {{ FA.format(b.avg_days) }} روز
                </span>
              </div>
              <div class="h-2 rounded-full bg-slate-100 mt-1 overflow-hidden">
                <div
                  class="h-full rounded-full"
                  :style="{ width: `${b.share_pct}%`, background: b.color || '#94a3b8' }"
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ۳. خون‌ریزی -->
      <section>
        <h2 class="text-sm font-bold text-slate-500 mb-2 px-1">
          خون‌ریزی — چقدر دارد می‌سوزد
        </h2>
        <div class="grid md:grid-cols-2 gap-3">
          <div
            class="rounded-card p-4 border"
            :class="Number(data.bleeding.daily_rial)
              ? 'bg-red-50 border-red-100' : 'bg-surface border-transparent shadow-soft'"
          >
            <p class="text-xs" :class="Number(data.bleeding.daily_rial) ? 'text-red-700' : 'text-slate-400'">
              هزینه هر روز تأخیر در گمرک
            </p>
            <p class="text-2xl font-bold ltr-nums mt-1"
               :class="Number(data.bleeding.daily_rial) ? 'text-red-700' : 'text-ink'">
              {{ exact(data.bleeding.daily_rial, true) }}
            </p>
            <p class="text-xs mt-1 ltr-nums"
               :class="Number(data.bleeding.daily_rial) ? 'text-red-600' : 'text-slate-400'">
              {{ num(data.bleeding.containers) }} کانتینر در گمرک ·
              جمع تاکنون {{ exact(data.bleeding.accrued_rial, true) }}
            </p>
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">سود دیرکرد پرداخت به فروشنده</p>
            <p class="text-2xl font-bold text-red-600 ltr-nums mt-1">
              {{ FA.format(Number(data.bleeding.interest)) }}
              <span class="text-sm text-slate-400">USD</span>
            </p>
            <p class="text-xs text-slate-400 ltr-nums mt-1">
              {{ num(data.bleeding.overdue_payments) }} فاکتور از سررسید گذشته
            </p>
          </div>
        </div>
      </section>

      <!-- ۴. تناژ -->
      <section>
        <h2 class="text-sm font-bold text-slate-500 mb-2 px-1">
          تناژ — چقدر کالا در راه است
        </h2>
        <div class="grid grid-cols-3 gap-3">
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">در مسیر</p>
            <p class="text-2xl font-bold text-ink ltr-nums mt-1">
              {{ num(data.tonnage.in_transit) }} <span class="text-sm">تن</span>
            </p>
            <p class="text-xs text-slate-400 ltr-nums">
              {{ num(data.tonnage.in_transit_count) }} کانتینر
            </p>
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">در گمرک</p>
            <p class="text-2xl font-bold ltr-nums mt-1"
               :class="Number(data.tonnage.at_customs) ? 'text-amber-600' : 'text-ink'">
              {{ num(data.tonnage.at_customs) }} <span class="text-sm">تن</span>
            </p>
            <p class="text-xs text-slate-400 ltr-nums">
              {{ num(data.tonnage.at_customs_count) }} کانتینر
            </p>
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">ترخیص‌شده</p>
            <p class="text-2xl font-bold text-emerald-600 ltr-nums mt-1">
              {{ num(data.tonnage.cleared_ytd) }} <span class="text-sm">تن</span>
            </p>
            <p class="text-xs text-slate-400">تحویل کارخانه</p>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
