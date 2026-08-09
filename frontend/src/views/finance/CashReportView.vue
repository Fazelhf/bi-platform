<script setup lang="ts">
/**
 * گزارش نقدینگی — the finance colleague's weekly sheet, computed.
 *
 * Same shape he already reads: واریز above, برداشت below, a row per day and a
 * total per category. What his sheet cannot show is added at the top — the
 * running balance, and a plain warning when the period burned cash.
 */
import { computed, onMounted, ref, watch } from "vue";
import { financeApi, type CashReport } from "@/api/finance";
import { salesApi } from "@/api/sales";
import { currentPeriodId, type Period } from "@/types";
import { toast } from "@/composables/useUi";
import { loadMoneySettings, setMoneySettings, useMoney } from "@/composables/useMoney";
import { num } from "@/utils/format";
import SeriesChart from "@/components/charts/SeriesChart.vue";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";
import AccountsPanel from "@/views/finance/AccountsPanel.vue";
// تسهیلات و قرض are not a section of their own and not even a tab: they are
// part of the cash picture, so the ledger that moved the balance and the
// balances themselves are read on one continuous page.
import CreditLinesView from "@/views/finance/CreditLinesView.vue";
import SectionBoard from "@/components/boards/SectionBoard.vue";
import { useAuthStore } from "@/stores/auth";

const periods = ref<Period[]>([]);
const selected = ref<number | null>(null);
const report = ref<CashReport | null>(null);
const loading = ref(true);
const error = ref("");

const n = (v: string | null | undefined) => Number(v ?? 0);

const auth = useAuthStore();

/**
 * Who gets the working sheet as well as the position.
 *
 * The day-by-day grids, the account list and the facility list are the finance
 * colleague's instrument: he keys them, reconciles them and answers for them.
 * The CEO opens this page for four figures — how much came in, how much went
 * out, where it ended and what is owed — and eight thousand pixels of daily
 * detail underneath meant scrolling past the answer to reach nothing.
 */
const isTreasury = computed(() => auth.department === "finance");

const { money, unitLabel, unit } = useMoney();

/** Money is written with the unit spelled out, so a figure is never ambiguous. */
const rial = (v: number | string | null | undefined) => money(v, false);

async function switchUnit(next: "rial" | "toman") {
  try {
    setMoneySettings(await financeApi.saveSettings({ unit: next }));
    toast.success(`ارقام از این پس به ${next === "toman" ? "تومان" : "ریال"} نمایش داده می‌شود.`);
  } catch {
    toast.error("واحد تغییر نکرد — فقط واحد مالی می‌تواند آن را عوض کند.");
  }
}

async function load() {
  if (!selected.value) return;
  loading.value = true;
  error.value = "";
  try {
    report.value = await financeApi.report(selected.value);
  } catch (e: any) {
    report.value = null;
    error.value = e?.response?.status === 403
      ? "بخش مالی برای شما قابل مشاهده نیست."
      : e?.response?.data?.detail || "گزارش ساخته نشد.";
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  try {
    await loadMoneySettings();
    periods.value = await salesApi.periods();
    selected.value = currentPeriodId(periods.value);
    await load();
  } catch {
    error.value = "بارگذاری دوره‌ها ناموفق بود.";
    loading.value = false;
  }
});
watch(selected, load);

const closingTone = computed(() => {
  const r = report.value;
  if (!r) return "text-ink";
  const closing = n(r.balance.closing);
  if (closing < 0) return "text-red-600";
  if (n(r.balance.low_threshold) && closing < n(r.balance.low_threshold)) {
    return "text-amber-600";
  }
  return "text-green-600";
});

const netTone = (v: string) => (n(v) < 0 ? "text-red-500" : n(v) > 0 ? "text-green-600" : "text-slate-400");

/** Only days that actually moved money — a month of empty rows reads as noise. */
const activeDays = computed(() =>
  (report.value?.days ?? []).filter((d) => n(d.total_in) || n(d.total_out)),
);

const trendCategories = computed(() => activeDays.value.map((d) => d.label));
const trendSeries = computed(() => [
  { name: "واریز", values: activeDays.value.map((d) => n(d.total_in)) },
  { name: "برداشت", values: activeDays.value.map((d) => n(d.total_out)) },
]);
const balanceSeries = computed(() => [
  { name: "موجودی", values: activeDays.value.map((d) => n(d.balance)) },
]);
</script>

