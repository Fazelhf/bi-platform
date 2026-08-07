<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import api from "@/api/client";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import DrillPanel, { type DrillColumn } from "@/components/commercial/DrillPanel.vue";
import Skeleton from "@/components/Skeleton.vue";

/**
 * گزارش کامل بازرگانی.
 *
 * The dashboards answer «امروز چطور است»; this answers «امسال چه شد». Rows
 * that carry their own breakdown open the same way the dashboard cards do —
 * a report that can only be read just moves the follow-up into an email.
 */
interface Section {
  key: string; title: string; hint: string;
  columns: DrillColumn[];
  rows: Record<string, any>[];
  count: number;
  totals: Record<string, any>;
}

const { exact, unitLabel } = useMoney();

const domestic = ref<Section[]>([]);
const foreign = ref<Section[]>([]);
const headline = ref<any>(null);
const loading = ref(true);
const error = ref("");
const half = ref<"domestic" | "foreign">("domestic");

const FA = new Intl.NumberFormat("fa-IR");

onMounted(async () => {
  await loadMoneySettings();
  try {
    const { data } = await api.get("/commercial/full-report/");
    domestic.value = data.domestic;
    foreign.value = data.foreign;
    headline.value = data.headline;
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
});

const sections = computed(() =>
  half.value === "domestic" ? domestic.value : foreign.value,
);
/** Foreign figures are USD and must not be scaled by the Rial unit toggle. */
const isForeign = computed(() => half.value === "foreign");

function cell(row: Record<string, any>, col: DrillColumn): string {
  const v = row[col.key];
  if (v === null || v === undefined || v === "") return "—";
  if (col.type === "money") {
    return isForeign.value ? FA.format(Number(v)) : exact(v);
  }
  if (col.type === "number") return num(v);
  return String(v);
}

const open = ref<{
  title: string; subtitle: string; columns: DrillColumn[];
  rows: any[]; currency?: string;
} | null>(null);

/** A row that carries its own rows can be opened; the rest are leaves. */
function openRow(section: Section, row: any) {
  if (!row.rows?.length) return;
  open.value = {
    title: `${section.title} — ${row.name ?? row.label ?? ""}`,
    subtitle: `${num(row.rows.length)} ردیف`,
    columns: row.columns ?? section.columns,
    rows: row.rows,
    currency: isForeign.value ? "USD" : undefined,
  };
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-24 rounded-card" />
      <Skeleton v-for="i in 3" :key="i" class="h-48 rounded-card" />
    </div>

    <p v-else-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">
      {{ error }}
    </p>

    <template v-else-if="headline">
      <!-- The year in six numbers -->
      <div class="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-xs text-slate-400">جمع خرید داخلی</p>
          <p class="text-xl font-bold text-ink ltr-nums mt-1">
            {{ exact(headline.domestic_spend, true) }}
          </p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-xs text-slate-400">ارزش واردات</p>
          <p class="text-xl font-bold text-ink ltr-nums mt-1">
            {{ FA.format(Number(headline.foreign_value)) }}
            <span class="text-sm text-slate-400">USD</span>
          </p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-xs text-slate-400">تناژ ترخیص‌شده</p>
          <p class="text-xl font-bold text-ink ltr-nums mt-1">
            {{ num(headline.tons_cleared) }} <span class="text-sm">تن</span>
          </p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-xs text-slate-400">بدهی به فروشنده</p>
          <p class="text-xl font-bold text-ink ltr-nums mt-1">
            {{ FA.format(Number(headline.outstanding)) }}
            <span class="text-sm text-slate-400">USD</span>
          </p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-xs text-slate-400">سود دیرکرد</p>
          <p class="text-xl font-bold text-red-600 ltr-nums mt-1">
            {{ FA.format(Number(headline.interest)) }}
            <span class="text-sm text-slate-400">USD</span>
          </p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-xs text-slate-400">میانگین چرخه واردات</p>
          <p class="text-xl font-bold text-ink ltr-nums mt-1">
            {{ headline.avg_cycle_days
              ? `${FA.format(Math.round(headline.avg_cycle_days))} روز` : "—" }}
          </p>
        </div>
      </div>

      <div class="bg-surface rounded-card shadow-soft p-2 flex gap-1">
        <button
          class="px-4 py-2 rounded-xl text-sm transition-colors"
          :class="half === 'domestic' ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
          @click="half = 'domestic'"
        >بازرگانی داخلی</button>
        <button
          class="px-4 py-2 rounded-xl text-sm transition-colors"
          :class="half === 'foreign' ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
          @click="half = 'foreign'"
        >بازرگانی خارجی</button>
        <span class="flex-1" />
        <span class="text-xs text-slate-400 self-center px-2">
          {{ isForeign ? "مبالغ به دلار" : `مبالغ به ${unitLabel}` }}
        </span>
      </div>

      <div
        v-for="s in sections" :key="s.key"
        class="bg-surface rounded-card shadow-soft overflow-hidden"
      >
        <div class="px-4 py-3 border-b border-slate-100">
          <p class="font-bold text-ink text-sm">
            {{ s.title }}
            <span class="font-normal text-slate-400 ltr-nums">
              ({{ num(s.count) }})
            </span>
          </p>
          <p v-if="s.hint" class="text-xs text-slate-400 mt-0.5">{{ s.hint }}</p>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th
                  v-for="c in s.columns" :key="c.key"
                  class="font-medium px-4 py-2.5"
                  :class="c.align === 'left' ? 'text-left' : 'text-right'"
                >{{ c.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(r, i) in s.rows" :key="i"
                class="border-t border-slate-100"
                :class="r.rows?.length ? 'cursor-pointer hover:bg-slate-50' : ''"
                @click="openRow(s, r)"
              >
                <td
                  v-for="c in s.columns" :key="c.key"
                  class="px-4 py-2.5"
                  :class="[
                    c.align === 'left' ? 'text-left' : 'text-right',
                    c.type === 'money' || c.type === 'number' ? 'ltr-nums' : '',
                    c.key === s.columns[0].key ? 'text-ink' : 'text-slate-500',
                  ]"
                >{{ cell(r, c) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div
          v-if="Object.keys(s.totals).length"
          class="px-4 py-2.5 border-t border-slate-100 bg-slate-50 flex flex-wrap gap-x-6 text-xs"
        >
          <span v-if="s.totals.amount" class="text-slate-500">
            جمع:
            <span class="text-ink ltr-nums">
              {{ isForeign ? FA.format(Number(s.totals.amount)) : exact(s.totals.amount, true) }}
            </span>
          </span>
          <span v-if="s.totals.outstanding" class="text-slate-500">
            باقی‌مانده:
            <span class="text-ink ltr-nums">{{ FA.format(Number(s.totals.outstanding)) }} USD</span>
          </span>
          <span v-if="s.totals.interest" class="text-slate-500">
            سود دیرکرد:
            <span class="text-red-600 ltr-nums">{{ FA.format(Number(s.totals.interest)) }} USD</span>
          </span>
          <span v-if="s.totals.avg_total_days" class="text-slate-500">
            میانگین چرخه:
            <span class="text-ink ltr-nums">
              {{ FA.format(Math.round(s.totals.avg_total_days)) }} روز
            </span>
          </span>
          <span v-if="s.totals.avg_price_per_ton" class="text-slate-500">
            میانگین قیمت هر تن:
            <span class="text-ink ltr-nums">
              {{ FA.format(Number(s.totals.avg_price_per_ton)) }} USD
            </span>
          </span>
        </div>
      </div>

      <DrillPanel
        v-if="open"
        :title="open.title" :subtitle="open.subtitle"
        :columns="open.columns" :rows="open.rows" :currency="open.currency"
        @close="open = null"
      />
    </template>
  </div>
</template>
