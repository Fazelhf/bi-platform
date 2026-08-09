<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { crmApi, type CrmDashboard, type DashCard, type ReportRow } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num, pct, rial } from "@/utils/format";
import CrmChart from "@/components/crm/CrmChart.vue";
import CrmFilterBar from "@/components/crm/CrmFilterBar.vue";
import CustomerForm from "@/components/crm/CustomerForm.vue";
import DealForm from "@/components/crm/DealForm.vue";
import ActivityForm from "@/components/crm/ActivityForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import SectionBoard from "@/components/boards/SectionBoard.vue";

/**
 * داشبورد CRM — the home screen.
 *
 * Every tile and every bar is clickable: the click opens the records behind
 * the figure. That is the whole difference from the tool this replaces, where
 * the same widgets existed but dead-ended.
 */
const crm = useCrmStore();
const router = useRouter();
const data = ref<CrmDashboard | null>(null);
const loading = ref(true);

async function load() {
  loading.value = true;
  try {
    data.value = await crmApi.dashboard(crm.query);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await crm.loadOptions(); await load(); });
watch(() => crm.query, load, { deep: true });

function cardValue(c: DashCard): string {
  if (c.unit === "rial") return rial(c.value);
  if (c.unit === "percent") return pct(c.value);
  if (c.unit === "days") return `${num(c.value)} روز`;
  return num(c.value);
}

function cardSub(c: DashCard): string {
  const s = c.sub ?? {};
  if (s.amount !== undefined) return rial(s.amount);
  if (s.margin_pct !== undefined) return `حاشیه ${pct(s.margin_pct)}`;
  if (s.won !== undefined) return `${num(s.won)} از ${num(s.closed)} معامله بسته‌شده`;
  if (s.calls !== undefined) return `${num(s.success)} موفق از ${num(s.calls)} تماس`;
  if (s.count !== undefined) return `${num(s.count)} معامله · وزنی ${rial(s.weighted ?? 0)}`;
  return "";
}

const CARD_STYLE: Record<string, { accent: string; icon: string }> = {
  incoming: { accent: "text-sky-600", icon: "M12 5v14M5 12h14" },
  won: { accent: "text-emerald-600", icon: "M20 6L9 17l-5-5" },
  lost: { accent: "text-red-500", icon: "M18 6L6 18M6 6l12 12" },
  profit: { accent: "text-emerald-600", icon: "M3 17l6-6 4 4 7-7" },
  pipeline: { accent: "text-violet-600", icon: "M4 6h16M7 12h10M10 18h4" },
  conversion: { accent: "text-amber-600", icon: "M4 4v16h16" },
  velocity: { accent: "text-sky-600", icon: "M12 8v4l3 2" },
  new_customers: { accent: "text-teal-600", icon: "M16 21v-2a4 4 0 00-8 0v2M12 3a4 4 0 100 8 4 4 0 000-8z" },
  calls: { accent: "text-indigo-600", icon: "M22 16.9v3a2 2 0 01-2.2 2 19.8 19.8 0 01-8.6-3 19.5 19.5 0 01-6-6A19.8 19.8 0 012.1 4.2 2 2 0 014.1 2h3a2 2 0 012 1.7l.6 2.5a2 2 0 01-.5 1.9L8 9.3a16 16 0 006 6l1.2-1.2a2 2 0 011.9-.5l2.5.6a2 2 0 011.7 2z" },
  overdue: { accent: "text-orange-600", icon: "M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" },
};

function openCard(c: DashCard) {
  if (c.drill?.kind) crm.openDrill(c.drill, c.label);
  else if (c.key === "overdue") router.push({ name: "crm-activities", query: { tab: "tasks" } });
}

function openRow(rows: ReportRow[], i: number, title: string) {
  const row = rows[i];
  if (row?.drill?.kind) crm.openDrill(row.drill, `${title} — ${row.label}`);
}

// ---- chart data -----------------------------------------------------------
const trendCats = computed(() => data.value?.trend.map((r) => r.label) ?? []);
const trendSeries = computed(() => [
  { name: "فروش موفق", values: data.value?.trend.map((r) => r.amount) ?? [], color: "#22c55e" },
  { name: "سود", values: data.value?.trend.map((r) => r.profit) ?? [], type: "line" as const, color: "#0ea5e9" },
]);

