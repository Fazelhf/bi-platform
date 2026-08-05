<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  foreignApi,
  type RateCell,
  type RateKind,
} from "@/api/commercialForeign";
import { useAuthStore } from "@/stores/auth";
import { loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import FxRateForm from "@/components/commercial/FxRateForm.vue";
import SeriesChart from "@/components/charts/SeriesChart.vue";
import Skeleton from "@/components/Skeleton.vue";

/**
 * نرخ ارز — شش نرخ.
 *
 * Each cell shows the date its figure belongs to, not today's date. A rate
 * from three weeks ago displayed without that would quietly pass as current
 * and mis-value every file that used it.
 */
const auth = useAuthStore();
const board = ref<RateCell[]>([]);
const hasProvider = ref(false);
const asOf = ref("");
const loading = ref(true);
const error = ref("");
const message = ref("");

const FA = new Intl.NumberFormat("fa-IR");

const canEdit = computed(
  () => auth.department === "commercial" || !!auth.me?.is_superuser,
);

const CURRENCIES = ["USD", "EUR"] as const;
const KINDS: { key: RateKind; label: string }[] = [
  { key: "free", label: "آزاد" },
  { key: "centre", label: "مرکز مبادله" },
  { key: "customs", label: "گمرکی" },
];

function cell(currency: string, kind: RateKind): RateCell | undefined {
  return board.value.find((r) => r.currency === currency && r.kind === kind);
}

/** A rate more than a few days old should not read as today's. */
function ageTone(age: number | null): string {
  if (age === null) return "text-slate-300";
  if (age === 0) return "text-emerald-600";
  if (age <= 3) return "text-slate-400";
  return "text-amber-600";
}

const history = ref<{ on_date: string; rate_rial: string }[]>([]);
const picked = ref<{ currency: string; kind: RateKind }>({
  currency: "USD", kind: "centre",
});

const chart = computed(() => ({
  categories: history.value.map((r) => faDate(r.on_date)),
  series: [{
    name: "نرخ (ریال)",
    values: history.value.map((r) => Number(r.rate_rial)),
  }],
}));

async function loadBoard() {
  const data = await foreignApi.rateBoard();
  board.value = data.rows;
  hasProvider.value = data.provider;
  asOf.value = data.on;
}

async function loadHistory() {
  const data = await foreignApi.rateHistory(picked.value.currency, picked.value.kind);
  history.value = data.rows;
}

async function pick(currency: string, kind: RateKind) {
  picked.value = { currency, kind };
  await loadHistory();
}

onMounted(async () => {
  await loadMoneySettings();
  try {
    await Promise.all([loadBoard(), loadHistory()]);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
});

const showForm = ref(false);
const syncing = ref(false);

async function onSaved() {
  showForm.value = false;
  await Promise.all([loadBoard(), loadHistory()]);
}

async function sync() {
  syncing.value = true;
  message.value = "";
  error.value = "";
  try {
    const report = await foreignApi.syncRates();
    if (report.ok) {
      message.value = report.detail;
      await loadBoard();
    } else {
      error.value = report.detail;
    }
  } catch (e) {
    error.value = apiError(e);
  } finally {
    syncing.value = false;
  }
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-40 rounded-card" />
      <Skeleton class="h-64 rounded-card" />
    </div>

    <template v-else>
      <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
        <span class="text-sm text-slate-500 ltr-nums">
          نرخ‌های در دسترس تا {{ faDate(asOf) }}
        </span>
        <span class="flex-1" />
        <button
          v-if="canEdit"
          class="bg-slate-100 text-ink rounded-xl px-4 py-2 text-sm disabled:opacity-50"
          :disabled="syncing"
          @click="sync"
        >{{ syncing ? "در حال دریافت…" : "دریافت خودکار" }}</button>
        <button
          v-if="canEdit"
          class="bg-panel text-white rounded-xl px-4 py-2 text-sm"
          @click="showForm = true"
        >+ ثبت نرخ</button>
      </div>

      <p
        v-if="!hasProvider"
        class="bg-sky-50 text-sky-700 text-sm rounded-xl px-3 py-2"
      >
        منبع دریافت خودکار هنوز تنظیم نشده است؛ نرخ‌ها دستی ثبت می‌شوند.
        نرخ گمرکی در هر حالت با بخشنامه تعیین می‌شود و دستی می‌ماند.
      </p>
      <p v-if="message" class="bg-emerald-50 text-emerald-700 text-sm rounded-xl px-3 py-2">
        {{ message }}
      </p>
      <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">
        {{ error }}
      </p>

      <!-- The six -->
      <div class="bg-surface rounded-card shadow-soft overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[640px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">ارز</th>
                <th v-for="k in KINDS" :key="k.key" class="text-right font-medium px-3">
                  {{ k.label }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in CURRENCIES" :key="c" class="border-t border-slate-100">
                <td class="px-4 py-3 text-ink font-medium">
                  {{ cell(c, "free")?.currency_label ?? c }}
                  <span class="text-xs text-slate-400 ltr-nums">{{ c }}</span>
                </td>
                <td
                  v-for="k in KINDS" :key="k.key"
                  class="px-3 py-3 cursor-pointer hover:bg-slate-50"
                  :class="picked.currency === c && picked.kind === k.key ? 'bg-slate-50' : ''"
                  @click="pick(c, k.key)"
                >
                  <template v-if="cell(c, k.key)?.rate_rial">
                    <p class="text-ink font-medium ltr-nums">
                      {{ FA.format(Number(cell(c, k.key)!.rate_rial)) }}
                    </p>
                    <p class="text-xs ltr-nums" :class="ageTone(cell(c, k.key)!.age_days)">
                      {{ faDate(cell(c, k.key)!.on_date!) }}
                      <template v-if="cell(c, k.key)!.age_days">
                        — {{ FA.format(cell(c, k.key)!.age_days!) }} روز پیش
                      </template>
                      <span v-if="cell(c, k.key)!.is_manual" class="text-slate-400">· دستی</span>
                    </p>
                  </template>
                  <span v-else class="text-slate-300 text-xs">ثبت نشده</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="px-4 py-2 text-xs text-slate-400 border-t border-slate-100">
          روی هر خانه بزنید تا نمودار تغییرات همان نرخ پایین نمایش داده شود.
        </p>
      </div>

      <div v-if="chart.categories.length" class="bg-surface rounded-card shadow-soft p-4">
        <SeriesChart
          :title="`روند نرخ ${picked.currency} — ${KINDS.find(k => k.key === picked.kind)?.label}`"
          :categories="chart.categories"
          :series="chart.series"
          :height="260"
        />
      </div>

      <div v-if="history.length" class="bg-surface rounded-card shadow-soft overflow-hidden">
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          تاریخچه ({{ num(history.length) }} ثبت)
        </h3>
        <table class="w-full text-sm">
          <tbody>
            <tr
              v-for="r in [...history].reverse()" :key="r.on_date"
              class="border-t border-slate-100"
            >
              <td class="px-4 py-2 text-slate-500 ltr-nums">{{ faDate(r.on_date) }}</td>
              <td class="px-4 py-2 text-left text-ink ltr-nums">
                {{ FA.format(Number(r.rate_rial)) }} ریال
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <FxRateForm
        v-if="showForm"
        :currency="picked.currency" :kind="picked.kind"
        @close="showForm = false" @saved="onSaved"
      />
    </template>
  </div>
</template>
