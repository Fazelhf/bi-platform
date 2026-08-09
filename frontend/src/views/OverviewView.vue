<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { salesApi } from "@/api/sales";
import { executiveApi, type TrendMonth } from "@/api/executive";
import { defaultPeriodId } from "@/types";
import type { ExecutiveOverview, KpiResult, Period } from "@/types";
import { kpiValue, num, pct, rial } from "@/utils/format";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";
import ExportActions from "@/components/ExportActions.vue";
import SectionBoard from "@/components/boards/SectionBoard.vue";

/**
 * The CEO's one screen.
 *
 * It used to be a wall of bare figures: a big total, twelve KPI values and
 * four financial numbers, none of them next to anything to judge them by. A
 * number on its own cannot answer "is this good?", which is the only question
 * this page exists to answer — so every headline now carries the two things
 * that make it readable: how it moved since last month, and how it stands
 * against the plan. The year's shape is drawn once at the top, and anything
 * off-plan is called out rather than left to be spotted.
 */
const periods = ref<Period[]>([]);
const selectedPeriod = ref<number | null>(null);
const data = ref<ExecutiveOverview | null>(null);
const trend = ref<TrendMonth[]>([]);
const loading = ref(false);

function pick(kpis: KpiResult[] | undefined, codes: string[]) {
  return codes.map((c) => kpis?.find((k) => k.kpi_code === c)).filter((k): k is KpiResult => !!k);
}

async function load() {
  if (!selectedPeriod.value) return;
  loading.value = true;
  try {
    const [ov, tr] = await Promise.all([
      executiveApi.overview(selectedPeriod.value),
      executiveApi.trend(),
    ]);
    data.value = ov;
    trend.value = tr.months;
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  periods.value = await salesApi.periods();
  selectedPeriod.value = defaultPeriodId(periods.value);
  await load();
});
watch(selectedPeriod, load);

// ---- context: this month against the last, and against plan ---------------
const here = computed(() => trend.value.find((m) => m.period === selectedPeriod.value) ?? null);
const previous = computed(() => {
  const i = trend.value.findIndex((m) => m.period === selectedPeriod.value);
  return i > 0 ? trend.value[i - 1] : null;
});

/** Percent change, or null when there is nothing to compare against. */
function delta(now: number | undefined, before: number | undefined): number | null {
  if (now === undefined || before === undefined || !before) return null;
  return ((now - before) / Math.abs(before)) * 100;
}

/**
 * How to say a change out loud.
 *
 * A percentage stops meaning anything once the base is tiny: growing from 55
 * million to 188 billion is "+۳۴۰٬۲۸۲٪", which reads as a glitch rather than
 * as good news. Past ten-fold, a multiple is the honest phrasing.
 */
function deltaText(d: number | null): string {
  if (d === null) return "";
  const abs = Math.abs(d);
  if (abs >= 900) return `${num(Math.round(abs / 100))} برابر`;
  return pct(abs);
}

const revenueDelta = computed(() => delta(here.value?.total, previous.value?.total));
const profitDelta = computed(() => delta(here.value?.profit, previous.value?.profit));

const achievement = computed(() => here.value?.achievement ?? 0);
const margin = computed(() => {
  const t = here.value?.total ?? 0;
  return t ? ((here.value?.profit ?? 0) / t) * 100 : 0;
});

/** Only months that have been reported — a flat zero tail is noise, not data. */
const reported = computed(() => trend.value.filter((m) => m.total > 0 || m.target > 0));

// ---- the four domains, each with its own movement -------------------------
const channels = computed(() => {
  const d = data.value;
  if (!d) return [];
  return [
    {
      title: "فروش همکار", color: "#3b6fed", route: "sales-dashboard",
      value: d.combined.sales_team_revenue,
      change: delta(here.value?.channel_team, previous.value?.channel_team),
      kpis: pick(d.sales_team.kpis, ["target_achievement", "profit_margin"]),
    },
    {
      title: "فروش بانکی", color: "#f59e0b", route: "sales-org-dashboard",
      value: d.combined.sales_org_revenue,
      change: delta(here.value?.channel_organizational, previous.value?.channel_organizational),
      kpis: pick(d.sales_org.kpis, ["profit_margin", "avg_invoice_value"]),
    },
    {
      title: "فروش B2B", color: "#ec4899", route: "sales-b2b-dashboard",
      value: d.combined.sales_b2b_revenue,
      change: delta(here.value?.channel_b2b, previous.value?.channel_b2b),
      kpis: pick(d.sales_b2b.kpis, ["target_achievement", "collection_rate"]),
    },
  ];
});

