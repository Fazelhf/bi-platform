<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { crmApi, type ReportData } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num, pct, rial } from "@/utils/format";
import CrmChart from "@/components/crm/CrmChart.vue";
import CrmFilterBar from "@/components/crm/CrmFilterBar.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * گزارش‌ها — one screen that renders every report the server defines.
 *
 * The report list, its axes and its columns all come from the API, so adding
 * a report on the backend makes it appear here with no frontend change. Each
 * row and each bar drills into the records behind it.
 */
const crm = useCrmStore();
const route = useRoute();
const router = useRouter();

const index = ref<{ key: string; title: string; axes: string[] }[]>([]);
const reportKey = ref<string>((route.query.report as string) || "sales");
const axis = ref<string>((route.query.axis as string) || "");
const data = ref<ReportData | null>(null);
const loading = ref(true);
const chartKind = ref<"bar" | "line">("bar");
const measure = ref<"amount" | "count">("amount");

/**
 * Column layout per report. `k` is the row key, `f` the format, and `total`
 * says whether the figure is additive (a footer total for an average would
 * be a lie, so those are marked false).
 */
type Col = { k: string; label: string; f: "rial" | "count" | "pct" | "days" | "text"; total?: boolean };
const COLUMNS: Record<string, Col[]> = {
  sales: [
    { k: "count", label: "تعداد معامله", f: "count", total: true },
    { k: "amount", label: "مبلغ فروش", f: "rial", total: true },
    { k: "cost", label: "بهای تمام‌شده", f: "rial", total: true },
    { k: "profit", label: "سود", f: "rial", total: true },
    { k: "margin_pct", label: "حاشیه سود", f: "pct" },
  ],
  profit: [
    { k: "amount", label: "فروش", f: "rial", total: true },
    { k: "cost", label: "هزینه", f: "rial", total: true },
    { k: "discount", label: "تخفیف", f: "rial", total: true },
    { k: "shipping", label: "حمل", f: "rial", total: true },
    { k: "profit", label: "سود خالص", f: "rial", total: true },
    { k: "margin_pct", label: "حاشیه", f: "pct" },
  ],
  incoming: [
    { k: "count", label: "ورودی", f: "count", total: true },
    { k: "amount", label: "مبلغ ورودی", f: "rial", total: true },
    { k: "won_count", label: "موفق", f: "count", total: true },
    { k: "open_count", label: "جاری", f: "count", total: true },
    { k: "lost_count", label: "ناموفق", f: "count", total: true },
    { k: "won_amount", label: "مبلغ موفق", f: "rial", total: true },
  ],
  lost: [
    { k: "count", label: "تعداد", f: "count", total: true },
    { k: "amount", label: "مبلغ از دست رفته", f: "rial", total: true },
  ],
  funnel: [
    { k: "count", label: "معاملات فعلی", f: "count", total: true },
    { k: "amount", label: "مبلغ", f: "rial", total: true },
    { k: "weighted", label: "ارزش وزنی", f: "rial", total: true },
    { k: "ever", label: "تا کنون رسیده", f: "count" },
    { k: "reach_pct", label: "نرخ عبور", f: "pct" },
  ],
  conversion: [
    { k: "won", label: "موفق", f: "count", total: true },
    { k: "lost", label: "ناموفق", f: "count", total: true },
    { k: "closed", label: "بسته‌شده", f: "count", total: true },
    { k: "rate", label: "نرخ تبدیل", f: "pct" },
    { k: "days_to_win", label: "روز تا موفقیت", f: "days" },
    { k: "days_to_lose", label: "روز تا شکست", f: "days" },
  ],
  new_customers: [{ k: "count", label: "مشتری جدید", f: "count", total: true }],
  activities: [{ k: "count", label: "تعداد فعالیت", f: "count", total: true }],
  calls: [
    { k: "calls", label: "کل تماس", f: "count", total: true },
    { k: "success", label: "موفق", f: "count", total: true },
    { k: "no_answer", label: "بی‌پاسخ", f: "count", total: true },
    { k: "follow_up", label: "نیاز به پیگیری", f: "count", total: true },
    { k: "success_rate", label: "نرخ موفقیت", f: "pct" },
    { k: "customers", label: "مشتریان", f: "count", total: true },
    { k: "minutes", label: "دقیقه", f: "count", total: true },
  ],
  products: [
    { k: "quantity", label: "مقدار", f: "count", total: true },
    { k: "deals", label: "معاملات", f: "count", total: true },
    { k: "amount", label: "فروش ناخالص", f: "rial", total: true },
    { k: "cost", label: "بهای تمام‌شده", f: "rial", total: true },
    { k: "profit", label: "سود", f: "rial", total: true },
    { k: "margin_pct", label: "حاشیه", f: "pct" },
  ],
  provinces: [
    { k: "count", label: "معاملات", f: "count", total: true },
    { k: "customers", label: "مشتریان", f: "count", total: true },
    { k: "owner_label", label: "کارشناس", f: "text" },
    { k: "amount", label: "فروش", f: "rial", total: true },
    { k: "target", label: "تارگت", f: "rial", total: true },
    { k: "achievement_pct", label: "تحقق", f: "pct" },
  ],
  satisfaction: [
    { k: "total", label: "بازخورد", f: "count", total: true },
    { k: "happy", label: "راضی", f: "count", total: true },
    { k: "unhappy", label: "ناراضی", f: "count", total: true },
    { k: "avg_score", label: "میانگین امتیاز", f: "count" },
    { k: "unhappy_pct", label: "درصد نارضایتی", f: "pct" },
  ],
  sources: [
    { k: "leads", label: "سرنخ", f: "count", total: true },
    { k: "won", label: "موفق", f: "count", total: true },
    { k: "conversion_pct", label: "نرخ تبدیل", f: "pct" },
    { k: "amount", label: "فروش", f: "rial", total: true },
    { k: "profit", label: "سود", f: "rial", total: true },
  ],
};