<template>
  <div class="space-y-4">
    <section class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="font-bold text-ink">نقدینگی</h1>
        <p v-if="report" class="text-xs text-slate-400 mt-0.5">
          {{ report.title }} · همه ارقام به <span class="font-medium">{{ unitLabel }}</span>
        </p>
      </div>
      <div class="flex items-end gap-3">
        <!-- Stored in Rial either way; this only changes what is shown. -->
        <div>
          <span class="text-[11px] text-slate-400 block mb-1">واحد</span>
          <div class="flex bg-slate-100 rounded-xl p-0.5">
            <button
              v-for="u in ([['rial', 'ریال'], ['toman', 'تومان']] as const)"
              :key="u[0]"
              class="px-3 py-1 text-xs rounded-lg transition"
              :class="unit === u[0] ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-500'"
              @click="switchUnit(u[0])"
            >{{ u[1] }}</button>
          </div>
        </div>
        <label class="block">
          <span class="text-[11px] text-slate-400">دوره</span>
          <select
            v-model.number="selected"
            class="mt-1 border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface"
          >
            <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
          </select>
        </label>
      </div>
    </section>

    <p v-if="error" class="bg-red-50 text-red-600 rounded-card p-4 text-sm">{{ error }}</p>
    <DashboardSkeleton v-else-if="loading && !report" />

    <template v-else-if="report">
      <!-- Warnings first: the sample week netted −۳٫۸ میلیارد and his sheet
           left that subtraction to the reader. -->
      <div
        v-for="(w, i) in report.warnings" :key="i"
        class="rounded-card p-3 text-sm flex items-center gap-2"
        :class="w.level === 'danger' ? 'bg-red-50 text-red-700' : 'bg-amber-50 text-amber-700'"
      >
        <span class="font-medium">{{ w.text }}</span>
        <span class="ltr-nums">{{ rial(n(w.amount)) }}</span>
      </div>

      <!-- Position -->
      <div class="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">موجودی ابتدای دوره</p>
          <p class="text-lg font-bold text-slate-500 ltr-nums">{{ rial(n(report.balance.opening)) }}</p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">جمع واریز</p>
          <p class="text-lg font-bold text-green-600 ltr-nums">{{ rial(n(report.totals.total_in)) }}</p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">جمع برداشت</p>
          <p class="text-lg font-bold text-red-500 ltr-nums">{{ rial(n(report.totals.total_out)) }}</p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">خالص دوره</p>
          <p class="text-lg font-bold ltr-nums" :class="netTone(report.totals.net)">
            {{ rial(n(report.totals.net)) }}
          </p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">موجودی پایان دوره</p>
          <p class="text-lg font-bold ltr-nums" :class="closingTone">
            {{ rial(n(report.balance.closing)) }}
          </p>
        </div>
      </div>



      <!-- Credit position -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">مانده تسهیلات (بدهی شرکت)</p>
          <p class="text-lg font-bold text-red-500 ltr-nums">
            {{ rial(n(report.credit_summary.owed_by_company)) }}
          </p>
          <p class="text-[11px] text-slate-400 mt-1">
            {{ num(report.credit_summary.lines.facility.length) }} فقره
          </p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">قرض‌های پرداختی (طلب شرکت)</p>
          <p class="text-lg font-bold text-green-600 ltr-nums">
            {{ rial(n(report.credit_summary.owed_to_company)) }}
          </p>
          <p class="text-[11px] text-slate-400 mt-1">
            {{ num(report.credit_summary.lines.lending.length) }} فقره
          </p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">خالص جاری شرکا</p>
          <p class="text-lg font-bold ltr-nums" :class="netTone(report.credit_summary.partner_net)">
            {{ rial(n(report.credit_summary.partner_net)) }}
          </p>
          <p class="text-[11px] text-slate-400 mt-1">
            {{ num(report.credit_summary.lines.partner.length) }} شریک
          </p>
        </div>
      </div>

      <div class="grid lg:grid-cols-2 gap-4">
        <SeriesChart
          v-if="activeDays.length"
          title="واریز و برداشت روزانه"
          :categories="trendCategories"
          :series="trendSeries"
        />
        <SeriesChart
          v-if="activeDays.length"
          title="روند موجودی"
          :categories="trendCategories"
          :series="balanceSeries"
        />
      </div>


      <!-- The grid, exactly as he reads it -->
      <template v-if="isTreasury">
      <section
        v-for="block in ([
          { key: 'in', title: 'واریز', cats: report.categories.in, tone: 'text-green-600' },
          { key: 'out', title: 'برداشت', cats: report.categories.out, tone: 'text-red-500' },
        ] as const)"
        :key="block.key"
        class="bg-surface rounded-card shadow-soft overflow-hidden"
      >
        <h2 class="font-semibold p-4 pb-2" :class="block.tone">{{ block.title }}</h2>
        <div v-if="!activeDays.length" class="p-6 text-center text-sm text-slate-400">
          در این دوره حرکتی ثبت نشده است.
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="bg-slate-50/60 text-[11px] text-slate-400">
              <tr>
                <th class="text-right font-medium px-3 py-2 whitespace-nowrap">تاریخ</th>
                <th
                  v-for="c in block.cats" :key="c.id"
                  class="text-left font-medium px-3 py-2 whitespace-nowrap"
                >{{ c.name }}</th>
                <th class="text-left font-medium px-3 py-2">مجموع</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="d in activeDays" :key="d.period_id"
                class="border-t border-slate-50 hover:bg-slate-50/60"
              >
                <td class="px-3 py-1.5 text-ink whitespace-nowrap">{{ d.label }}</td>
                <td
                  v-for="c in block.cats" :key="c.id"
                  class="px-3 py-1.5 text-left ltr-nums"
                  :class="n(d[block.key][String(c.id)]) ? 'text-ink' : 'text-slate-300'"
                >{{ n(d[block.key][String(c.id)]) ? rial(n(d[block.key][String(c.id)])) : "—" }}</td>
                <td class="px-3 py-1.5 text-left ltr-nums font-medium">
                  {{ rial(n(block.key === "in" ? d.total_in : d.total_out)) }}
                </td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="border-t-2 border-slate-100 bg-slate-50/40 font-semibold">
                <td class="px-3 py-2 text-ink">مجموع</td>
                <td
                  v-for="c in block.cats" :key="c.id"
                  class="px-3 py-2 text-left ltr-nums"
                >{{ rial(n(report.totals[block.key][String(c.id)])) }}</td>
                <td class="px-3 py-2 text-left ltr-nums">
                  {{ rial(n(block.key === "in" ? report.totals.total_in : report.totals.total_out)) }}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>
      </template>

      <!-- Running balance per day -->
      <section v-if="isTreasury && activeDays.length" class="bg-surface rounded-card shadow-soft overflow-hidden">
        <h2 class="font-semibold text-ink p-4 pb-2">موجودی روزبه‌روز</h2>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="bg-slate-50/60 text-[11px] text-slate-400">
              <tr>
                <th class="text-right font-medium px-3 py-2">تاریخ</th>
                <th class="text-left font-medium px-3 py-2">واریز</th>
                <th class="text-left font-medium px-3 py-2">برداشت</th>
                <th class="text-left font-medium px-3 py-2">خالص روز</th>
                <th class="text-left font-medium px-3 py-2">موجودی پایان روز</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="d in activeDays" :key="d.period_id"
                class="border-t border-slate-50"
              >
                <td class="px-3 py-1.5 text-ink">{{ d.label }}</td>
                <td class="px-3 py-1.5 text-left ltr-nums text-green-600">{{ rial(n(d.total_in)) }}</td>
                <td class="px-3 py-1.5 text-left ltr-nums text-red-500">{{ rial(n(d.total_out)) }}</td>
                <td class="px-3 py-1.5 text-left ltr-nums" :class="netTone(d.net)">{{ rial(n(d.net)) }}</td>
                <td
                  class="px-3 py-1.5 text-left ltr-nums font-medium"
                  :class="n(d.balance) < 0 ? 'text-red-600' : 'text-ink'"
                >{{ rial(n(d.balance)) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- The accounts every figure above is attributed to. -->
      <AccountsPanel v-if="isTreasury" @changed="load" />

      <!-- The facilities, loans and partner accounts behind the balances
           above — same page, because they are the same question. -->
      <CreditLinesView v-if="isTreasury" embedded />
    </template>
      <!-- گزارش این بخش، روی همین صفحه: داشبورد و گزارش یک صفحه‌اند. -->
    <SectionBoard section="finance" :period="selected" />
</div>
</template>