const productionKpis = computed(() =>
  pick(data.value?.production.kpis, ["prod_productivity", "waste_rate", "financial_return"]),
);

/** Share of the month's sales, for the mix bar under the hero. */
function share(v: number): number {
  const total = data.value?.combined.total_sales_revenue ?? 0;
  return total ? (v / total) * 100 : 0;
}

// ---- what needs attention -------------------------------------------------
const alerts = computed(() => {
  const out: { text: string; tone: "bad" | "warn" }[] = [];
  const d = data.value;
  if (!d) return out;

  if (here.value?.target && achievement.value < 100) {
    out.push({
      text: `فروش ماه ${pct(achievement.value)} تارگت است — ${rial((here.value.target ?? 0) - (here.value.total ?? 0))} عقب‌تر از برنامه`,
      tone: achievement.value < 70 ? "bad" : "warn",
    });
  }
  if (revenueDelta.value !== null && revenueDelta.value < 0) {
    out.push({ text: `فروش نسبت به ماه قبل ${deltaText(revenueDelta.value)} کاهش داشته`, tone: "warn" });
  }
  if (!d.sales_completeness.complete) {
    out.push({
      text: `داده فروش کامل تایید نشده (${num(d.sales_completeness.approved)} از ${num(d.sales_completeness.total)})`,
      tone: "warn",
    });
  }
  if (!d.production.completeness.complete) {
    out.push({
      text: `داده تولید کامل تایید نشده (${num(d.production.completeness.approved)} از ${num(d.production.completeness.total)})`,
      tone: "warn",
    });
  }
  if (d.combined.production_margin < 0) {
    out.push({ text: `حاشیه تولید منفی است (${rial(d.combined.production_margin)})`, tone: "bad" });
  }
  return out;
});

