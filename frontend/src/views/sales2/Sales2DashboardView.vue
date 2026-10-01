<script setup lang="ts">
import { onMounted, ref } from "vue";
import { sales2Api, type KpiMonth, type Summary } from "@/api/sales2";
import Skeleton from "@/components/Skeleton.vue";
import { apiError } from "@/components/crm/formError";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { faDate } from "@/utils/adminFormat";
import { MONTH_NAMES } from "@/utils/jalali";

/**
 * داشبورد فروش ۲ — this month's sales and the money still out. Each tile is
 * a way into the list behind it.
 */
const { money } = useMoney();
const FA = new Intl.NumberFormat("fa-IR");
const s = ref<Summary | null>(null);
const error = ref("");
const k = ref<{ current: KpiMonth; previous: KpiMonth; deals_without_next_action: number } | null>(null);

/** «فروش خوب» (کتاب فروش، فصل ۱۶): beside how much was sold, how well. */
const pct = (v: number | null) => (v == null ? "—" : `${FA.format(v)}٪`);
function delta(cur: number | null, prev: number | null, unit = "٪") {
  if (cur == null || prev == null) return "";
  const d = Math.round((cur - prev) * 10) / 10;
  return d === 0 ? "بدون تغییر" : `${d > 0 ? "▲" : "▼"} ${FA.format(Math.abs(d))}${unit} نسبت به ماه قبل`;
}

onMounted(async () => {
  try {
    await loadMoneySettings();
    [s.value, k.value] = await Promise.all([sales2Api.summary(), sales2Api.kpis()]);
  } catch (e) {
    error.value = apiError(e);
  }
});
</script>