const incomingCats = computed(() => data.value?.incoming_trend.map((r) => r.label) ?? []);
const incomingSeries = computed(() => [
  { name: "موفق", values: data.value?.incoming_trend.map((r) => r.won_count) ?? [], stack: "s", color: "#22c55e" },
  { name: "جاری", values: data.value?.incoming_trend.map((r) => r.open_count) ?? [], stack: "s", color: "#f59e0b" },
  { name: "ناموفق", values: data.value?.incoming_trend.map((r) => r.lost_count) ?? [], stack: "s", color: "#ef4444" },
]);

const sellerCats = computed(() => data.value?.top_sellers.map((r) => r.label) ?? []);
const sellerSeries = computed(() => [
  { name: "فروش", values: data.value?.top_sellers.map((r) => r.amount) ?? [] },
]);

const funnelRows = computed(() => data.value?.funnel.filter((r) => r.kind === "open") ?? []);
const maxFunnel = computed(() => Math.max(...funnelRows.value.map((r) => r.count as number), 1));

const lostCats = computed(() => data.value?.lost_reasons.map((r) => r.label) ?? []);
const lostSeries = computed(() => [
  { name: "تعداد", values: data.value?.lost_reasons.map((r) => r.count) ?? [], color: "#ef4444" },
]);

const actCats = computed(() => data.value?.activities_by_kind.map((r) => r.label) ?? []);
const actSeries = computed(() => [
  { name: "تعداد", values: data.value?.activities_by_kind.map((r) => r.count) ?? [], color: "#6366f1" },
]);

const activeCats = computed(() => data.value?.top_active.map((r) => r.label) ?? []);
const activeSeries = computed(() => [
  { name: "فعالیت", values: data.value?.top_active.map((r) => r.count) ?? [], color: "#14b8a6" },
]);

const newCustCats = computed(() => data.value?.new_customers_by_user.map((r) => r.label) ?? []);
const newCustSeries = computed(() => [
  { name: "مشتری جدید", values: data.value?.new_customers_by_user.map((r) => r.count) ?? [], color: "#0d9488" },
]);

const groupCats = computed(() => data.value?.by_group.map((r) => r.label) ?? []);
const groupSeries = computed(() => [
  { name: "فروش", values: data.value?.by_group.map((r) => r.amount) ?? [] },
]);

const card = "bg-surface rounded-card shadow-soft p-4";

