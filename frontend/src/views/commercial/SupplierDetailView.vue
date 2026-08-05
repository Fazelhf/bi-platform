<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { commercialApi, type SupplierHistory } from "@/api/commercial";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import StatTile from "@/components/commercial/StatTile.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/** پرونده یک تامین‌کننده: چه خواست، چه برد، و چه تحویل داد. */
const route = useRoute();
const router = useRouter();
const { exact, unitLabel } = useMoney();

const data = ref<SupplierHistory | null>(null);
const loading = ref(true);
const error = ref("");

const FA = new Intl.NumberFormat("fa-IR");

const stats = computed(() => data.value?.stats ?? null);

onMounted(async () => {
  await loadMoneySettings();
  try {
    data.value = await commercialApi.supplierHistory(Number(route.params.id));
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-20 rounded-card" />
      <Skeleton class="h-48 rounded-card" />
    </div>

    <p
      v-else-if="error"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line"
    >{{ error }}</p>

    <template v-else-if="stats">
      <div class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 class="text-lg font-bold text-ink">
            {{ stats.name }}
            <span v-if="!stats.is_active" class="text-xs text-slate-400 font-normal">(غیرفعال)</span>
          </h2>
          <p class="text-xs text-slate-400 mt-0.5">
            <span v-if="stats.contact_name">{{ stats.contact_name }}</span>
            <span v-if="stats.mobile" class="ltr-nums"> · {{ stats.mobile }}</span>
            <span v-if="stats.activity"> · {{ stats.activity }}</span>
          </p>
          <p v-if="stats.materials.length" class="text-xs text-slate-500 mt-1">
            کالاها: {{ stats.materials.join("، ") }}
          </p>
        </div>
        <button
          class="text-sm text-slate-500 hover:text-ink px-2 py-2"
          @click="router.push({ name: 'commercial-suppliers' })"
        >← بازگشت</button>
      </div>

      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile
          label="جمع خرید"
          :value="exact(stats.total_spend_rial, true)"
          :hint="`${num(stats.order_count)} سفارش`"
        />
        <StatTile
          label="درصد برد در استعلام"
          :value="stats.win_rate_pct === null
            ? '—'
            : `${FA.format(stats.win_rate_pct)}٪`"
          :hint="stats.win_rate_pct === null
            ? 'هنوز استعلامی نگرفته'
            : `${num(stats.win_count)} برد از ${num(stats.quote_count)} استعلام`"
        />
        <StatTile
          label="میانگین قیمت پیشنهادی"
          :value="exact(stats.avg_quote_price_rial, true)"
          :hint="`آخرین قیمت: ${exact(stats.last_price_rial)}`"
        />
        <StatTile
          label="میانگین زمان تحویل"
          :value="stats.avg_actual_days === null
            ? (stats.avg_promised_days === null ? '—' : `${FA.format(stats.avg_promised_days)} روز`)
            : `${FA.format(stats.avg_actual_days)} روز`"
          :hint="stats.avg_actual_days === null
            ? 'بر پایه قول تحویل — هنوز تحویلی ثبت نشده'
            : `قول داده: ${stats.avg_promised_days === null ? '—' : FA.format(stats.avg_promised_days) + ' روز'}`"
        />
      </div>

      <!-- Quote history: the wins and, more usefully, the losses -->
      <div class="bg-surface rounded-card shadow-soft overflow-hidden">
        <div class="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
          <h3 class="font-bold text-ink text-sm">تاریخچه استعلام</h3>
          <span class="text-xs text-slate-400">مبالغ به {{ unitLabel }}</span>
        </div>
        <EmptyState v-if="!data?.quotes.length" title="استعلامی ثبت نشده" />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm min-w-[800px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">تاریخ</th>
                <th class="text-right font-medium px-3">کالا</th>
                <th class="text-right font-medium px-3">مقدار</th>
                <th class="text-right font-medium px-3">قیمت واحد</th>
                <th class="text-right font-medium px-3">تحویل</th>
                <th class="text-right font-medium px-4">نتیجه</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="q in data.quotes" :key="q.id"
                class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                @click="router.push({ name: 'commercial-request', params: { id: q.request_id } })"
              >
                <td class="px-4 py-2.5 text-xs text-slate-500 ltr-nums">
                  {{ faDate(q.quoted_on) }}
                  <p class="text-slate-400">{{ q.request_no }}</p>
                </td>
                <td class="px-3 text-ink">{{ q.material }}</td>
                <td class="px-3 ltr-nums text-slate-500">{{ num(q.quantity) }}</td>
                <td class="px-3 ltr-nums text-ink">{{ exact(q.unit_price_rial) }}</td>
                <td class="px-3 ltr-nums text-slate-500">{{ num(q.delivery_days) }} روز</td>
                <td class="px-4">
                  <span
                    v-if="q.is_selected"
                    class="text-xs rounded-full px-2 py-0.5 bg-emerald-100 text-emerald-700"
                  >✔ برنده{{ q.reason ? ` — ${q.reason}` : "" }}</span>
                  <span
                    v-else-if="q.reason"
                    class="text-xs rounded-full px-2 py-0.5 bg-red-50 text-red-500"
                  >{{ q.reason }}</span>
                  <span v-else class="text-xs text-slate-300">بدون نتیجه</span>
                  <p v-if="q.decision_note" class="text-xs text-slate-400 mt-0.5">
                    {{ q.decision_note }}
                  </p>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Orders actually placed -->
      <div class="bg-surface rounded-card shadow-soft overflow-hidden">
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          سفارش‌های خرید
        </h3>
        <EmptyState v-if="!data?.orders.length" title="هنوز از این تامین‌کننده خریدی نشده" />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm min-w-[760px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">شماره</th>
                <th class="text-right font-medium px-3">کالا</th>
                <th class="text-right font-medium px-3">تعداد</th>
                <th class="text-right font-medium px-3">مبلغ کل</th>
                <th class="text-right font-medium px-3">تاریخ</th>
                <th class="text-right font-medium px-4">وضعیت</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="o in data.orders" :key="o.id" class="border-t border-slate-100">
                <td class="px-4 py-2.5 ltr-nums text-ink font-medium">{{ o.order_no }}</td>
                <td class="px-3 text-ink">{{ o.material }}</td>
                <td class="px-3 ltr-nums text-slate-500">{{ num(o.quantity) }}</td>
                <td class="px-3 ltr-nums text-ink">{{ exact(o.total_rial) }}</td>
                <td class="px-3 text-xs text-slate-500 ltr-nums">
                  {{ faDate(o.ordered_on) }}
                  <p v-if="o.delivery_days !== null" class="text-slate-400">
                    تحویل در {{ num(o.delivery_days) }} روز
                  </p>
                </td>
                <td class="px-4 text-xs text-slate-500">{{ o.status_label }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <EmptyState v-else title="تامین‌کننده پیدا نشد" />
  </div>
</template>