/** Which measure the chart plots, per report. */
const CHART_KEY: Record<string, { amount: string; count: string; fmt: "rial" | "count" | "percent" | "days" }> = {
  sales: { amount: "amount", count: "count", fmt: "rial" },
  profit: { amount: "profit", count: "count", fmt: "rial" },
  incoming: { amount: "amount", count: "count", fmt: "rial" },
  lost: { amount: "amount", count: "count", fmt: "rial" },
  funnel: { amount: "amount", count: "count", fmt: "rial" },
  conversion: { amount: "rate", count: "won", fmt: "percent" },
  new_customers: { amount: "count", count: "count", fmt: "count" },
  activities: { amount: "count", count: "count", fmt: "count" },
  calls: { amount: "success_rate", count: "calls", fmt: "percent" },
  products: { amount: "amount", count: "quantity", fmt: "rial" },
  provinces: { amount: "amount", count: "count", fmt: "rial" },
  satisfaction: { amount: "unhappy", count: "total", fmt: "count" },
  sources: { amount: "amount", count: "won", fmt: "rial" },
};

const cols = computed<Col[]>(() => COLUMNS[reportKey.value] ?? [{ k: "count", label: "تعداد", f: "count", total: true }]);

async function load() {
  loading.value = true;
  try {
    data.value = await crmApi.report(reportKey.value, { ...crm.query, axis: axis.value });
    axis.value = data.value.axis;
    router.replace({ query: { ...route.query, report: reportKey.value, axis: axis.value } });
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  await crm.loadOptions();
  index.value = (await crmApi.reportIndex()).reports;
  await load();
});
watch(() => crm.query, load, { deep: true });
watch(reportKey, () => { axis.value = ""; load(); });
watch(axis, (v, old) => { if (old !== undefined && v !== old) load(); });

function fmtCell(v: any, f: Col["f"]): string {
  if (v === null || v === undefined) return "—";
  if (f === "rial") return rial(v);
  if (f === "pct") return pct(v);
  if (f === "days") return `${num(v)}`;
  if (f === "text") return String(v || "—");
  return num(v);
}

// ---- chart ---------------------------------------------------------------
const spec = computed(() => CHART_KEY[reportKey.value] ?? { amount: "count", count: "count", fmt: "count" as const });
const chartRows = computed(() => (data.value?.rows ?? []).slice(0, 30));
const categories = computed(() => chartRows.value.map((r) => r.label));

