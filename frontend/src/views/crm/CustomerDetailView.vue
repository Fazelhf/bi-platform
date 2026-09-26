<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { crmApi, type CrmActivity, type CrmCustomer, type Deal } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num, pct, rial } from "@/utils/format";
import CustomerForm from "@/components/crm/CustomerForm.vue";
import DealForm from "@/components/crm/DealForm.vue";
import ActivityForm from "@/components/crm/ActivityForm.vue";
import TaskForm from "@/components/crm/TaskForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * پرونده مشتری — the 360° view: who they are, what they bought, every touch.
 *
 * The page answers the three questions a کارشناس has before calling: is this
 * relationship healthy (and why not), what have they bought and what do they
 * still owe, and what have we promised them. The health score always shows
 * its reasons — a number nobody can explain is a number nobody acts on.
 */
const route = useRoute();
const router = useRouter();
const crm = useCrmStore();

const customer = ref<CrmCustomer | null>(null);
const deals = ref<Deal[]>([]);
const activities = ref<CrmActivity[]>([]);
const loading = ref(true);
const tab = ref<"timeline" | "deals" | "invoices" | "tasks">("timeline");

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

onMounted(async () => { await crm.loadOptions(); await load(); });
watch(() => route.params.id, load);

// Entry forms opened from this page — all pre-bound to this customer.
const modal = ref<"customer" | "deal" | "activity" | "task" | null>(null);

async function onSaved(id?: number) {
  const wasEdit = modal.value === "customer";
  modal.value = null;
  // A deleted customer has nowhere to go back to.
  if (wasEdit && id === 0) {
    router.push({ name: "crm-customers" });
    return;
  }
  await load();
}

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

const insights = computed(() => customer.value?.insights ?? null);

const healthTone = computed(() => {
  const s = insights.value?.health.score ?? 0;
  return s >= 70 ? "good" : s >= 40 ? "warn" : "bad";
});
const HEALTH_RING: Record<string, string> = { good: "#34d399", warn: "#fbbf24", bad: "#f87171" };
const REASON_DOT: Record<string, string> = { good: "bg-emerald-500", warn: "bg-amber-500", bad: "bg-red-500" };

/** The twelve-month bars share one scale, so a quiet month looks quiet. */
const seriesMax = computed(() =>
  Math.max(1, ...(insights.value?.series ?? []).map((m) => Math.max(m.won, m.invoiced))),
);

function since(days: number | null | undefined, never: string): string {
  if (days === null || days === undefined) return never;
  if (days < 1) return "امروز";
  return `${num(days)} روز پیش`;
}

async function completeTask(id: number) {
  await crmApi.completeTask(id);
  await load();
}