const card = "bg-surface rounded-card shadow-soft";
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between flex-wrap gap-2">
      <h2 class="text-lg font-bold text-ink">نمای کلی سازمان</h2>
      <div class="flex items-center gap-2">
        <ExportActions :excel="false" />
        <select v-model.number="selectedPeriod" class="bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition">
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <DashboardSkeleton v-if="loading" :cards="4" :charts="0" :rows="4" />

    <template v-else-if="data">
      <!-- ===== Hero: the month, judged ===== -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <!-- Headline + mix -->
        <div class="bg-panel text-white rounded-card shadow-soft p-6 lg:col-span-2">
          <div class="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <p class="text-sm text-white/60 mb-1">فروش کل شرکت — {{ data.period.label }}</p>
              <p class="text-4xl font-extrabold ltr-nums">{{ rial(data.combined.total_sales_revenue) }}</p>
              <p v-if="revenueDelta !== null" class="text-sm mt-1.5 ltr-nums"
                 :class="revenueDelta >= 0 ? 'text-green-300' : 'text-red-300'">
                {{ revenueDelta >= 0 ? "▲" : "▼" }} {{ deltaText(revenueDelta) }}
                <span class="text-white/40">نسبت به {{ previous?.label }}</span>
              </p>
              <p v-else class="text-sm mt-1.5 text-white/40">ماه قبلی برای مقایسه ثبت نشده</p>
            </div>

            <div v-if="here?.target" class="text-left min-w-[190px]">
              <p class="text-xs text-white/60 mb-1">تحقق تارگت</p>
              <p class="text-2xl font-bold ltr-nums"
                 :class="achievement >= 100 ? 'text-green-300' : achievement >= 70 ? 'text-amber-300' : 'text-red-300'">
                {{ pct(achievement) }}
              </p>
              <div class="h-1.5 bg-white/15 rounded-full mt-2 overflow-hidden">
                <div class="h-full rounded-full transition-all"
                     :class="achievement >= 100 ? 'bg-green-400' : achievement >= 70 ? 'bg-amber-400' : 'bg-red-400'"
                     :style="{ width: Math.min(achievement, 100) + '%' }"></div>
              </div>
              <p class="text-[11px] text-white/40 mt-1 ltr-nums">تارگت {{ rial(here.target) }}</p>
            </div>
          </div>

          <!-- Channel mix as one bar, so the split is seen rather than read -->
          <div class="mt-5">
            <div class="flex h-2.5 rounded-full overflow-hidden bg-white/10">
              <div class="bg-[#3b6fed]" :style="{ width: share(data.combined.sales_team_revenue) + '%' }" title="فروش همکار"></div>
              <div class="bg-[#f59e0b]" :style="{ width: share(data.combined.sales_org_revenue) + '%' }" title="فروش بانکی"></div>
              <div class="bg-[#ec4899]" :style="{ width: share(data.combined.sales_b2b_revenue) + '%' }" title="فروش B2B"></div>
            </div>
            <div class="flex flex-wrap gap-x-5 gap-y-1 text-xs text-white/50 mt-2 ltr-nums">
              <span><span class="inline-block w-2 h-2 rounded-full bg-[#3b6fed] ml-1"></span>همکار {{ pct(share(data.combined.sales_team_revenue)) }}</span>
              <span><span class="inline-block w-2 h-2 rounded-full bg-[#f59e0b] ml-1"></span>بانکی {{ pct(share(data.combined.sales_org_revenue)) }}</span>
              <span><span class="inline-block w-2 h-2 rounded-full bg-[#ec4899] ml-1"></span>B2B {{ pct(share(data.combined.sales_b2b_revenue)) }}</span>
            </div>
          </div>
        </div>

        <!-- Profit + attention -->
        <div class="space-y-4">
          <div :class="card" class="p-5">
            <p class="text-xs text-slate-400">سود فروش این ماه</p>
            <p class="text-2xl font-bold text-ink ltr-nums mt-1">{{ rial(here?.profit ?? 0) }}</p>
            <div class="flex items-center gap-3 mt-1.5 text-xs">
              <span class="text-slate-400">حاشیه {{ pct(margin) }}</span>
              <span v-if="profitDelta !== null" class="ltr-nums" :class="profitDelta >= 0 ? 'text-green-600' : 'text-red-500'">
                {{ profitDelta >= 0 ? "▲" : "▼" }} {{ deltaText(profitDelta) }}
              </span>
            </div>
          </div>

          <div :class="card" class="p-5">
            <p class="text-xs text-slate-400 mb-2">نیازمند توجه</p>
            <ul v-if="alerts.length" class="space-y-1.5">
              <li v-for="(a, i) in alerts" :key="i" class="text-xs flex items-start gap-2">
                <span class="mt-1 w-1.5 h-1.5 rounded-full shrink-0" :class="a.tone === 'bad' ? 'bg-red-500' : 'bg-amber-500'"></span>
                <span :class="a.tone === 'bad' ? 'text-red-600' : 'text-amber-600'">{{ a.text }}</span>
              </li>
            </ul>
            <p v-else class="text-xs text-green-600">✓ همه‌چیز مطابق برنامه است</p>
          </div>
        </div>
      </div>

      <!-- ===== The year so far, as figures ===== -->
      <!-- Deliberately a table, not a chart: this page is read at a glance and
           the charts belong on the dashboards each row links to. -->
      <div :class="card" class="overflow-hidden">
        <h3 class="font-bold text-ink px-5 pt-5 pb-3">روند سال — فروش در برابر تارگت</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[640px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-5 py-2.5">ماه</th>
                <th class="text-left font-medium px-3">فروش</th>
                <th class="text-left font-medium px-3">تارگت</th>
                <th class="text-left font-medium px-3">تحقق</th>
                <th class="text-left font-medium px-3">سود</th>
                <th class="text-left font-medium px-5">تغییر</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(m, i) in reported" :key="m.period"
                class="border-t border-slate-100 cursor-pointer transition-colors"
                :class="m.period === selectedPeriod ? 'bg-brand-500/5' : 'hover:bg-slate-50'"
                @click="selectedPeriod = m.period"
              >
                <td class="px-5 py-2.5 text-ink font-medium whitespace-nowrap">{{ m.label }}</td>
                <td class="px-3 text-left ltr-nums text-ink whitespace-nowrap">{{ rial(m.total) }}</td>
                <td class="px-3 text-left ltr-nums text-slate-400 whitespace-nowrap">{{ rial(m.target) }}</td>
                <td class="px-3 text-left ltr-nums font-medium"
                    :class="m.achievement >= 100 ? 'text-green-600' : m.achievement >= 70 ? 'text-amber-600' : 'text-red-500'">
                  {{ m.target ? pct(m.achievement) : "—" }}
                </td>
                <td class="px-3 text-left ltr-nums text-slate-600 whitespace-nowrap">{{ rial(m.profit) }}</td>
                <td class="px-5 text-left ltr-nums whitespace-nowrap">
                  <span v-if="i > 0 && delta(m.total, reported[i - 1].total) !== null"
                        :class="delta(m.total, reported[i - 1].total)! >= 0 ? 'text-green-600' : 'text-red-500'">
                    {{ delta(m.total, reported[i - 1].total)! >= 0 ? "▲" : "▼" }}
                    {{ deltaText(delta(m.total, reported[i - 1].total)) }}
                  </span>
                  <span v-else class="text-slate-300">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!reported.length" class="text-sm text-slate-400 px-5 py-4">هنوز برای هیچ ماهی داده‌ای ثبت نشده است.</p>
      </div>

      <!-- ===== Channels ===== -->
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div v-for="c in channels" :key="c.title" :class="card" class="p-5 hover:shadow-pop transition-shadow duration-200">
          <div class="flex items-center gap-2 mb-3">
            <span class="w-2.5 h-2.5 rounded-full" :style="{ backgroundColor: c.color }"></span>
            <h3 class="font-bold text-ink text-sm">{{ c.title }}</h3>
          </div>
          <p class="text-xl font-bold text-ink ltr-nums">{{ rial(c.value) }}</p>
          <p v-if="c.change !== null" class="text-xs mt-0.5 ltr-nums" :class="c.change >= 0 ? 'text-green-600' : 'text-red-500'">
            {{ c.change >= 0 ? "▲" : "▼" }} {{ deltaText(c.change) }} نسبت به ماه قبل
          </p>
          <div class="space-y-1.5 mt-3 pt-3 border-t border-slate-100">
            <div v-for="k in c.kpis" :key="k.id" class="flex justify-between items-baseline text-xs">
              <span class="text-slate-400">{{ k.kpi_name_fa }}</span>
              <span class="ltr-nums font-semibold text-ink">{{ kpiValue(k.actual, k.unit) }}</span>
            </div>
          </div>
          <RouterLink :to="{ name: c.route }" class="text-xs mt-3 inline-block hover:underline" :style="{ color: c.color }">
            مشاهده داشبورد ←
          </RouterLink>
        </div>

        <!-- Production is not a sales channel; it gets the same card, its own metrics -->
        <div :class="card" class="p-5 hover:shadow-pop transition-shadow duration-200">
          <div class="flex items-center gap-2 mb-3">
            <span class="w-2.5 h-2.5 rounded-full bg-[#10b981]"></span>
            <h3 class="font-bold text-ink text-sm">تولید</h3>
          </div>
          <p class="text-xl font-bold text-ink ltr-nums">{{ rial(data.combined.internal_piece_rate_revenue) }}</p>
          <p class="text-xs text-slate-400 mt-0.5">درآمد اجرت (داخلی)</p>
          <div class="space-y-1.5 mt-3 pt-3 border-t border-slate-100">
            <div v-for="k in productionKpis" :key="k.id" class="flex justify-between items-baseline text-xs">
              <span class="text-slate-400">{{ k.kpi_name_fa }}</span>
              <span class="ltr-nums font-semibold text-ink">{{ kpiValue(k.actual, k.unit) }}</span>
            </div>
          </div>
          <RouterLink :to="{ name: 'production-dashboard' }" class="text-xs mt-3 inline-block text-[#10b981] hover:underline">
            مشاهده داشبورد ←
          </RouterLink>
        </div>
      </div>

      <!-- ===== Combined financials ===== -->
      <div :class="card" class="p-5">
        <div class="flex items-center justify-between mb-4">
          <h3 class="font-bold text-ink">تصویر مالی تلفیقی</h3>
          <span class="text-[11px] text-slate-400">{{ data.combined.note }}</span>
        </div>
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <p class="text-xs text-slate-400 mb-1">فروش خارجی کل</p>
            <p class="text-xl font-bold ltr-nums text-brand-600">{{ rial(data.combined.total_sales_revenue) }}</p>
          </div>
          <div>
            <p class="text-xs text-slate-400 mb-1">درآمد اجرت تولید (داخلی)</p>
            <p class="text-xl font-bold ltr-nums text-accent-600">{{ rial(data.combined.internal_piece_rate_revenue) }}</p>
          </div>
          <div>
            <p class="text-xs text-slate-400 mb-1">هزینه تولید</p>
            <p class="text-xl font-bold ltr-nums text-ink">{{ rial(data.combined.production_cost) }}</p>
          </div>
          <div>
            <p class="text-xs text-slate-400 mb-1">حاشیه تولید</p>
            <p class="text-xl font-bold ltr-nums" :class="data.combined.production_margin >= 0 ? 'text-green-600' : 'text-red-600'">
              {{ rial(data.combined.production_margin) }}
            </p>
          </div>
        </div>
      </div>
    </template>
      <!-- گزارش این بخش، روی همین صفحه: داشبورد و گزارش یک صفحه‌اند. -->
    <SectionBoard section="overview" :period="selectedPeriod" />
</div>
</template>