// Quick entry straight from the home screen.
const modal = ref<"customer" | "deal" | "activity" | null>(null);
async function onSaved(id?: number) {
  const kind = modal.value;
  modal.value = null;
  if (kind === "deal" && id) {
    router.push({ name: "crm-deal", params: { id } });
    return;
  }
  if (kind === "customer" && id) {
    router.push({ name: "crm-customer", params: { id } });
    return;
  }
  await load();
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="crm.canEdit" class="flex flex-wrap items-center gap-2 no-print">
      <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm" @click="modal = 'activity'">ثبت فعالیت</button>
      <button class="bg-surface shadow-soft text-slate-600 hover:text-ink rounded-xl px-4 py-2 text-sm" @click="modal = 'deal'">+ فرصت فروش</button>
      <button class="bg-surface shadow-soft text-slate-600 hover:text-ink rounded-xl px-4 py-2 text-sm" @click="modal = 'customer'">+ مشتری</button>
      <span class="text-xs text-slate-400">
        {{ crm.me?.employee_name ? `ثبت به نام ${crm.me.employee_name}` : "" }}
      </span>
    </div>

    <CustomerForm v-if="modal === 'customer'" @close="modal = null" @saved="onSaved" />
    <DealForm v-if="modal === 'deal'" @close="modal = null" @saved="onSaved" />
    <ActivityForm v-if="modal === 'activity'" @close="modal = null" @saved="onSaved" />

    <CrmFilterBar />

    <!-- ============ KPI tiles ============ -->
    <div v-if="loading" class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
      <Skeleton v-for="i in 10" :key="i" class="h-24 rounded-card" />
    </div>
    <div v-else class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
      <button
        v-for="c in data?.cards" :key="c.key"
        class="bg-surface rounded-card shadow-soft p-4 text-right transition hover:shadow-pop hover:-translate-y-0.5 group"
        :class="c.drill?.kind || c.key === 'overdue' ? 'cursor-pointer' : 'cursor-default'"
        @click="openCard(c)"
      >
        <div class="flex items-start justify-between gap-2">
          <p class="text-xs text-slate-400">{{ c.label }}</p>
          <svg
            class="w-4 h-4 shrink-0 opacity-60" :class="CARD_STYLE[c.key]?.accent"
            viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round"
          ><path :d="CARD_STYLE[c.key]?.icon" /></svg>
        </div>
        <p class="text-xl font-bold mt-1.5" :class="CARD_STYLE[c.key]?.accent ?? 'text-ink'">
          {{ cardValue(c) }}
        </p>
        <p class="text-[11px] text-slate-400 mt-0.5 truncate">{{ cardSub(c) }}</p>
        <p v-if="c.drill?.kind" class="text-[10px] text-slate-300 mt-1 group-hover:text-slate-400">
          برای دیدن ریز اطلاعات کلیک کنید
        </p>
      </button>
    </div>

    <!-- ============ Trend + incoming ============ -->
    <div class="grid lg:grid-cols-2 gap-4">
      <div :class="card">
        <h3 class="text-sm font-semibold text-ink mb-2">روند فروش و سود</h3>
        <CrmChart
          :categories="trendCats" :series="trendSeries" format="rial" :height="270"
          @pick="(i) => openRow(data!.trend, i, 'فروش موفق')"
        />
      </div>
      <div :class="card">
        <h3 class="text-sm font-semibold text-ink mb-2">فرصت‌های جدید به تفکیک وضعیت</h3>
        <CrmChart
          :categories="incomingCats" :series="incomingSeries" format="count" :height="270"
          @pick="(i) => openRow(data!.incoming_trend, i, 'فرصت‌های جدید')"
        />
      </div>
    </div>

    <!-- ============ Sellers / funnel ============ -->
    <div class="grid lg:grid-cols-3 gap-4">
      <div :class="card" class="lg:col-span-2">
        <h3 class="text-sm font-semibold text-ink mb-2">بهترین فروشنده‌ها</h3>
        <CrmChart
          :categories="sellerCats" :series="sellerSeries" format="rial" :height="240" horizontal
          @pick="(i) => openRow(data!.top_sellers, i, 'فروش کارشناس')"
        />
      </div>

      <div :class="card">
        <h3 class="text-sm font-semibold text-ink mb-3">قیف فروش</h3>
        <div v-if="!funnelRows.length" class="text-xs text-slate-400">داده‌ای نیست</div>
        <div v-else class="space-y-2">
          <button
            v-for="s in funnelRows" :key="String(s.id)"
            class="w-full text-right group"
            @click="crm.openDrill(s.drill!, `مرحله فروش — ${s.label}`)"
          >
            <div class="flex items-center justify-between text-xs mb-1">
              <span class="text-slate-500 truncate">{{ s.label }}</span>
              <span class="text-ink font-medium shrink-0">{{ num(s.count) }}</span>
            </div>
            <div class="h-2 bg-slate-100 rounded-full overflow-hidden">
              <div
                class="h-full rounded-full transition-all group-hover:opacity-80"
                :style="{ width: `${Math.max((s.count / maxFunnel) * 100, 2)}%`, background: '#8b5cf6' }"
              ></div>
            </div>
          </button>
        </div>
      </div>
    </div>

    <!-- ============ Lost reasons / activities / sources ============ -->
    <div class="grid lg:grid-cols-3 gap-4">
      <div :class="card">
        <h3 class="text-sm font-semibold text-ink mb-2">اصلی‌ترین دلایل از دست رفتن</h3>
        <CrmChart
          v-if="lostCats.length" :categories="lostCats" :series="lostSeries"
          format="count" :height="230" horizontal
          @pick="(i) => openRow(data!.lost_reasons, i, 'دلیل از دست رفتن')"
        />
        <EmptyState v-else title="معامله شکست‌خورده‌ای نیست" />
      </div>

      <div :class="card">
        <h3 class="text-sm font-semibold text-ink mb-2">فعالیت‌های انجام شده</h3>
        <CrmChart
          :categories="actCats" :series="actSeries" format="count" :height="230" horizontal
          @pick="(i) => openRow(data!.activities_by_kind, i, 'فعالیت')"
        />
      </div>

      <div :class="card">
        <h3 class="text-sm font-semibold text-ink mb-3">بهترین منابع سرنخ</h3>
        <table class="w-full text-xs">
          <thead>
            <tr class="text-slate-400">
              <th class="text-right font-medium pb-2">شیوه</th>
              <th class="text-left font-medium pb-2">فروش</th>
              <th class="text-left font-medium pb-2">تبدیل</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in data?.sources" :key="String(s.id)"
              class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
              @click="crm.openDrill(s.drill!, `منبع سرنخ — ${s.label}`)"
            >
              <td class="py-2 text-slate-600">{{ s.label }}</td>
              <td class="py-2 text-left text-ink whitespace-nowrap">{{ rial(s.amount) }}</td>
              <td class="py-2 text-left" :class="s.conversion_pct >= 40 ? 'text-emerald-600' : 'text-slate-500'">
                {{ pct(s.conversion_pct) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ============ People ============ -->
    <div class="grid lg:grid-cols-3 gap-4">
      <div :class="card">
        <h3 class="text-sm font-semibold text-ink mb-2">فعال‌ترین کارشناسان</h3>
        <CrmChart
          :categories="activeCats" :series="activeSeries" format="count" :height="220" horizontal
          @pick="(i) => openRow(data!.top_active, i, 'فعالیت‌های')"
        />
      </div>

      <div :class="card">
        <h3 class="text-sm font-semibold text-ink mb-2">مشتریان جدید بر اساس کارشناس</h3>
        <CrmChart
          :categories="newCustCats" :series="newCustSeries" format="count" :height="220" horizontal
          @pick="(i) => openRow(data!.new_customers_by_user, i, 'مشتریان جدید')"
        />
      </div>

      <div :class="card">
        <h3 class="text-sm font-semibold text-ink mb-3">رضایت مشتری از کارشناسان</h3>
        <table class="w-full text-xs">
          <thead>
            <tr class="text-slate-400">
              <th class="text-right font-medium pb-2">کارشناس</th>
              <th class="text-left font-medium pb-2">میانگین</th>
              <th class="text-left font-medium pb-2">ناراضی</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in data?.satisfaction" :key="String(s.id)"
              class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
              @click="crm.openDrill(s.drill!, `بازخورد — ${s.label}`)"
            >
              <td class="py-2 text-slate-600">{{ s.label }}</td>
              <td class="py-2 text-left text-ink">{{ num(s.avg_score) }}</td>
              <td class="py-2 text-left" :class="s.unhappy ? 'text-red-500 font-medium' : 'text-slate-400'">
                {{ num(s.unhappy) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ============ Geography + segments ============ -->
    <div class="grid lg:grid-cols-2 gap-4">
      <div :class="card">
        <h3 class="text-sm font-semibold text-ink mb-3">فروش و تارگت استان‌ها</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-xs min-w-[420px]">
            <thead>
              <tr class="text-slate-400">
                <th class="text-right font-medium pb-2">استان</th>
                <th class="text-right font-medium pb-2">کارشناس</th>
                <th class="text-left font-medium pb-2">فروش</th>
                <th class="text-left font-medium pb-2">تارگت</th>
                <th class="text-left font-medium pb-2">تحقق</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="p in data?.provinces" :key="String(p.id)"
                class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                @click="crm.openDrill(p.drill!, `فروش استان ${p.label}`)"
              >
                <td class="py-2 text-ink">{{ p.label }}</td>
                <td class="py-2 text-slate-500 truncate max-w-[130px]">{{ p.owner_label }}</td>
                <td class="py-2 text-left text-ink whitespace-nowrap">{{ rial(p.amount) }}</td>
                <td class="py-2 text-left text-slate-400 whitespace-nowrap">{{ rial(p.target) }}</td>
                <td class="py-2 text-left font-medium" :class="p.achievement_pct >= 100 ? 'text-emerald-600' : p.achievement_pct >= 70 ? 'text-amber-600' : 'text-red-500'">
                  {{ pct(p.achievement_pct) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div :class="card">
        <h3 class="text-sm font-semibold text-ink mb-2">فروش بر اساس گروه مشتری</h3>
        <CrmChart
          :categories="groupCats" :series="groupSeries" kind="pie" format="rial" :height="260"
          @pick="(i) => openRow(data!.by_group, i, 'گروه مشتری')"
        />
      </div>
    </div>
      <!-- گزارش این بخش، روی همین صفحه: داشبورد و گزارش یک صفحه‌اند. -->
    <SectionBoard section="crm" :period="null" />
</div>
</template>
