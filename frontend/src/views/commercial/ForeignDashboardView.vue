<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import api from "@/api/client";
import { loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import DrillPanel, { type DrillColumn } from "@/components/commercial/DrillPanel.vue";
import Skeleton from "@/components/Skeleton.vue";

/**
 * داشبورد بازرگانی خارجی.
 *
 * Every figure opens. The rows arrive with the card, so the panel lists
 * exactly what the tile counted — there is no second query to drift from it.
 */
interface Card {
  key: string;
  label: string;
  value: string;
  unit: string;
  hint: string;
  tone: "" | "warn" | "danger";
  count: number;
  columns: DrillColumn[];
  rows: Record<string, any>[];
}
interface Stage {
  status: string; label: string; count: number;
  amount: string; tons: string;
  columns: DrillColumn[]; rows: Record<string, any>[];
}
interface Bank {
  id: number | null; name: string; color: string;
  count: number; amount: string; share_pct: number;
  avg_days: number; max_days: number; overdue_count: number;
}

const router = useRouter();

const cards = ref<Card[]>([]);
const stages = ref<Stage[]>([]);
const banks = ref<Bank[]>([]);
const cycle = ref<any>(null);
const queueAmount = ref("0");
const loading = ref(true);
const error = ref("");

const FA = new Intl.NumberFormat("fa-IR");

onMounted(async () => {
  await loadMoneySettings();
  try {
    const { data } = await api.get("/commercial/foreign/cards/");
    cards.value = data.cards;
    stages.value = data.by_stage;
    banks.value = data.by_bank;
    cycle.value = data.cycle;
    queueAmount.value = data.queue_amount;
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
});

/** Rial cards are scaled by the unit toggle; foreign-currency ones are not. */
function display(c: Card): string {
  if (c.unit === "USD") return FA.format(Number(c.value));
  if (c.unit === "تن") return num(c.value);
  return num(c.value);
}

const TONE: Record<string, string> = {
  danger: "text-red-600",
  warn: "text-amber-600",
  "": "text-ink",
};

// -- the drill panel ---------------------------------------------------
const openCard = ref<{
  title: string; subtitle: string;
  columns: DrillColumn[]; rows: any[]; currency?: string;
} | null>(null);

function openFrom(c: Card) {
  if (!c.rows.length) return;
  openCard.value = {
    title: c.label, subtitle: c.hint,
    columns: c.columns, rows: c.rows,
    currency: c.unit === "USD" ? "USD" : undefined,
  };
}

function openStage(s: Stage) {
  if (!s.count) return;
  openCard.value = {
    title: s.label, subtitle: `${FA.format(Number(s.amount))} USD`,
    columns: s.columns, rows: s.rows, currency: "USD",
  };
}

function openBank(b: Bank) {
  const queue = cards.value.find((c) => c.key === "queue");
  if (!queue) return;
  openCard.value = {
    title: `صف تخصیص — ${b.name}`,
    subtitle: `${FA.format(Number(b.amount))} USD · میانگین ${FA.format(b.avg_days)} روز`,
    columns: queue.columns,
    rows: queue.rows.filter((r) => r.bank === b.name),
    currency: "USD",
  };
}

/** A row that names a file opens that file. */
function pick(row: any) {
  if (!row?.id) return;
  openCard.value = null;
  router.push({ name: "foreign-order", params: { id: row.id } });
}

const widest = computed(
  () => Math.max(...stages.value.map((s) => s.count), 1),
);
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Skeleton v-for="i in 8" :key="i" class="h-24 rounded-card" />
      </div>
      <Skeleton class="h-64 rounded-card" />
    </div>

    <p
      v-else-if="error"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line"
    >{{ error }}</p>

    <template v-else>
      <p class="text-xs text-slate-400 px-1">
        روی هر عدد بزنید تا ردیف‌های پشتش باز شود.
      </p>

      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <button
          v-for="c in cards" :key="c.key"
          class="bg-surface rounded-card shadow-soft p-4 text-right transition hover:shadow-pop disabled:opacity-60 disabled:cursor-default"
          :class="c.tone === 'danger' ? 'ring-1 ring-red-100' : ''"
          :disabled="!c.count"
          @click="openFrom(c)"
        >
          <p class="text-xs text-slate-400">{{ c.label }}</p>
          <p class="text-2xl font-bold ltr-nums mt-1" :class="TONE[c.tone]">
            {{ display(c) }}
            <span v-if="c.unit" class="text-sm font-normal text-slate-400">
              {{ c.unit }}
            </span>
          </p>
          <p class="text-xs text-slate-400 mt-1 ltr-nums">{{ c.hint }}</p>
        </button>
      </div>

      <!-- Pipeline -->
      <div class="bg-surface rounded-card shadow-soft p-4">
        <p class="text-sm text-slate-500 mb-3">وضعیت پرونده‌ها</p>
        <div class="space-y-1.5">
          <button
            v-for="s in stages" :key="s.status"
            class="w-full flex items-center gap-3 text-right rounded-lg px-1 py-1 transition hover:bg-slate-50 disabled:cursor-default"
            :disabled="!s.count"
            @click="openStage(s)"
          >
            <span class="text-xs text-slate-500 w-40 shrink-0">{{ s.label }}</span>
            <span class="flex-1 h-6 bg-slate-50 rounded-lg overflow-hidden">
              <span
                class="block h-full bg-panel/80 rounded-lg"
                :style="{ width: `${Math.round((s.count / widest) * 100)}%` }"
              />
            </span>
            <span class="text-xs ltr-nums w-36 text-left shrink-0">
              <span class="text-ink font-medium">{{ num(s.count) }}</span>
              <span v-if="Number(s.amount)" class="text-slate-400">
                · {{ FA.format(Number(s.amount)) }}
              </span>
            </span>
          </button>
        </div>
      </div>

      <div class="grid md:grid-cols-2 gap-3">
        <!-- Bank queue -->
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-sm text-slate-500">صف تخصیص ارز به تفکیک بانک</p>
          <p class="text-xs text-slate-400 mb-3 ltr-nums">
            {{ FA.format(Number(queueAmount)) }} USD نزد
            {{ num(banks.length) }} بانک
          </p>
          <div v-if="banks.length" class="space-y-2.5">
            <button
              v-for="b in banks" :key="b.id ?? 'none'"
              class="w-full text-right rounded-lg px-1 py-1 transition hover:bg-slate-50"
              @click="openBank(b)"
            >
              <span class="flex items-baseline justify-between text-xs mb-1">
                <span class="text-ink">{{ b.name }}</span>
                <span class="ltr-nums text-slate-500">
                  {{ FA.format(b.share_pct) }}٪ · {{ FA.format(Number(b.amount)) }}
                </span>
              </span>
              <span class="block h-2 rounded-full bg-slate-100 overflow-hidden">
                <span
                  class="block h-full rounded-full"
                  :style="{ width: `${b.share_pct}%`, background: b.color || '#94a3b8' }"
                />
              </span>
              <span class="block text-xs text-slate-400 ltr-nums mt-0.5">
                {{ num(b.count) }} پرونده · میانگین {{ FA.format(b.avg_days) }} روز
                <span v-if="b.overdue_count" class="text-amber-600">
                  · {{ num(b.overdue_count) }} فراتر از مهلت
                </span>
              </span>
            </button>
          </div>
          <p v-else class="text-sm text-slate-400">پرونده‌ای در صف نیست.</p>
        </div>

        <!-- Cycle time -->
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-sm text-slate-500">میانگین زمان چرخه</p>
          <p class="text-xs text-slate-400 mb-3 ltr-nums">
            بر پایه {{ num(cycle?.file_count ?? 0) }} پرونده بسته‌شده امسال
          </p>
          <template v-if="cycle?.avg_total_days">
            <p class="text-3xl font-bold text-ink ltr-nums">
              {{ FA.format(Math.round(cycle.avg_total_days)) }}
              <span class="text-base font-normal text-slate-400">روز</span>
            </p>
            <p class="text-xs text-slate-400 ltr-nums mt-1">
              از ثبت سفارش تا ترخیص · طولانی‌ترین
              {{ FA.format(cycle.longest_days ?? 0) }} روز
            </p>
            <div class="grid grid-cols-3 gap-2 mt-4 pt-3 border-t border-slate-100 text-center">
              <div v-for="s in [
                { label: 'تخصیص ارز', v: cycle.avg_queue_days },
                { label: 'حمل', v: cycle.avg_sea_days },
                { label: 'گمرک', v: cycle.avg_customs_days },
              ]" :key="s.label">
                <p class="text-xs text-slate-400">{{ s.label }}</p>
                <p class="text-lg font-bold text-ink ltr-nums">
                  {{ s.v === null || s.v === undefined
                    ? "—" : FA.format(Math.round(s.v)) }}
                </p>
              </div>
            </div>
          </template>
          <p v-else class="text-sm text-slate-400">امسال هنوز پرونده‌ای بسته نشده.</p>
        </div>
      </div>

      <DrillPanel
        v-if="openCard"
        :title="openCard.title"
        :subtitle="openCard.subtitle"
        :columns="openCard.columns"
        :rows="openCard.rows"
        :currency="openCard.currency"
        @close="openCard = null"
        @pick="pick"
      />
    </template>
  </div>
</template>
