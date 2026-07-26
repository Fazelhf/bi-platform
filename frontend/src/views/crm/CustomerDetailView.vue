<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { crmApi, type CrmActivity, type CrmCustomer, type Deal } from "@/api/crm";
import { num, pct, rial } from "@/utils/format";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/** پرونده مشتری — the 360° view: who they are, what they bought, every touch. */
const route = useRoute();
const router = useRouter();

const customer = ref<CrmCustomer | null>(null);
const deals = ref<Deal[]>([]);
const activities = ref<CrmActivity[]>([]);
const loading = ref(true);
const tab = ref<"timeline" | "deals">("timeline");

async function load() {
  loading.value = true;
  try {
    const id = Number(route.params.id);
    const [c, t] = await Promise.all([crmApi.customer(id), crmApi.customerTimeline(id)]);
    customer.value = c;
    deals.value = t.deals;
    activities.value = t.activities;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(() => route.params.id, load);

const stats = computed(() => customer.value?.stats ?? {});
const winRate = computed(() => {
  const w = Number(stats.value.won ?? 0);
  const l = Number(stats.value.lost ?? 0);
  return w + l ? (w / (w + l)) * 100 : 0;
});

const statusClass: Record<string, string> = {
  won: "bg-emerald-100 text-emerald-700",
  lost: "bg-red-100 text-red-600",
  open: "bg-amber-100 text-amber-700",
};
const resultDot: Record<string, string> = {
  success: "bg-emerald-500", no_answer: "bg-slate-300",
  follow_up: "bg-amber-500", failed: "bg-red-500",
};

const card = "bg-surface rounded-card shadow-soft p-4";
</script>

<template>
  <div class="space-y-4">
    <button class="text-sm text-slate-400 hover:text-ink no-print" @click="router.back()">‹ بازگشت</button>

    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-32 rounded-card" />
      <Skeleton class="h-80 rounded-card" />
    </div>

    <template v-else-if="customer">
      <!-- Header -->
      <div class="bg-panel text-white rounded-card p-5">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div class="min-w-0">
            <h1 class="text-xl font-bold">{{ customer.name_fa }}</h1>
            <p class="text-sm text-white/70 mt-1">
              {{ customer.group_name }} · {{ customer.province_name }}
              <span v-if="customer.city"> · {{ customer.city }}</span>
            </p>
            <p class="text-xs text-white/60 mt-2">
              کارشناس: {{ customer.owner_name }} · شیوه آشنایی: {{ customer.source_name }}
            </p>
          </div>
          <div class="text-sm text-white/80 space-y-0.5 text-left">
            <p v-if="customer.contact_name">{{ customer.contact_name }}</p>
            <p v-if="customer.mobile" dir="ltr">{{ customer.mobile }}</p>
            <p v-if="customer.phone" dir="ltr">{{ customer.phone }}</p>
          </div>
        </div>
      </div>

      <!-- Stats -->
      <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <div :class="card"><p class="text-xs text-slate-400">مجموع خرید</p><p class="text-lg font-bold text-ink mt-1">{{ rial(stats.revenue) }}</p></div>
        <div :class="card"><p class="text-xs text-slate-400">سود</p><p class="text-lg font-bold text-emerald-600 mt-1">{{ rial(stats.profit) }}</p></div>
        <div :class="card"><p class="text-xs text-slate-400">معاملات موفق</p><p class="text-lg font-bold text-ink mt-1">{{ num(stats.won) }}</p></div>
        <div :class="card"><p class="text-xs text-slate-400">نرخ موفقیت</p><p class="text-lg font-bold text-ink mt-1">{{ pct(winRate) }}</p></div>
        <div :class="card"><p class="text-xs text-slate-400">تماس‌ها</p><p class="text-lg font-bold text-ink mt-1">{{ num(stats.calls) }}</p></div>
        <div :class="card"><p class="text-xs text-slate-400">کار باز</p><p class="text-lg font-bold" :class="Number(stats.open_tasks) ? 'text-amber-600' : 'text-ink'">{{ num(stats.open_tasks) }}</p></div>
      </div>

      <!-- Tabs -->
      <div class="bg-surface rounded-card shadow-soft">
        <div class="flex gap-1 p-2 border-b border-slate-100">
          <button
            class="text-sm rounded-xl px-4 py-2" :class="tab === 'timeline' ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
            @click="tab = 'timeline'"
          >کارنامه فعالیت‌ها ({{ num(activities.length) }})</button>
          <button
            class="text-sm rounded-xl px-4 py-2" :class="tab === 'deals' ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
            @click="tab = 'deals'"
          >معاملات ({{ num(deals.length) }})</button>
        </div>

        <!-- Timeline -->
        <div v-if="tab === 'timeline'" class="p-4 max-h-[560px] overflow-y-auto">
          <EmptyState v-if="!activities.length" title="فعالیتی ثبت نشده" />
          <ol v-else class="relative border-r-2 border-slate-100 pr-4 space-y-4">
            <li v-for="a in activities" :key="a.id" class="relative">
              <span class="absolute -right-[21px] top-1.5 w-2.5 h-2.5 rounded-full ring-2 ring-white" :class="resultDot[a.result]"></span>
              <div class="flex flex-wrap items-baseline gap-x-2">
                <span class="text-sm font-medium text-ink">{{ a.kind_display }}</span>
                <span class="text-xs text-slate-400">{{ a.at_jalali }}</span>
                <span class="text-xs text-slate-400">· {{ a.owner_name }}</span>
                <span class="text-[11px] rounded-full px-2 py-0.5 bg-slate-100 text-slate-500">{{ a.result_display }}</span>
              </div>
              <p v-if="a.note" class="text-xs text-slate-500 mt-0.5">{{ a.note }}</p>
              <p v-if="a.deal_title" class="text-[11px] text-slate-400 mt-0.5">معامله: {{ a.deal_title }}</p>
            </li>
          </ol>
        </div>

        <!-- Deals -->
        <div v-else class="overflow-x-auto">
          <EmptyState v-if="!deals.length" title="معامله‌ای ثبت نشده" />
          <table v-else class="w-full text-sm min-w-[620px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">معامله</th>
                <th class="text-right font-medium px-3">مرحله</th>
                <th class="text-right font-medium px-3">وضعیت</th>
                <th class="text-left font-medium px-3">مبلغ</th>
                <th class="text-left font-medium px-3">سود</th>
                <th class="text-right font-medium px-4">تاریخ</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="d in deals" :key="d.id"
                class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                @click="router.push({ name: 'crm-deal', params: { id: d.id } })"
              >
                <td class="px-4 py-2.5 text-ink">{{ d.title }}</td>
                <td class="px-3 text-slate-500">{{ d.stage_name }}</td>
                <td class="px-3">
                  <span class="text-[11px] rounded-full px-2 py-0.5" :class="statusClass[d.status]">{{ d.status_display }}</span>
                  <span v-if="d.reason_name" class="text-[11px] text-red-400 block mt-0.5">{{ d.reason_name }}</span>
                </td>
                <td class="px-3 text-left text-ink whitespace-nowrap">{{ rial(d.amount_rial) }}</td>
                <td class="px-3 text-left whitespace-nowrap" :class="Number(d.profit_rial) >= 0 ? 'text-emerald-600' : 'text-red-500'">{{ rial(d.profit_rial) }}</td>
                <td class="px-4 text-xs text-slate-400 whitespace-nowrap">{{ d.closed_jalali || d.opened_jalali }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
