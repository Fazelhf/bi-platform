<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { foreignApi, type HistoryReport } from "@/api/commercialForeign";
import { loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import SeriesChart from "@/components/charts/SeriesChart.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * تاریخچه — files finished in a year, and how long they really took.
 *
 * The cycle time is split into the three waits that make it up, because they
 * have different owners: the queue is the bank's, the sea is the carrier's,
 * customs is ours. A single «۲۵۶ روز» tells nobody which one to push on.
 */
const router = useRouter();

const data = ref<HistoryReport | null>(null);
const loading = ref(true);
const error = ref("");
const year = ref<number | undefined>(undefined);

const FA = new Intl.NumberFormat("fa-IR");

async function load() {
  loading.value = true;
  try {
    data.value = await foreignApi.history(year.value);
    year.value = data.value.year;
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await loadMoneySettings(); await load(); });
watch(year, (v, old) => { if (old !== undefined && v !== old) load(); });

const totals = computed(() => data.value?.totals);

/** Price per tonne over the year — is importing getting dearer? */
const priceChart = computed(() => {
  const rows = [...(data.value?.rows ?? [])]
    .filter((r) => Number(r.price_per_ton) > 0)
    .reverse();
  return {
    categories: rows.map((r) => faDate(r.finished_on)),
    series: [{
      name: "قیمت هر تن (USD)",
      values: rows.map((r) => Number(r.price_per_ton)),
    }],
  };
});

function days(v: number | null): string {
  return v === null || v === undefined ? "—" : `${FA.format(Math.round(v))} روز`;
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-28 rounded-card" />
      <Skeleton v-for="i in 5" :key="i" class="h-12 rounded-xl" />
    </div>

    <p v-else-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">
      {{ error }}
    </p>

    <template v-else-if="data && totals">
      <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
        <span class="text-sm text-slate-500">سال</span>
        <select
          v-model.number="year"
          class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none ltr-nums"
        >
          <option v-for="y in data.years" :key="y" :value="y">{{ FA.format(y) }}</option>
        </select>
        <span class="text-xs text-slate-400 ltr-nums">
          {{ num(totals.file_count) }} پرونده بسته شده
        </span>
      </div>

      <EmptyState
        v-if="!data.rows.length"
        title="در این سال پرونده‌ای بسته نشده"
        hint="پرونده وقتی اینجا می‌آید که تاریخ ترخیصش ثبت شده باشد."
      />

      <template v-else>
        <!-- The number that makes planning possible -->
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">میانگین کل چرخه</p>
            <p class="text-2xl font-bold text-ink ltr-nums mt-1">
              {{ days(totals.avg_total_days) }}
            </p>
            <p class="text-xs text-slate-400 ltr-nums">
              طولانی‌ترین {{ days(totals.longest_days) }}
            </p>
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">جمع ارزش</p>
            <p class="text-2xl font-bold text-ink ltr-nums mt-1">
              {{ FA.format(Number(totals.value)) }}
              <span class="text-sm text-slate-400">USD</span>
            </p>
            <p class="text-xs text-slate-400 ltr-nums">
              {{ num(totals.tons) }} تن
            </p>
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">میانگین قیمت هر تن</p>
            <p class="text-2xl font-bold text-ink ltr-nums mt-1">
              {{ FA.format(Number(totals.avg_price_per_ton)) }}
              <span class="text-sm text-slate-400">USD</span>
            </p>
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs text-slate-400">کانتینر</p>
            <p class="text-2xl font-bold text-ink ltr-nums mt-1">
              {{ num(totals.container_count) }}
            </p>
          </div>
        </div>

        <!-- Where the time actually goes -->
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-sm font-bold text-ink mb-3">
            زمان کجا می‌رود
            <span class="font-normal text-slate-400">
              — هر مرحله صاحب دیگری دارد
            </span>
          </p>
          <div class="grid grid-cols-3 gap-3 text-center">
            <div>
              <p class="text-xs text-slate-400">صف تخصیص ارز</p>
              <p class="text-xl font-bold text-amber-600 ltr-nums">
                {{ days(totals.avg_queue_days) }}
              </p>
              <p class="text-xs text-slate-400">بانک</p>
            </div>
            <div>
              <p class="text-xs text-slate-400">مسیر دریا</p>
              <p class="text-xl font-bold text-sky-600 ltr-nums">
                {{ days(totals.avg_sea_days) }}
              </p>
              <p class="text-xs text-slate-400">شرکت حمل</p>
            </div>
            <div>
              <p class="text-xs text-slate-400">گمرک تا ترخیص</p>
              <p class="text-xl font-bold text-emerald-600 ltr-nums">
                {{ days(totals.avg_customs_days) }}
              </p>
              <p class="text-xs text-slate-400">ما</p>
            </div>
          </div>
        </div>

        <div v-if="priceChart.categories.length > 1" class="bg-surface rounded-card shadow-soft p-4">
          <SeriesChart
            title="قیمت هر تن در طول سال"
            :categories="priceChart.categories"
            :series="priceChart.series"
            :height="220"
          />
        </div>

        <div class="bg-surface rounded-card shadow-soft overflow-hidden">
          <div class="overflow-x-auto">
            <table class="w-full text-sm min-w-[960px]">
              <thead>
                <tr class="text-xs text-slate-400 bg-slate-50">
                  <th class="text-right font-medium px-4 py-3">پرونده</th>
                  <th class="text-right font-medium px-3">کالا</th>
                  <th class="text-right font-medium px-3">بانک</th>
                  <th class="text-right font-medium px-3">مقدار / ارزش</th>
                  <th class="text-right font-medium px-3">قیمت هر تن</th>
                  <th class="text-right font-medium px-3">ثبت → ترخیص</th>
                  <th class="text-right font-medium px-4">کل</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="r in data.rows" :key="r.id"
                  class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                  @click="router.push({ name: 'foreign-order', params: { id: r.id } })"
                >
                  <td class="px-4 py-2.5">
                    <p class="text-ink font-medium ltr-nums">{{ r.pi_no }}</p>
                    <p class="text-xs text-slate-400 ltr-nums">{{ r.registration_no }}</p>
                  </td>
                  <td class="px-3 text-slate-500 text-xs">{{ r.goods || "—" }}</td>
                  <td class="px-3 text-slate-500 text-xs">{{ r.bank || "—" }}</td>
                  <td class="px-3 ltr-nums text-slate-500 text-xs">
                    {{ num(r.weight_ton) }} تن
                    <p class="text-ink">{{ FA.format(Number(r.amount)) }} {{ r.currency }}</p>
                  </td>
                  <td class="px-3 ltr-nums text-ink">
                    {{ Number(r.price_per_ton)
                      ? FA.format(Number(r.price_per_ton)) : "—" }}
                  </td>
                  <td class="px-3 text-xs text-slate-500 ltr-nums">
                    {{ r.registered_on ? faDate(r.registered_on) : "—" }}
                    <p class="text-emerald-600">{{ faDate(r.finished_on) }}</p>
                  </td>
                  <td class="px-4 ltr-nums font-medium"
                      :class="(r.total_days ?? 0) > 300 ? 'text-red-600' : 'text-ink'">
                    {{ days(r.total_days) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>
