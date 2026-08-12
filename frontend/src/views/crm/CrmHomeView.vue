<script setup lang="ts">
/**
 * میز کار — the first thing you see in CRM, and the only page built around
 * «حالا چه کنم» rather than «چطور پیش رفتیم».
 *
 * The آمار page already answers the second question with charts. Opening a
 * CRM onto charts is a quiet way of saying the tool is for reporting on the
 * salesperson rather than for helping them, so this page leads with the three
 * things that are actually waiting: calls that are late, deals nobody has
 * touched, and what is due this week.
 *
 * The module cards at the bottom exist because a workspace with no sidebar
 * needs one obvious place that lists everything in it — the tabs along the
 * top are for switching once you know where you are going.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { crmApi, type CrmWorkbench } from "@/api/crm";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import NavIcon from "@/components/NavIcon.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

const router = useRouter();
const { exact } = useMoney();

const data = ref<CrmWorkbench | null>(null);
const loading = ref(true);
const error = ref("");

const MODULES = [
  { name: "crm-customers", label: "مشتری‌ها", icon: "team",
    hint: "شرکت‌ها و اشخاصی که با آن‌ها کار می‌کنیم" },
  { name: "crm-deals", label: "معامله‌ها", icon: "box",
    hint: "هر خرید، از اولین تماس تا تسویه" },
  { name: "crm-pipeline", label: "کاریز فروش", icon: "target",
    hint: "معامله‌های باز، به تفکیک مرحله" },
  { name: "crm-activities", label: "پیگیری‌ها", icon: "notes",
    hint: "تماس‌ها، جلسه‌ها و یادداشت‌ها" },
  { name: "crm-dashboard", label: "آمار", icon: "grid",
    hint: "نمودار فروش، منابع و دلایل شکست" },
  { name: "crm-reports", label: "گزارش‌ها", icon: "chart",
    hint: "جدول‌های تفصیلی و خروجی اکسل" },
];

onMounted(async () => {
  await loadMoneySettings();
  try {
    data.value = await crmApi.workbench();
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
});

function tileValue(t: { value: number | string; unit?: string }): string {
  return t.unit === "rial" ? exact(t.value as string, true) : num(t.value as number);
}

const hasWork = computed(
  () => !!(data.value?.overdue.length || data.value?.due_soon.length),
);

function openCustomer(id: number) {
  router.push({ name: "crm-customer", params: { id } });
}
function openDeal(id: number) {
  router.push({ name: "crm-deal", params: { id } });
}
</script>

<template>
  <div class="space-y-5">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-24 rounded-card" />
      <Skeleton class="h-56 rounded-card" />
    </div>

    <p
      v-else-if="error"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3 whitespace-pre-line"
    >{{ error }}</p>

    <template v-else-if="data">
      <!-- Greeting + the four numbers worth knowing before anything else -->
      <div class="bg-surface rounded-card shadow-soft p-4 sm:p-5">
        <div class="flex flex-wrap items-baseline justify-between gap-2 mb-4">
          <h2 class="text-lg font-bold text-ink">
            سلام، {{ data.greeting_name }}
          </h2>
          <span class="text-xs text-slate-400">{{ data.scope }}</span>
        </div>

        <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div
            v-for="t in data.tiles" :key="t.key"
            class="rounded-2xl px-4 py-3"
            :class="t.tone === 'warn' && Number(t.value) > 0
              ? 'bg-amber-50' : 'bg-slate-50'"
          >
            <p class="text-xs text-slate-500">{{ t.label }}</p>
            <p
              class="text-xl font-bold ltr-nums mt-0.5"
              :class="t.tone === 'warn' && Number(t.value) > 0
                ? 'text-amber-700' : 'text-ink'"
            >{{ tileValue(t) }}</p>
          </div>
        </div>
      </div>

      <div class="grid lg:grid-cols-2 gap-4">
        <!-- What is late, and what is due -->
        <div class="bg-surface rounded-card shadow-soft overflow-hidden">
          <div class="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <h3 class="font-bold text-ink text-sm">کارهای من</h3>
            <button
              class="text-xs text-slate-400 hover:text-ink"
              @click="router.push({ name: 'crm-activities' })"
            >همه‌ی پیگیری‌ها</button>
          </div>

          <EmptyState
            v-if="!hasWork"
            title="چیزی عقب نیفتاده"
            hint="هر پیگیری که ثبت کنید و انجام نشود، اینجا می‌آید."
          />

          <div v-else class="divide-y divide-slate-100 max-h-[26rem] overflow-y-auto">
            <button
              v-for="t in data.overdue" :key="'o' + t.id"
              class="w-full text-right px-4 py-3 hover:bg-slate-50 flex items-start gap-3"
              @click="t.deal_id ? openDeal(t.deal_id) : openCustomer(t.customer_id)"
            >
              <span class="mt-0.5 shrink-0 w-2 h-2 rounded-full bg-amber-500"></span>
              <span class="min-w-0 flex-1">
                <span class="block text-sm text-ink truncate">{{ t.title }}</span>
                <span class="block text-xs text-slate-400 truncate">
                  {{ t.customer }}
                  <span v-if="t.owner"> · {{ t.owner }}</span>
                </span>
              </span>
              <span class="text-xs text-amber-600 shrink-0 ltr-nums">
                {{ num(t.days_late) }} روز
              </span>
            </button>

            <button
              v-for="t in data.due_soon" :key="'s' + t.id"
              class="w-full text-right px-4 py-3 hover:bg-slate-50 flex items-start gap-3"
              @click="t.deal_id ? openDeal(t.deal_id) : openCustomer(t.customer_id)"
            >
              <span class="mt-0.5 shrink-0 w-2 h-2 rounded-full bg-slate-300"></span>
              <span class="min-w-0 flex-1">
                <span class="block text-sm text-ink truncate">{{ t.title }}</span>
                <span class="block text-xs text-slate-400 truncate">{{ t.customer }}</span>
              </span>
              <span class="text-xs text-slate-400 shrink-0 ltr-nums">
                {{ faDate(t.due_at) }}
              </span>
            </button>
          </div>
        </div>

        <!-- Open deals nobody has touched -->
        <div class="bg-surface rounded-card shadow-soft overflow-hidden">
          <div class="px-4 py-3 border-b border-slate-100">
            <h3 class="font-bold text-ink text-sm">معامله‌های بی‌خبر</h3>
            <p class="text-xs text-slate-400 mt-0.5">
              باز هستند و بیش از سه هفته است کسی سراغشان نرفته
            </p>
          </div>

          <EmptyState
            v-if="!data.stale_deals.length"
            title="همه‌ی معامله‌های باز تازه‌اند"
          />

          <div v-else class="divide-y divide-slate-100 max-h-[26rem] overflow-y-auto">
            <button
              v-for="d in data.stale_deals" :key="d.id"
              class="w-full text-right px-4 py-3 hover:bg-slate-50"
              @click="openDeal(d.id)"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <p class="text-sm text-ink truncate">{{ d.customer }}</p>
                  <p class="text-xs text-slate-400 truncate">
                    {{ d.stage }}
                    <span v-if="d.owner"> · {{ d.owner }}</span>
                  </p>
                </div>
                <div class="text-left shrink-0">
                  <p class="text-sm text-ink ltr-nums">
                    {{ exact(d.amount_rial, true) }}
                  </p>
                  <p class="text-xs text-slate-400 ltr-nums">
                    {{ num(d.quiet_days) }} روز سکوت
                  </p>
                </div>
              </div>
            </button>
          </div>
        </div>
      </div>

      <!-- The map of the workspace, for when the tabs are not enough -->
      <div>
        <p class="text-xs text-slate-400 px-1 mb-2">بخش‌های CRM</p>
        <div class="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <button
            v-for="m in MODULES" :key="m.name"
            class="bg-surface rounded-card shadow-soft p-4 text-right hover:shadow-pop
                   transition-shadow flex items-start gap-3"
            @click="router.push({ name: m.name })"
          >
            <span class="w-10 h-10 rounded-2xl bg-slate-100 grid place-items-center shrink-0 text-slate-500">
              <NavIcon :name="m.icon" :size="20" />
            </span>
            <span class="min-w-0">
              <span class="block font-medium text-ink text-sm">{{ m.label }}</span>
              <span class="block text-xs text-slate-400 mt-0.5">{{ m.hint }}</span>
            </span>
          </button>
        </div>
      </div>

      <!-- Latest movement, so the page shows life even on a quiet day -->
      <div v-if="data.recent.length" class="bg-surface rounded-card shadow-soft overflow-hidden">
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          آخرین اتفاق‌ها
        </h3>
        <div class="divide-y divide-slate-100">
          <button
            v-for="a in data.recent" :key="a.id"
            class="w-full text-right px-4 py-2.5 hover:bg-slate-50 flex items-center gap-3"
            @click="openCustomer(a.customer_id)"
          >
            <span class="text-xs text-slate-400 shrink-0 w-20 ltr-nums">
              {{ faDate(a.at) }}
            </span>
            <span class="text-xs bg-slate-100 text-slate-500 rounded-full px-2 py-0.5 shrink-0">
              {{ a.kind }}
            </span>
            <span class="text-sm text-ink truncate flex-1">{{ a.customer }}</span>
            <span class="text-xs text-slate-400 truncate hidden sm:block max-w-[16rem]">
              {{ a.note }}
            </span>
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
