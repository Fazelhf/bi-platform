<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { foreignApi, type ForeignDashboard } from "@/api/commercialForeign";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import StatTile from "@/components/commercial/StatTile.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * داشبورد بازرگانی خارجی.
 *
 * Alerts sit above the numbers, because the numbers describe the situation
 * and the alerts are the part someone can act on this morning.
 */
const router = useRouter();
const { exact } = useMoney();

const data = ref<ForeignDashboard | null>(null);
const loading = ref(true);
const error = ref("");

const FA = new Intl.NumberFormat("fa-IR");

onMounted(async () => {
  await loadMoneySettings();
  try {
    data.value = await foreignApi.dashboard();
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
});

function openAlert(orderId: number | null) {
  if (orderId) router.push({ name: "foreign-order", params: { id: orderId } });
}

const hasAnything = computed(
  () => !!data.value && data.value.counts.active_orders + data.value.counts.cleared > 0,
);
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

    <template v-else-if="data">
      <!-- What needs doing today -->
      <div
        v-if="data.alerts.length"
        class="bg-surface rounded-card shadow-soft overflow-hidden"
      >
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          هشدارها
          <span class="text-slate-400 font-normal">— کارهایی که امروز می‌شود انجام داد</span>
        </h3>
        <ul class="divide-y divide-slate-100 max-h-72 overflow-y-auto">
          <li
            v-for="(a, i) in data.alerts" :key="i"
            class="px-4 py-2.5 flex items-start gap-3 text-sm"
            :class="a.order_id ? 'cursor-pointer hover:bg-slate-50' : ''"
            @click="openAlert(a.order_id)"
          >
            <span
              class="w-2 h-2 rounded-full mt-1.5 shrink-0"
              :class="a.level === 'danger' ? 'bg-red-500' : 'bg-amber-400'"
            />
            <span class="flex-1" :class="a.level === 'danger' ? 'text-red-700' : 'text-slate-600'">
              {{ a.text }}
            </span>
            <span v-if="a.amount_rial" class="text-xs text-red-600 ltr-nums shrink-0">
              {{ exact(a.amount_rial, true) }}
            </span>
          </li>
        </ul>
      </div>

      <!-- The pipeline -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile
          label="پرونده‌های فعال"
          :value="num(data.counts.active_orders)"
          :hint="`${num(data.counts.stalled_orders)} پرونده راکد`"
        />
        <StatTile
          label="در صف تخصیص ارز"
          :value="num(data.counts.in_queue)"
          :hint="data.queue.count
            ? `میانگین ${FA.format(data.queue.avg_days)} روز · بیشترین ${FA.format(data.queue.max_days)} روز`
            : 'صف خالی است'"
        />
        <StatTile
          label="بار در راه"
          :value="num(data.counts.in_transit)"
          :hint="`${num(data.tonnage.in_transit)} تن`"
        />
        <StatTile
          label="بار در گمرک"
          :value="num(data.counts.at_customs)"
          :hint="`${num(data.tonnage.at_customs)} تن`"
        />
      </div>

      <!-- The bill that grows on its own -->
      <div
        v-if="Number(data.demurrage.daily_burn_rial)"
        class="bg-red-50 border border-red-100 rounded-card p-4 flex flex-wrap items-center justify-between gap-3 cursor-pointer"
        @click="router.push({ name: 'foreign-demurrage' })"
      >
        <div>
          <p class="text-sm text-red-700">هزینه هر روز تأخیر</p>
          <p class="text-2xl font-bold text-red-700 ltr-nums mt-0.5">
            {{ exact(data.demurrage.daily_burn_rial, true) }}
          </p>
        </div>
        <p class="text-xs text-red-600 ltr-nums text-left">
          {{ num(data.demurrage.accruing_count) }} کانتینر در حال هزینه‌سازی
          <br />
          جمع تاکنون: {{ exact(data.demurrage.total_rial, true) }}
        </p>
      </div>

      <!-- Value and rates -->
      <div class="grid md:grid-cols-2 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <h3 class="font-bold text-ink text-sm mb-3">ارزش خرید</h3>
          <div v-if="data.value_by_currency.length" class="space-y-2">
            <div
              v-for="v in data.value_by_currency" :key="v.currency"
              class="flex items-baseline justify-between"
            >
              <span class="text-sm text-slate-500">{{ v.label }}</span>
              <span class="text-lg font-bold text-ink ltr-nums">
                {{ FA.format(Number(v.amount)) }}
                <span class="text-xs text-slate-400">{{ v.currency }}</span>
              </span>
            </div>
            <!-- Never summed: adding dollars to euros needs a rate, and which
                 of the three is a choice no headline should make silently. -->
            <p class="text-xs text-slate-400 pt-1 border-t border-slate-100">
              هر ارز جداگانه — جمع کردنشان نیازمند انتخاب یک نرخ است.
            </p>
          </div>
          <p v-else class="text-sm text-slate-400">هنوز پرونده‌ای ثبت نشده.</p>
        </div>

        <div class="bg-surface rounded-card shadow-soft p-4">
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-bold text-ink text-sm">نرخ ارز</h3>
            <button
              class="text-xs text-slate-400 hover:text-ink"
              @click="router.push({ name: 'foreign-fx' })"
            >همه نرخ‌ها ←</button>
          </div>
          <table class="w-full text-sm">
            <tbody>
              <tr v-for="r in data.rates" :key="`${r.currency}-${r.kind}`">
                <td class="py-1 text-slate-500 text-xs">
                  {{ r.currency_label }} · {{ r.kind_label }}
                </td>
                <td class="py-1 text-left ltr-nums">
                  <span v-if="r.rate_rial" class="text-ink">
                    {{ FA.format(Number(r.rate_rial)) }}
                  </span>
                  <span v-else class="text-slate-300 text-xs">ثبت نشده</span>
                  <span
                    v-if="r.age_days"
                    class="text-xs mr-1"
                    :class="r.age_days > 3 ? 'text-amber-600' : 'text-slate-400'"
                  >({{ FA.format(r.age_days) }} روز پیش)</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Queue by bank -->
      <div
        v-if="data.queue.by_bank.length"
        class="bg-surface rounded-card shadow-soft p-4"
      >
        <div class="flex items-center justify-between mb-3">
          <h3 class="font-bold text-ink text-sm">سهم بانک‌ها از صف تخصیص</h3>
          <button
            class="text-xs text-slate-400 hover:text-ink"
            @click="router.push({ name: 'foreign-queue' })"
          >جزئیات صف ←</button>
        </div>
        <div class="flex w-full h-4 rounded-full overflow-hidden mb-3">
          <div
            v-for="b in data.queue.by_bank" :key="b.id ?? 'none'"
            class="h-full"
            :style="{ width: `${b.share_pct}%`, background: b.color || '#94a3b8' }"
            :title="`${b.name} — ${b.share_pct}%`"
          />
        </div>
        <div class="flex flex-wrap gap-x-5 gap-y-1 text-xs">
          <span v-for="b in data.queue.by_bank" :key="b.id ?? 'none'" class="text-slate-500">
            <span
              class="inline-block w-2.5 h-2.5 rounded-full ml-1"
              :style="{ background: b.color || '#94a3b8' }"
            />
            {{ b.name }}
            <span class="ltr-nums text-ink">{{ FA.format(b.share_pct) }}٪</span>
            <span class="ltr-nums text-slate-400">
              ({{ num(b.count) }} — میانگین {{ FA.format(b.avg_days) }} روز)
            </span>
          </span>
        </div>
      </div>

      <!-- Customs pile, the way the warehouse talks about it -->
      <div
        v-if="data.customs_by_brand.length"
        class="bg-surface rounded-card shadow-soft overflow-hidden"
      >
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          بار موجود در گمرک، به تفکیک برند
        </h3>
        <table class="w-full text-sm">
          <tbody>
            <tr v-for="b in data.customs_by_brand" :key="b.brand" class="border-t border-slate-100">
              <td class="px-4 py-2.5 text-ink">{{ b.brand }}</td>
              <td class="px-3 ltr-nums text-slate-500">{{ num(b.tons) }} تن</td>
              <td class="px-4 py-2.5 text-left ltr-nums text-slate-500">
                {{ num(b.containers) }} کانتینر
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-if="!hasAnything"
        title="هنوز پرونده‌ای ثبت نشده"
        hint="با ثبت اولین پروفرما شروع کنید؛ صف تخصیص و محموله‌ها از همان‌جا دنبال می‌شوند."
      />
    </template>
  </div>
</template>