<template>
  <div class="space-y-4">
    <div class="bg-amber-50 text-amber-800 text-sm rounded-xl px-4 py-3">
      فروش ۲ در حال ساخت است و فعلاً فقط برای مدیر سامانه نمایش داده می‌شود. اسناد این بخش جدا از فاکتورهای آرپا و فروش ماهانه‌ی فعلی نگه داشته می‌شوند.
    </div>

    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">{{ error }}</p>
    <div v-if="!s && !error" class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
      <Skeleton v-for="i in 8" :key="i" class="h-24 rounded-card" />
    </div>

    <template v-if="s">
      <div class="flex flex-wrap gap-2">
        <router-link :to="{ name: 'sales2-document-new', params: { kind: 'proforma' } }" class="rounded-xl px-4 py-2 text-sm bg-slate-100 text-slate-700">+ پیش‌فاکتور</router-link>
        <router-link :to="{ name: 'sales2-document-new', params: { kind: 'invoice' } }" class="rounded-xl px-4 py-2 text-sm bg-panel text-white">+ فاکتور فروش</router-link>
        <router-link :to="{ name: 'sales2-receipts', query: { new: 1 } }" class="rounded-xl px-4 py-2 text-sm bg-slate-100 text-slate-700">+ دریافت</router-link>
      </div>

      <h2 class="text-sm font-bold text-ink">{{ MONTH_NAMES[s.month.jalali_month - 1] }} {{ FA.format(s.month.jalali_year).replace(/٬/g, "") }}</h2>
      <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <router-link :to="{ name: 'sales2-sales-list' }" class="bg-surface rounded-card shadow-soft p-4 block">
          <p class="text-xs text-slate-500">فروش خالص ماه</p>
          <p class="text-xl font-bold text-ink mt-1">{{ money(s.month_invoiced_rial) }}</p>
          <p class="text-xs text-slate-400 mt-1">{{ FA.format(s.month_invoice_count) }} فاکتور</p>
        </router-link>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-xs text-slate-500">سود ناخالص ماه</p>
          <p class="text-xl font-bold text-emerald-600 mt-1">{{ money(s.month_profit_rial) }}</p>
          <p v-if="s.loss_overrides" class="text-xs text-amber-600 mt-1">{{ FA.format(s.loss_overrides) }} سند با عبور از کنترل</p>
        </div>
        <router-link :to="{ name: 'sales2-returns' }" class="bg-surface rounded-card shadow-soft p-4 block">
          <p class="text-xs text-slate-500">مرجوعی ماه</p>
          <p class="text-xl font-bold text-ink mt-1">{{ money(s.month_returns_rial) }}</p>
        </router-link>
        <router-link :to="{ name: 'sales2-receipts' }" class="bg-surface rounded-card shadow-soft p-4 block">
          <p class="text-xs text-slate-500">دریافتی ماه</p>
          <p class="text-xl font-bold text-ink mt-1">{{ money(s.month_received_rial) }}</p>
        </router-link>
      </div>

      <template v-if="k">
        <h2 class="text-sm font-bold text-ink pt-2">کیفیت فروش ماه <span class="text-xs font-normal text-slate-400">— فروش زیاد لزوماً فروش خوب نیست</span></h2>
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-500">حاشیه سود ناخالص</p>
            <p class="text-xl font-bold mt-1" :class="k.current.margin_pct != null && k.current.margin_pct < 5 ? 'text-red-600' : 'text-ink'">{{ pct(k.current.margin_pct) }}</p>
            <p class="text-[11px] text-slate-400 mt-1">{{ delta(k.current.margin_pct, k.previous.margin_pct) }}</p>
          </div>
          <router-link :to="{ name: 'sales2-proformas' }" class="bg-surface rounded-card shadow-soft p-4 block">
            <p class="text-xs text-slate-500">تبدیل پیش‌فاکتور به فاکتور</p>
            <p class="text-xl font-bold text-ink mt-1">{{ pct(k.current.conversion_pct) }}</p>
            <p class="text-[11px] text-slate-400 mt-1">
              {{ FA.format(k.current.converted) }} از {{ FA.format(k.current.proformas) }}
              <template v-if="k.current.avg_conversion_days != null"> · میانگین {{ FA.format(k.current.avg_conversion_days) }} روز</template>
            </p>
          </router-link>
          <router-link :to="{ name: 'sales2-receivables' }" class="bg-surface rounded-card shadow-soft p-4 block">
            <p class="text-xs text-slate-500">وصول در سررسید</p>
            <p class="text-xl font-bold mt-1" :class="(k.current.on_time_pct ?? 100) < 70 ? 'text-amber-600' : 'text-ink'">{{ pct(k.current.on_time_pct) }}</p>
            <p class="text-[11px] text-slate-400 mt-1">از {{ money(k.current.due_rial) }} سررسید این ماه</p>
          </router-link>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-500">خرید مجدد</p>
            <p class="text-xl font-bold text-ink mt-1">{{ pct(k.current.repeat_pct) }}</p>
            <p class="text-[11px] text-slate-400 mt-1">از مشتریان ماه، در ۶ ماه قبل هم خریده‌اند</p>
          </div>
          <router-link :to="{ name: 'sales2-grades' }" class="bg-surface rounded-card shadow-soft p-4 block">
            <p class="text-xs text-slate-500">مشتری فعال سودآور</p>
            <p class="text-xl font-bold text-ink mt-1">{{ FA.format(k.current.profitable_customers) }} <span class="text-sm font-normal text-slate-400">از {{ FA.format(k.current.active_customers) }}</span></p>
          </router-link>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-500">مشتری جدید فعال</p>
            <p class="text-xl font-bold text-ink mt-1">{{ FA.format(k.current.new_customers) }}</p>
            <p class="text-[11px] text-slate-400 mt-1">ماه قبل: {{ FA.format(k.previous.new_customers) }}</p>
          </div>
          <router-link :to="{ name: 'crm-today' }" class="bg-surface rounded-card shadow-soft p-4 block">
            <p class="text-xs text-slate-500">فرصت بدون اقدام بعدی (CRM)</p>
            <p class="text-xl font-bold mt-1" :class="k.deals_without_next_action ? 'text-red-600' : 'text-emerald-600'">{{ FA.format(k.deals_without_next_action) }}</p>
            <p class="text-[11px] text-slate-400 mt-1">هشدار مستقیم ضعف پیگیری</p>
          </router-link>
        </div>
      </template>

      <h2 class="text-sm font-bold text-ink pt-2">مطالبات و کارهای باز</h2>
      <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <router-link :to="{ name: 'sales2-customers' }" class="bg-surface rounded-card shadow-soft p-4 block">
          <p class="text-xs text-slate-500">کل مطالبات</p>
          <p class="text-xl font-bold text-ink mt-1">{{ money(s.receivable_rial) }}</p>
          <p class="text-xs mt-1" :class="Number(s.overdue_rial) > 0 ? 'text-red-600' : 'text-slate-400'">سررسیدگذشته: {{ money(s.overdue_rial) }}</p>
        </router-link>
        <router-link :to="{ name: 'sales2-receipts' }" class="bg-surface rounded-card shadow-soft p-4 block">
          <p class="text-xs text-slate-500">چک‌های وصول‌نشده</p>
          <p class="text-xl font-bold text-ink mt-1">{{ money(s.cheques_pending_rial) }}</p>
        </router-link>
        <router-link :to="{ name: 'sales2-proformas' }" class="bg-surface rounded-card shadow-soft p-4 block">
          <p class="text-xs text-slate-500">پیش‌فاکتور معتبر باز</p>
          <p class="text-xl font-bold text-ink mt-1">{{ FA.format(s.open_proformas) }}</p>
          <p class="text-xs text-slate-400 mt-1">{{ FA.format(s.drafts) }} پیش‌نویس</p>
        </router-link>
        <router-link :to="{ name: 'sales2-deliveries' }" class="bg-surface rounded-card shadow-soft p-4 block">
          <p class="text-xs text-slate-500">فاکتور تحویل‌نشده (۹۰ روز)</p>
          <p class="text-xl font-bold text-ink mt-1">{{ FA.format(s.undelivered_invoices) }}</p>
        </router-link>
      </div>

      <div class="grid lg:grid-cols-2 gap-4">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <h3 class="text-sm font-bold text-ink mb-2">چک‌های سررسید هفته‌ی پیش رو</h3>
          <p v-if="!s.cheques_due_week.length" class="text-xs text-slate-400">چکی سررسید نمی‌شود.</p>
          <ul class="divide-y divide-slate-100 text-sm">
            <li v-for="c in s.cheques_due_week" :key="c.id" class="py-2 flex justify-between gap-2">
              <span>{{ c.customer_name }} <span class="text-xs text-slate-400 ltr-nums">چک {{ c.cheque_no }}</span></span>
              <span class="text-xs text-slate-500">{{ faDate(c.cheque_due_date) }} · <b class="ltr-nums">{{ money(c.amount_rial) }}</b></span>
            </li>
          </ul>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <h3 class="text-sm font-bold text-ink mb-2">مشتریان برتر ماه</h3>
          <p v-if="!s.top_customers.length" class="text-xs text-slate-400">هنوز فاکتوری در این ماه صادر نشده.</p>
          <ul class="divide-y divide-slate-100 text-sm">
            <li v-for="t in s.top_customers" :key="t.customer" class="py-2 flex justify-between gap-2">
              <router-link :to="{ name: 'sales2-customer', params: { id: t.customer } }" class="text-ink hover:text-sky-600">{{ t.name }}</router-link>
              <b class="ltr-nums">{{ money(t.net_rial) }}</b>
            </li>
          </ul>
        </div>
      </div>
    </template>
  </div>
</template>
