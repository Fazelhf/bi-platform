<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { crmApi, type Deal } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num, pct, rial } from "@/utils/format";
import Skeleton from "@/components/Skeleton.vue";

/**
 * پرونده معامله — and, more importantly, **why this deal made the money it
 * made**: the line-by-line margin plus the deal-level costs that eat it.
 * This is the answer to "دلیل سودش بیاره".
 */
const route = useRoute();
const router = useRouter();
const crm = useCrmStore();

const deal = ref<Deal | null>(null);
const history = ref<any[]>([]);
const activities = ref<any[]>([]);
const loading = ref(true);
const moving = ref(false);

async function load() {
  loading.value = true;
  try {
    const id = Number(route.params.id);
    const [d, h, a] = await Promise.all([
      crmApi.deal(id),
      crmApi.dealHistory(id),
      crmApi.activities({ deal: id, page_size: 100 }),
    ]);
    deal.value = d;
    history.value = h;
    activities.value = a.results;
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await crm.loadOptions(); await load(); });
watch(() => route.params.id, load);

async function moveTo(stageId: number) {
  if (!deal.value) return;
  moving.value = true;
  try {
    await crmApi.moveDeal(deal.value.id, stageId);
    await load();
  } finally {
    moving.value = false;
  }
}

const items = computed(() => deal.value?.items ?? []);

/** Gross line margin, before the costs that sit on the deal itself. */
const grossProfit = computed(() =>
  items.value.reduce((s, i) => s + Number(i.line_profit), 0),
);

const costBreakdown = computed(() => {
  const d = deal.value;
  if (!d) return [];
  return [
    { label: "سود ناخالص ردیف‌ها", value: grossProfit.value, positive: true },
    { label: "تخفیف کل معامله", value: -Number(d.discount_rial), positive: false },
    { label: "هزینه حمل", value: -Number(d.shipping_cost_rial), positive: false },
    { label: "سایر هزینه‌ها", value: -Number(d.other_cost_rial), positive: false },
  ].filter((r) => r.value !== 0);
});

const statusClass: Record<string, string> = {
  won: "bg-emerald-500", lost: "bg-red-500", open: "bg-amber-500",
};
const card = "bg-surface rounded-card shadow-soft p-4";
</script>