const series = computed(() => {
  const rows = chartRows.value;
  const key = measure.value === "amount" ? spec.value.amount : spec.value.count;

  // The lost-reasons time axis is genuinely stacked: one stack per reason.
  if (reportKey.value === "lost" && axis.value === "time" && data.value?.stacks?.length) {
    const palette = ["#ef4444", "#f59e0b", "#6366f1", "#14b8a6", "#8b5cf6", "#64748b", "#0ea5e9", "#84cc16"];
    return data.value.stacks.map((name, i) => ({
      name,
      stack: "reasons",
      color: palette[i % palette.length],
      values: rows.map((r) => r.breakdown?.[name]?.[measure.value === "amount" ? "amount" : "count"] ?? 0),
    }));
  }
  if (reportKey.value === "incoming") {
    return [
      { name: "موفق", stack: "s", color: "#22c55e", values: rows.map((r) => r.won_count) },
      { name: "جاری", stack: "s", color: "#f59e0b", values: rows.map((r) => r.open_count) },
      { name: "ناموفق", stack: "s", color: "#ef4444", values: rows.map((r) => r.lost_count) },
    ];
  }
  if (reportKey.value === "sales" || reportKey.value === "profit") {
    return [
      { name: "فروش", values: rows.map((r) => r.amount), color: "#22c55e" },
      { name: "سود", values: rows.map((r) => r.profit), type: "line" as const, color: "#0ea5e9" },
    ];
  }
  if (reportKey.value === "provinces") {
    return [
      { name: "فروش", values: rows.map((r) => r.amount), color: "#0ea5e9" },
      { name: "تارگت", values: rows.map((r) => r.target), color: "#cbd5e1" },
    ];
  }
  if (reportKey.value === "calls") {
    return [
      { name: "موفق", stack: "c", color: "#22c55e", values: rows.map((r) => r.success) },
      { name: "بی‌پاسخ", stack: "c", color: "#94a3b8", values: rows.map((r) => r.no_answer) },
      { name: "پیگیری", stack: "c", color: "#f59e0b", values: rows.map((r) => r.follow_up) },
      { name: "ناموفق", stack: "c", color: "#ef4444", values: rows.map((r) => r.failed) },
    ];
  }
  return [{ name: data.value?.title ?? "", values: rows.map((r) => r[key]) }];
});

const chartFormat = computed(() => {
  if (reportKey.value === "incoming" || reportKey.value === "calls") return "count" as const;
  return measure.value === "count" ? ("count" as const) : spec.value.fmt;
});

const isStacked = computed(() =>
  ["incoming", "calls"].includes(reportKey.value) ||
  (reportKey.value === "lost" && axis.value === "time"),
);

function pick(i: number) {
  const row = chartRows.value[i];
  if (row?.drill?.kind) crm.openDrill(row.drill, `${data.value?.title} — ${row.label}`);
}