const card = "bg-surface rounded-card shadow-soft p-4";
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center gap-2 no-print">
      <button class="text-sm text-slate-400 hover:text-ink" @click="router.back()">‹ بازگشت</button>
      <span class="flex-1"></span>
      <template v-if="crm.canEdit && customer">
        <button class="text-sm bg-panel text-white rounded-xl px-3 py-1.5" @click="modal = 'activity'">ثبت فعالیت</button>
        <button class="text-sm bg-slate-100 text-slate-600 hover:bg-slate-200 rounded-xl px-3 py-1.5" @click="modal = 'deal'">معامله جدید</button>
        <button class="text-sm bg-slate-100 text-slate-600 hover:bg-slate-200 rounded-xl px-3 py-1.5" @click="modal = 'task'">کار جدید</button>
        <button class="text-sm bg-slate-100 text-slate-600 hover:bg-slate-200 rounded-xl px-3 py-1.5" @click="modal = 'customer'">ویرایش</button>
      </template>
    </div>

    <CustomerForm v-if="modal === 'customer'" :customer="customer" @close="modal = null" @saved="onSaved" />
    <DealForm v-if="modal === 'deal'" :customer-id="customer!.id" @close="modal = null" @saved="onSaved" />
    <ActivityForm
      v-if="modal === 'activity'" :customer-id="customer!.id" :customer-label="customer!.name_fa"
      @close="modal = null" @saved="onSaved"
    />
    <TaskForm
      v-if="modal === 'task'" :customer-id="customer!.id" :customer-label="customer!.name_fa"
      @close="modal = null" @saved="onSaved"
    />

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
              کارشناس: {{ customer.owner_name }} · منبع سرنخ: {{ customer.source_name }}
            </p>
          </div>
          <div class="flex items-center gap-5">
            <div class="text-sm text-white/80 space-y-0.5 text-left">
              <p v-if="customer.contact_name">{{ customer.contact_name }}</p>
              <!-- tel: links — on a phone, a tap is the call. -->
              <a v-if="customer.mobile" :href="`tel:${customer.mobile}`" dir="ltr" class="block hover:text-white hover:underline">{{ customer.mobile }}</a>
              <a v-if="customer.phone" :href="`tel:${customer.phone}`" dir="ltr" class="block hover:text-white hover:underline">{{ customer.phone }}</a>
            </div>

            <div v-if="insights" class="flex items-center gap-3 shrink-0" :title="insights.health.reasons.map((r) => r.text).join('\n')">
              <div class="relative w-16 h-16">
                <svg viewBox="0 0 64 64" class="w-full h-full -rotate-90">
                  <circle cx="32" cy="32" r="27" fill="none" stroke="rgba(255,255,255,.12)" stroke-width="6" />
                  <circle cx="32" cy="32" r="27" fill="none" :stroke="HEALTH_RING[healthTone]" stroke-width="6" stroke-linecap="round"
                          :stroke-dasharray="2 * Math.PI * 27" :stroke-dashoffset="2 * Math.PI * 27 * (1 - insights.health.score / 100)" />
                </svg>
                <span class="absolute inset-0 flex items-center justify-center text-base font-extrabold ltr-nums">{{ num(insights.health.score) }}</span>
              </div>
              <div>
                <p class="text-[11px] text-white/50">سلامت رابطه</p>
                <p class="text-sm font-semibold">{{ insights.health.label }}</p>
              </div>
            </div>
          </div>
        </div>

        <!-- Why the score is what it is -->
        <div v-if="insights?.health.reasons.length" class="flex flex-wrap gap-2 mt-4">
          <span
            v-for="(r, i) in insights.health.reasons" :key="i"
            class="inline-flex items-center gap-1.5 text-[11px] bg-white/10 rounded-full px-2.5 py-1"
          >
            <span class="w-1.5 h-1.5 rounded-full" :class="REASON_DOT[r.tone]"></span>{{ r.text }}
          </span>
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

      <div v-if="insights" class="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <!-- Accounting's view of the customer -->
        <div :class="card" class="grid grid-cols-2 gap-3">
          <div>
            <p class="text-xs text-slate-400">فاکتور شده (آرپا)</p>
            <p class="text-lg font-bold text-ink ltr-nums mt-1">{{ rial(insights.invoiced) }}</p>
            <p class="text-[11px] text-slate-400">{{ num(insights.invoice_count) }} فاکتور<template v-if="insights.last_invoice"> · آخرین {{ insights.last_invoice }}</template></p>
          </div>
          <div>
            <p class="text-xs text-slate-400">مانده تسویه‌نشده</p>
            <p class="text-lg font-bold ltr-nums mt-1" :class="insights.unsettled ? 'text-amber-600' : 'text-emerald-600'">{{ rial(insights.unsettled) }}</p>
            <p v-if="insights.overdue_debt" class="text-[11px] text-red-600">سررسیدگذشته {{ rial(insights.overdue_debt) }}</p>
            <p v-else class="text-[11px] text-slate-400">بدون بدهی سررسیدگذشته</p>
          </div>
          <div class="col-span-2 grid grid-cols-2 gap-3 pt-3 border-t border-slate-100">
            <div>
              <p class="text-[11px] text-slate-400">آخرین تماس</p>
              <p class="text-sm font-semibold" :class="(insights.days_quiet ?? 999) > 60 ? 'text-red-600' : 'text-ink'">{{ since(insights.days_quiet, "ثبت نشده") }}</p>
            </div>
            <div>
              <p class="text-[11px] text-slate-400">آخرین خرید</p>
              <p class="text-sm font-semibold text-ink">{{ since(insights.days_since_buy, "ندارد") }}</p>
            </div>
          </div>
        </div>

        <!-- Twelve months of buying -->
        <div :class="card" class="lg:col-span-2">
          <div class="flex items-center justify-between mb-3">
            <p class="text-sm font-semibold text-ink">خرید دوازده ماه اخیر</p>
            <div class="flex items-center gap-3 text-[11px] text-slate-400">
              <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-emerald-500"></span>معامله موفق</span>
              <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-sky-400"></span>فاکتور</span>
              <span>· {{ num(insights.active_months) }} ماه فعال</span>
            </div>
          </div>
          <div class="flex items-end gap-1.5 h-32">
            <div v-for="m in insights.series" :key="m.label" class="flex-1 flex flex-col items-center gap-1 min-w-0 group">
              <div class="w-full flex items-end justify-center gap-0.5 h-24" :title="`${m.label}\nمعامله: ${rial(m.won)}\nفاکتور: ${rial(m.invoiced)}`">
                <div class="w-1/2 max-w-[10px] rounded-t bg-emerald-500 transition-all" :style="{ height: Math.max(m.won ? 3 : 0, (m.won / seriesMax) * 100) + '%' }"></div>
                <div class="w-1/2 max-w-[10px] rounded-t bg-sky-400 transition-all" :style="{ height: Math.max(m.invoiced ? 3 : 0, (m.invoiced / seriesMax) * 100) + '%' }"></div>
              </div>
              <span class="text-[9px] text-slate-400 truncate w-full text-center">{{ m.label.split(" ")[0] }}</span>
            </div>
          </div>
        </div>
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
          <button
            v-if="insights"
            class="text-sm rounded-xl px-4 py-2" :class="tab === 'invoices' ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
            @click="tab = 'invoices'"
          >فاکتورها ({{ num(insights.invoice_count) }})</button>
          <button
            v-if="insights"
            class="text-sm rounded-xl px-4 py-2" :class="tab === 'tasks' ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
            @click="tab = 'tasks'"
          >کارهای باز ({{ num(insights.tasks.length) }})</button>
        </div>

        <!-- Invoices -->
        <div v-if="tab === 'invoices' && insights" class="overflow-x-auto">
          <EmptyState v-if="!insights.invoices.length" title="فاکتوری برای این مشتری ثبت نشده" />
          <table v-else class="w-full text-sm min-w-[620px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">شماره</th>
                <th class="text-right font-medium px-3">نوع</th>
                <th class="text-right font-medium px-3">تاریخ</th>
                <th class="text-left font-medium px-3">مبلغ</th>
                <th class="text-left font-medium px-3">تسویه‌نشده</th>
                <th class="text-right font-medium px-4">معامله</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="inv in insights.invoices" :key="inv.id" class="border-t border-slate-100">
                <td class="px-4 py-2.5 text-ink ltr-nums">{{ inv.number }}</td>
                <td class="px-3 text-xs" :class="inv.kind === 'return' ? 'text-red-500' : 'text-slate-500'">{{ inv.kind_display }}</td>
                <td class="px-3 text-xs text-slate-400 whitespace-nowrap">{{ inv.issued_jalali }}</td>
                <td class="px-3 text-left text-ink whitespace-nowrap ltr-nums">{{ rial(inv.amount_rial) }}</td>
                <td class="px-3 text-left whitespace-nowrap ltr-nums" :class="Number(inv.unsettled_rial) ? 'text-amber-600' : 'text-slate-300'">{{ Number(inv.unsettled_rial) ? rial(inv.unsettled_rial) : "—" }}</td>
                <td class="px-4 text-xs text-slate-500 truncate max-w-[200px]">
                  <button v-if="inv.deal" class="hover:underline" @click="router.push({ name: 'crm-deal', params: { id: inv.deal } })">{{ inv.deal_title }}</button>
                  <span v-else class="text-slate-300">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Open tasks -->
        <div v-else-if="tab === 'tasks' && insights" class="p-2">
          <EmptyState v-if="!insights.tasks.length" title="کار بازی برای این مشتری نیست" />
          <ul v-else class="divide-y divide-slate-100">
            <li v-for="t in insights.tasks" :key="t.id" class="px-3 py-3 flex items-center gap-3">
              <button
                v-if="crm.canEdit"
                class="w-5 h-5 rounded-md border border-slate-300 hover:border-emerald-500 hover:bg-emerald-50 shrink-0"
                title="انجام شد"
                @click="completeTask(t.id)"
              ></button>
              <div class="min-w-0 flex-1">
                <p class="text-sm text-ink truncate">{{ t.title }}</p>
                <p class="text-xs text-slate-400">{{ t.kind_display }}<template v-if="t.owner_name"> · {{ t.owner_name }}</template></p>
              </div>
              <span class="text-xs shrink-0 ltr-nums" :class="new Date(t.due_at) < new Date() ? 'text-red-600' : 'text-slate-400'">{{ t.due_jalali }}</span>
            </li>
          </ul>
        </div>

        <!-- Timeline -->
        <div v-else-if="tab === 'timeline'" class="p-4 max-h-[560px] overflow-y-auto">
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

        <!-- Deals. Sideways scroll only where the table shows — on a phone
             the cards below fit, and an overflow container there would just
             reintroduce the horizontal drag it exists to avoid. -->
        <div v-else-if="tab === 'deals'" class="md:overflow-x-auto">
          <EmptyState v-if="!deals.length" title="معامله‌ای ثبت نشده" />

          <!-- A card per deal on phones; see DealsView for the reasoning. -->
          <ul v-else class="md:hidden divide-y divide-slate-100">
            <li
              v-for="d in deals" :key="`m-${d.id}`"
              class="p-4 active:bg-slate-50 cursor-pointer"
              @click="router.push({ name: 'crm-deal', params: { id: d.id } })"
            >
              <div class="flex items-start justify-between gap-3">
                <p class="text-ink min-w-0 truncate">{{ d.title }}</p>
                <span class="text-[11px] rounded-full px-2 py-0.5 shrink-0" :class="statusClass[d.status]">
                  {{ d.status_display }}
                </span>
              </div>
              <div class="flex items-baseline gap-3 mt-2 flex-wrap">
                <span class="text-ink font-semibold ltr-nums">{{ rial(d.amount_rial) }}</span>
                <span class="text-xs ltr-nums" :class="Number(d.profit_rial) >= 0 ? 'text-emerald-600' : 'text-red-500'">
                  سود {{ rial(d.profit_rial) }}
                </span>
              </div>
              <div class="flex items-center justify-between gap-2 mt-1.5 text-xs text-slate-400">
                <span class="truncate">{{ d.stage_name }}</span>
                <span class="shrink-0 ltr-nums">{{ d.closed_jalali || d.opened_jalali }}</span>
              </div>
              <p v-if="d.reason_name" class="text-[11px] text-red-400 mt-1">{{ d.reason_name }}</p>
            </li>
          </ul>

          <table v-if="deals.length" class="hidden md:table w-full text-sm min-w-[620px]">
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