<template>
  <div class="space-y-4">
    <button class="text-sm text-slate-400 hover:text-ink no-print" @click="router.back()">‹ بازگشت</button>

    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-28 rounded-card" />
      <Skeleton class="h-72 rounded-card" />
    </div>

    <template v-else-if="deal">
      <!-- Header -->
      <div class="bg-panel text-white rounded-card p-5">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <span class="w-2.5 h-2.5 rounded-full" :class="statusClass[deal.status]"></span>
              <span class="text-xs text-white/70">{{ deal.status_display }} · {{ deal.stage_name }}</span>
            </div>
            <h1 class="text-xl font-bold mt-1">{{ deal.title }}</h1>
            <button
              class="text-sm text-white/70 hover:text-white hover:underline mt-1"
              @click="router.push({ name: 'crm-customer', params: { id: deal.customer } })"
            >{{ deal.customer_name }} ›</button>
            <p class="text-xs text-white/60 mt-2">
              کارشناس {{ deal.owner_name }} · {{ deal.province_name }} · شیوه آشنایی {{ deal.source_name }}
            </p>
            <p v-if="deal.reason_name" class="text-xs text-red-300 mt-1">
              دلیل شکست: {{ deal.reason_name }}<span v-if="deal.lost_note"> — {{ deal.lost_note }}</span>
            </p>
          </div>
          <div class="text-left">
            <p class="text-xs text-white/60">مبلغ معامله</p>
            <p class="text-2xl font-bold">{{ rial(deal.amount_rial) }}</p>
            <p class="text-sm mt-1" :class="Number(deal.profit_rial) >= 0 ? 'text-emerald-300' : 'text-red-300'">
              سود {{ rial(deal.profit_rial) }} · حاشیه {{ pct(deal.margin_pct) }}
            </p>
          </div>
        </div>
      </div>

      <!-- Stage mover -->
      <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-1.5 no-print">
        <span class="text-xs text-slate-400 px-2">انتقال به مرحله:</span>
        <button
          v-for="s in crm.options?.stages" :key="s.id"
          class="text-xs rounded-lg px-2.5 py-1.5 transition disabled:opacity-40"
          :class="deal.stage === s.id ? 'bg-panel text-white' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'"
          :disabled="moving || deal.stage === s.id"
          @click="moveTo(s.id)"
        >{{ s.name_fa }}</button>
      </div>

      <div class="grid lg:grid-cols-3 gap-4">
        <!-- Lines + margin -->
        <div class="lg:col-span-2 space-y-4">
          <div class="bg-surface rounded-card shadow-soft overflow-hidden">
            <h3 class="text-sm font-semibold text-ink px-4 pt-4 pb-2">اقلام معامله و حاشیه سود هر ردیف</h3>
            <div class="overflow-x-auto">
              <table class="w-full text-sm min-w-[620px]">
                <thead>
                  <tr class="text-xs text-slate-400 bg-slate-50">
                    <th class="text-right font-medium px-4 py-2.5">محصول</th>
                    <th class="text-left font-medium px-3">تعداد</th>
                    <th class="text-left font-medium px-3">قیمت واحد</th>
                    <th class="text-left font-medium px-3">تخفیف</th>
                    <th class="text-left font-medium px-3">مبلغ</th>
                    <th class="text-left font-medium px-3">سود</th>
                    <th class="text-left font-medium px-4">حاشیه</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="i in items" :key="i.id" class="border-t border-slate-100">
                    <td class="px-4 py-2.5 text-ink">{{ i.product_name }}</td>
                    <td class="px-3 text-left text-slate-600">{{ num(Number(i.quantity)) }}</td>
                    <td class="px-3 text-left text-slate-600 whitespace-nowrap">{{ rial(i.unit_price_rial) }}</td>
                    <td class="px-3 text-left" :class="Number(i.discount_pct) ? 'text-amber-600' : 'text-slate-300'">
                      {{ Number(i.discount_pct) ? pct(i.discount_pct) : "—" }}
                    </td>
                    <td class="px-3 text-left text-ink whitespace-nowrap">{{ rial(i.line_total) }}</td>
                    <td class="px-3 text-left whitespace-nowrap" :class="Number(i.line_profit) >= 0 ? 'text-emerald-600' : 'text-red-500'">
                      {{ rial(i.line_profit) }}
                    </td>
                    <td class="px-4 text-left font-medium" :class="i.margin_pct >= 20 ? 'text-emerald-600' : i.margin_pct >= 10 ? 'text-amber-600' : 'text-red-500'">
                      {{ pct(i.margin_pct) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Why the profit is what it is -->
          <div :class="card">
            <h3 class="text-sm font-semibold text-ink mb-3">تحلیل سود این معامله</h3>
            <div class="space-y-2">
              <div v-for="r in costBreakdown" :key="r.label" class="flex items-center justify-between text-sm">
                <span class="text-slate-500">{{ r.label }}</span>
                <span :class="r.positive ? 'text-emerald-600' : 'text-red-500'">
                  {{ r.positive ? "" : "−" }}{{ rial(Math.abs(r.value)) }}
                </span>
              </div>
              <div class="flex items-center justify-between text-sm font-bold border-t border-slate-100 pt-2 mt-2">
                <span class="text-ink">سود خالص</span>
                <span :class="Number(deal.profit_rial) >= 0 ? 'text-emerald-600' : 'text-red-500'">{{ rial(deal.profit_rial) }}</span>
              </div>
            </div>
          </div>

          <!-- Activities -->
          <div :class="card">
            <h3 class="text-sm font-semibold text-ink mb-3">فعالیت‌های این معامله ({{ num(activities.length) }})</h3>
            <ol class="space-y-2 max-h-72 overflow-y-auto">
              <li v-for="a in activities" :key="a.id" class="flex items-baseline gap-2 text-sm">
                <span class="text-xs text-slate-400 w-24 shrink-0">{{ a.at_jalali }}</span>
                <span class="text-ink">{{ a.kind_display }}</span>
                <span class="text-xs text-slate-400">{{ a.note }}</span>
                <span class="text-[11px] text-slate-400 mr-auto">{{ a.result_display }}</span>
              </li>
              <li v-if="!activities.length" class="text-xs text-slate-400">فعالیتی ثبت نشده</li>
            </ol>
          </div>
        </div>

        <!-- Side: facts + stage history -->
        <div class="space-y-4">
          <div :class="card">
            <h3 class="text-sm font-semibold text-ink mb-3">مشخصات</h3>
            <dl class="text-sm space-y-2">
              <div class="flex justify-between"><dt class="text-slate-400">کد</dt><dd class="text-ink">{{ deal.code }}</dd></div>
              <div class="flex justify-between"><dt class="text-slate-400">تاریخ ایجاد</dt><dd class="text-ink">{{ deal.opened_jalali }}</dd></div>
              <div class="flex justify-between"><dt class="text-slate-400">تاریخ بسته شدن</dt><dd class="text-ink">{{ deal.closed_jalali || "—" }}</dd></div>
              <div class="flex justify-between"><dt class="text-slate-400">طول چرخه</dt><dd class="text-ink">{{ num(deal.age_days) }} روز</dd></div>
              <div class="flex justify-between"><dt class="text-slate-400">گروه مشتری</dt><dd class="text-ink">{{ deal.group_name }}</dd></div>
              <div class="flex justify-between"><dt class="text-slate-400">بهای تمام‌شده</dt><dd class="text-ink">{{ rial(deal.cost_rial) }}</dd></div>
            </dl>
          </div>

          <div :class="card">
            <h3 class="text-sm font-semibold text-ink mb-3">مسیر کاریز</h3>
            <ol class="relative border-r-2 border-slate-100 pr-4 space-y-3">
              <li v-for="h in history" :key="h.id" class="relative">
                <span class="absolute -right-[21px] top-1.5 w-2.5 h-2.5 rounded-full bg-violet-500 ring-2 ring-white"></span>
                <p class="text-sm text-ink">{{ h.to_name || "—" }}</p>
                <p class="text-xs text-slate-400">
                  {{ h.at_jalali }}
                  <span v-if="h.days_in_previous"> · {{ num(h.days_in_previous) }} روز در مرحله قبل</span>
                </p>
              </li>
              <li v-if="!history.length" class="text-xs text-slate-400">تاریخچه‌ای نیست</li>
            </ol>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