function exportCsv() {
  if (!data.value) return;
  const head = [data.value.axis_labels[axis.value] ?? "عنوان", ...cols.value.map((c) => c.label)];
  const body = data.value.rows.map((r) => [r.label, ...cols.value.map((c) => r[c.k] ?? "")]);
  const totals = ["مجموع", ...cols.value.map((c) => data.value!.totals[c.k] ?? "")];
  const csv = [head, ...body, totals]
    .map((line) => line.map((c: any) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(","))
    .join("\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${data.value.title}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

const tabBtn = (on: boolean) =>
  on ? "bg-panel text-white" : "text-slate-500 hover:bg-slate-100";
</script>

<template>
  <div class="space-y-4">
    <CrmFilterBar />

    <!-- Report picker -->
    <div class="bg-surface rounded-card shadow-soft p-2 flex flex-wrap gap-1 no-print">
      <button
        v-for="r in index" :key="r.key"
        class="text-xs rounded-xl px-3 py-2 transition" :class="tabBtn(reportKey === r.key)"
        @click="reportKey = r.key"
      >{{ r.title }}</button>
    </div>

    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-72 rounded-card" />
      <Skeleton class="h-64 rounded-card" />
    </div>

    <template v-else-if="data">
      <!-- Axis tabs + chart -->
      <div class="bg-surface rounded-card shadow-soft p-4">
        <div class="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div class="flex flex-wrap gap-1">
            <button
              v-for="a in data.axes" :key="a"
              class="text-xs rounded-lg px-2.5 py-1.5 transition"
              :class="axis === a ? 'bg-slate-200 text-ink font-medium' : 'text-slate-400 hover:bg-slate-100'"
              @click="axis = a"
            >{{ data.axis_labels[a] ?? a }}</button>
          </div>

          <div class="flex items-center gap-2 no-print">
            <div class="flex rounded-lg bg-slate-100 p-0.5">
              <button
                class="text-[11px] px-2.5 py-1 rounded-md" :class="measure === 'amount' ? 'bg-surface shadow-sm text-ink' : 'text-slate-400'"
                @click="measure = 'amount'"
              >مبلغ</button>
              <button
                class="text-[11px] px-2.5 py-1 rounded-md" :class="measure === 'count' ? 'bg-surface shadow-sm text-ink' : 'text-slate-400'"
                @click="measure = 'count'"
              >تعداد</button>
            </div>
            <div class="flex rounded-lg bg-slate-100 p-0.5">
              <button
                class="text-[11px] px-2.5 py-1 rounded-md" :class="chartKind === 'bar' ? 'bg-surface shadow-sm text-ink' : 'text-slate-400'"
                @click="chartKind = 'bar'"
              >میله‌ای</button>
              <button
                class="text-[11px] px-2.5 py-1 rounded-md" :class="chartKind === 'line' ? 'bg-surface shadow-sm text-ink' : 'text-slate-400'"
                @click="chartKind = 'line'"
              >خطی</button>
            </div>
            <button class="text-xs rounded-lg px-3 py-1.5 bg-slate-100 text-slate-600 hover:bg-slate-200" @click="exportCsv">
              خروجی اکسل
            </button>
          </div>
        </div>

        <EmptyState v-if="!data.rows.length" title="در این بازه داده‌ای ثبت نشده است" />
        <CrmChart
          v-else
          :categories="categories" :series="series"
          :kind="isStacked ? 'bar' : chartKind"
          :format="chartFormat" :height="320"
          @pick="pick"
        />
        <p v-if="data.rows.length" class="text-[11px] text-slate-300 mt-2 text-center no-print">
          روی هر ستون یا ردیف کلیک کنید تا ریز رکوردهای همان بخش باز شود
        </p>
      </div>

      <!-- Table -->
      <div v-if="data.rows.length" class="bg-surface rounded-card shadow-soft overflow-hidden">
        <!-- Phones: one card per row, the columns laid out as label/value
             pairs. The column set is chosen at runtime, so the card reads the
             same `cols` the table does rather than hardcoding a subset. -->
        <ul class="md:hidden divide-y divide-slate-100">
          <li
            v-for="row in data.rows" :key="`m-${String(row.id)}${row.label}`"
            class="p-4" :class="row.drill?.kind ? 'cursor-pointer active:bg-slate-50' : ''"
            @click="row.drill?.kind && crm.openDrill(row.drill, `${data.title} — ${row.label}`)"
          >
            <p class="text-ink font-medium">{{ row.label }}</p>
            <dl class="grid grid-cols-2 gap-x-3 gap-y-1 mt-2">
              <div v-for="c in cols" :key="c.k" class="flex items-baseline justify-between gap-2 min-w-0">
                <dt class="text-[11px] text-slate-400 truncate">{{ c.label }}</dt>
                <dd
                  class="text-xs ltr-nums shrink-0"
                  :class="c.k === 'profit' ? (Number(row[c.k]) >= 0 ? 'text-emerald-600' : 'text-red-500')
                    : c.k === 'unhappy' && Number(row[c.k]) > 0 ? 'text-red-500'
                    : c.k === 'achievement_pct' ? (Number(row[c.k]) >= 100 ? 'text-emerald-600' : Number(row[c.k]) >= 70 ? 'text-amber-600' : 'text-red-500')
                    : 'text-slate-600'"
                >{{ fmtCell(row[c.k], c.f) }}</dd>
              </div>
            </dl>
          </li>
        </ul>

        <div class="hidden md:block overflow-x-auto">
          <table class="w-full text-sm min-w-[640px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">{{ data.axis_labels[axis] ?? "عنوان" }}</th>
                <th v-for="c in cols" :key="c.k" class="text-left font-medium px-3 py-3 whitespace-nowrap">
                  {{ c.label }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in data.rows" :key="String(row.id) + row.label"
                class="border-t border-slate-100 hover:bg-slate-50"
                :class="row.drill?.kind ? 'cursor-pointer' : ''"
                @click="row.drill?.kind && crm.openDrill(row.drill, `${data.title} — ${row.label}`)"
              >
                <td class="px-4 py-2.5 text-ink font-medium">{{ row.label }}</td>
                <td
                  v-for="c in cols" :key="c.k"
                  class="px-3 py-2.5 text-left whitespace-nowrap"
                  :class="c.k === 'profit' ? (Number(row[c.k]) >= 0 ? 'text-emerald-600' : 'text-red-500')
                    : c.k === 'unhappy' && Number(row[c.k]) > 0 ? 'text-red-500'
                    : c.k === 'achievement_pct' ? (Number(row[c.k]) >= 100 ? 'text-emerald-600' : Number(row[c.k]) >= 70 ? 'text-amber-600' : 'text-red-500')
                    : c.f === 'text' ? 'text-slate-500 text-right' : 'text-slate-600'"
                >{{ fmtCell(row[c.k], c.f) }}</td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="border-t-2 border-slate-200 bg-slate-50 font-bold text-ink">
                <td class="px-4 py-3">مجموع</td>
                <td v-for="c in cols" :key="c.k" class="px-3 py-3 text-left whitespace-nowrap">
                  <!-- Averages have no meaningful sum; the server sends a
                       weighted figure for those and nothing for the rest. -->
                  {{ data.totals[c.k] !== undefined ? fmtCell(data.totals[c.k], c.f) : "—" }}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
