<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import api from "@/api/client";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import DrillPanel, { type DrillColumn } from "@/components/commercial/DrillPanel.vue";
import SeriesChart from "@/components/charts/SeriesChart.vue";
import Skeleton from "@/components/Skeleton.vue";
import SectionBoard from "@/components/boards/SectionBoard.vue";

/**
 * داشبورد بازرگانی داخلی.
 *
 * Every figure opens. The rows arrive with the card, so what the panel lists
 * is by construction what the tile counted.
 */
interface Card {
  key: string; label: string; value: string; unit: string; hint: string;
  tone: "" | "warn" | "danger"; count: number;
  columns: DrillColumn[]; rows: Record<string, any>[];
}
interface Group {
  id: number; name: string; amount: string; quantity: string; count: number;
  columns: DrillColumn[]; rows: Record<string, any>[];
}

const router = useRouter();
const { exact, toUnit, unitLabel } = useMoney();

const cards = ref<Card[]>([]);
const byMaterial = ref<Group[]>([]);
const bySupplier = ref<Group[]>([]);
const monthly = ref<any[]>([]);
const forecastRows = ref<any[]>([]);
const monthLabel = ref("");
const loading = ref(true);
const error = ref("");

const FA = new Intl.NumberFormat("fa-IR");

onMounted(async () => {
  await loadMoneySettings();
  try {
    const { data } = await api.get("/commercial/cards/");
    cards.value = data.cards;
    byMaterial.value = data.by_material;
    bySupplier.value = data.by_supplier;
    monthly.value = data.monthly_spend;
    forecastRows.value = data.forecast;
    monthLabel.value = data.month.label;
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
});

function display(c: Card): string {
  return c.unit === "rial" ? exact(c.value, true) : num(c.value);
}

const TONE: Record<string, string> = {
  danger: "text-red-600", warn: "text-amber-600", "": "text-ink",
};

const spendChart = computed(() => ({
  categories: monthly.value.map((r) => r.label),
  series: [{
    name: `مبلغ خرید (${unitLabel.value})`,
    values: monthly.value.map((r) => (r.has_data ? toUnit(r.amount_rial) : null)),
  }],
}));

const open = ref<{
  title: string; subtitle: string; columns: DrillColumn[]; rows: any[];
} | null>(null);

function openCard(c: Card) {
  if (!c.count) return;
  open.value = { title: c.label, subtitle: c.hint, columns: c.columns, rows: c.rows };
}

function openGroup(g: Group, what: string) {
  if (!g.count) return;
  open.value = {
    title: `${what} — ${g.name}`,
    subtitle: exact(g.amount, true),
    columns: g.columns, rows: g.rows,
  };
}

function pick(row: any) {
  // Orders have no page of their own; a material does.
  if (!row?.material_id) return;
  open.value = null;
  router.push({ name: "commercial-material", params: { id: row.material_id } });
}

const widest = computed(() => Math.max(
  ...byMaterial.value.map((r) => Number(r.amount)), 1,
));
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Skeleton v-for="i in 4" :key="i" class="h-24 rounded-card" />
      </div>
      <Skeleton class="h-64 rounded-card" />
    </div>

    <p v-else-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">
      {{ error }}
    </p>

    <template v-else>
      <div class="flex items-baseline justify-between px-1">
        <h2 class="text-sm text-slate-500">{{ monthLabel }}</h2>
        <span class="text-xs text-slate-400">
          مبالغ به {{ unitLabel }} · روی هر عدد بزنید
        </span>
      </div>

      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <button
          v-for="c in cards" :key="c.key"
          class="bg-surface rounded-card shadow-soft p-4 text-right transition hover:shadow-pop disabled:opacity-60 disabled:cursor-default"
          :disabled="!c.count"
          @click="openCard(c)"
        >
          <p class="text-xs text-slate-400">{{ c.label }}</p>
          <p class="text-2xl font-bold ltr-nums mt-1" :class="TONE[c.tone]">
            {{ display(c) }}
          </p>
          <p class="text-xs text-slate-400 mt-1 ltr-nums">{{ c.hint }}</p>
        </button>
      </div>

      <div v-if="spendChart.categories.length" class="bg-surface rounded-card shadow-soft p-4">
        <SeriesChart
          title="روند مبلغ خرید ماهانه"
          :categories="spendChart.categories"
          :series="spendChart.series"
          :height="240"
        />
      </div>

      <div class="grid md:grid-cols-2 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-sm text-slate-500 mb-3">خرید به تفکیک کالا</p>
          <div class="space-y-1.5">
            <button
              v-for="m in byMaterial.slice(0, 8)" :key="m.id"
              class="w-full text-right rounded-lg px-1 py-1 transition hover:bg-slate-50"
              @click="openGroup(m, 'خرید کالا')"
            >
              <span class="flex items-baseline justify-between text-xs mb-1">
                <span class="text-ink">{{ m.name }}</span>
                <span class="ltr-nums text-slate-500">
                  {{ exact(m.amount) }} · {{ num(m.count) }} سفارش
                </span>
              </span>
              <span class="block h-2 rounded-full bg-slate-100 overflow-hidden">
                <span
                  class="block h-full rounded-full bg-panel/70"
                  :style="{ width: `${(Number(m.amount) / widest) * 100}%` }"
                />
              </span>
            </button>
          </div>
        </div>

        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-sm text-slate-500 mb-3">خرید به تفکیک تامین‌کننده</p>
          <table class="w-full text-sm">
            <tbody>
              <tr
                v-for="s in bySupplier.slice(0, 8)" :key="s.id"
                class="border-t border-slate-100 first:border-0 cursor-pointer hover:bg-slate-50"
                @click="openGroup(s, 'خرید از')"
              >
                <td class="py-2 text-ink">{{ s.name }}</td>
                <td class="py-2 text-xs text-slate-400 ltr-nums">
                  {{ num(s.count) }} سفارش
                </td>
                <td class="py-2 text-left ltr-nums text-slate-600">
                  {{ exact(s.amount) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="forecastRows.length" class="bg-surface rounded-card shadow-soft overflow-hidden">
        <p class="px-4 py-3 border-b border-slate-100 text-sm text-slate-500">
          پیش‌بینی نیاز — یک ماه پس از آخرین خرید هر کالا
        </p>
        <table class="w-full text-sm">
          <tbody>
            <tr
              v-for="f in forecastRows" :key="f.material_id"
              class="border-t border-slate-100 first:border-0 cursor-pointer hover:bg-slate-50"
              @click="router.push({ name: 'commercial-material', params: { id: f.material_id } })"
            >
              <td class="px-4 py-2.5 text-ink">{{ f.material }}</td>
              <td class="px-3 text-xs text-slate-400">{{ f.next_label }}</td>
              <td class="px-3 ltr-nums text-ink">
                {{ num(f.next_quantity) }} {{ f.unit_label }}
              </td>
              <td class="px-4 py-2.5 text-left text-xs text-slate-400 ltr-nums">
                اطمینان {{ FA.format(Math.round(f.confidence * 100)) }}٪
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <DrillPanel
        v-if="open"
        :title="open.title" :subtitle="open.subtitle"
        :columns="open.columns" :rows="open.rows"
        @close="open = null" @pick="pick"
      />
    </template>
      <!-- گزارش این بخش، روی همین صفحه: داشبورد و گزارش یک صفحه‌اند. -->
    <SectionBoard section="commercial" :period="null" />
</div>
</template>
