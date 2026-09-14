<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { inboxApi, type SalesSheet } from "@/api/platform";
import { useAuthStore } from "@/stores/auth";
import { toast, prompt } from "@/composables/useUi";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import { num, rial } from "@/utils/format";

/**
 * کارتابل تایید اطلاعات.
 *
 * Sales arrives as *sheets*: one item per channel and period, holding every
 * salesperson and every province entered for it. That is how a manager
 * enters it and how it has to be judged — a week's provincial split only
 * means something next to the salesperson figures it splits, so the two are
 * approved, returned or rejected together. Whether an item is a week or a
 * month is simply the grain the period was entered at.
 */
const auth = useAuthStore();
const sheets = ref<SalesSheet[]>([]);
const production = ref<any[]>([]);
const loading = ref(true);
const busy = ref<string>("");
const salesPreview = ref<SalesSheet | null>(null);
const productionPreview = ref<any | null>(null);

// A manager only sees their own section (the server already scopes sales
// sheets); only the CEO can actually decide.
const visibleProduction = computed(() =>
  auth.isExecutive || auth.department === "production" ? production.value : [],
);
const totalPending = computed(() => sheets.value.length + visibleProduction.value.length);

async function load() {
  loading.value = true;
  try {
    [sheets.value, production.value] = await Promise.all([
      inboxApi.salesSheets(),
      inboxApi.pendingProduction(),
    ]);
  } finally {
    loading.value = false;
  }
}

type Action = "approve" | "reject" | "request-revision";
const VERB: Record<Action, string> = {
  approve: "تأیید شد",
  reject: "رد شد",
  "request-revision": "برای اصلاح ارسال شد",
};

/** The optional note for a revision; null when the dialog was cancelled. */
async function noteFor(action: Action): Promise<string | null> {
  if (action !== "request-revision") return "";
  const r = await prompt({
    title: "ارسال برای اصلاح",
    message: "توضیح برای مدیر بخش (اختیاری):",
    placeholder: "مثلاً: جمع استان‌ها با جمع کارشناس‌ها نمی‌خواند",
  });
  return r === null ? null : r;
}

async function decideSheet(sheet: SalesSheet, action: Action) {
  const note = await noteFor(action);
  if (note === null) return;
  busy.value = `sheet-${sheet.key}`;
  try {
    await inboxApi.decideSalesSheet(sheet.period.id, sheet.channel, action, note);
    toast.success(`${sheet.channel_label} · ${sheet.period.label} ${VERB[action]}.`);
    salesPreview.value = null;
    await load();
  } catch (e: any) {
    toast.error(
      e?.response?.status === 409
        ? "این دوره قبلاً تعیین تکلیف شده است."
        : "انجام نشد یا دسترسی ندارید.",
    );
    await load();
  } finally {
    busy.value = "";
  }
}

async function decideProduction(row: any, action: Action) {
  const note = await noteFor(action);
  if (note === null) return;
  busy.value = `production-${row.id}`;
  try {
    await inboxApi.decideProduction(row.id, action, note);
    toast.success(`مورد ${VERB[action]}.`);
    productionPreview.value = null;
    await load();
  } catch {
    toast.error("انجام نشد یا دسترسی ندارید.");
  } finally {
    busy.value = "";
  }
}

const STATUS_FA: Record<string, string> = {
  draft: "پیش‌نویس",
  submitted: "در انتظار تأیید مدیرعامل",
  needs_revision: "برگشت برای اصلاح",
  approved: "تأییدشده",
  rejected: "ردشده",
};

const GRAIN_FA: Record<string, string> = { week: "هفتگی", month: "ماهانه", day: "روزانه" };

const WHEN = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  month: "long", day: "numeric", hour: "2-digit", minute: "2-digit",
});
function when(iso: string | null): string {
  return iso ? WHEN.format(new Date(iso)) : "—";
}

/**
 * Salesperson columns for the review table. Only the ones this sheet actually
 * filled are shown: a B2B sheet has tonnage and no پیش‌فاکتور, a team sheet the
 * reverse, and a table of empty columns hides the numbers being approved.
 */
const PEOPLE_COLUMNS: { key: string; label: string; money?: boolean }[] = [
  { key: "revenue_rial", label: "فروش ریالی", money: true },
  { key: "invoice_count", label: "فاکتور" },
  { key: "profit_rial", label: "سود", money: true },
  { key: "cost_rial", label: "هزینه", money: true },
  { key: "new_customers", label: "مشتری جدید" },
  { key: "active_customers", label: "مشتری فعال" },
  { key: "calls", label: "تماس" },
  { key: "proforma_issued_rial", label: "پیش‌فاکتور صادره", money: true },
  { key: "proforma_cancelled_rial", label: "پیش‌فاکتور کنسل", money: true },
  { key: "quantity_ton", label: "تن" },
  { key: "collected_rial", label: "وصول‌شده", money: true },
  { key: "receivables_rial", label: "مانده مطالبات", money: true },
  { key: "won_invoices_rial", label: "فاکتور مناقصه", money: true },
];
const peopleColumns = computed(() => {
  const s = salesPreview.value;
  if (!s) return [];
  return PEOPLE_COLUMNS.filter(
    (c) => c.key === "revenue_rial" || s.salespeople.some((p) => Number(p[c.key])),
  );
});
function cell(p: Record<string, any>, c: { key: string; money?: boolean }): string {
  const v = p[c.key];
  if (v == null || Number(v) === 0) return "—";
  return c.money ? rial(v) : num(v);
}

/**
 * Salesperson total vs provincial total. They describe the same sales, so a
 * gap is usually a typo in one block — worth putting in front of the approver,
 * not worth blocking on (a sale can legitimately lack a province).
 */
const gap = computed(() => {
  const s = salesPreview.value;
  if (!s || !s.totals.provinces) return 0;
  return Number(s.totals.people_revenue_rial) - Number(s.totals.province_sales_rial);
});

const PRODUCTION_FIELDS: { key: string; label: string }[] = [
  { key: "output_units", label: "تعداد تولید" },
  { key: "active_shifts", label: "شیفت فعال" },
  { key: "waste_pct", label: "درصد ضایعات" },
  { key: "repair_count", label: "تعداد تعمیر" },
  { key: "downtime_breakdown_shifts", label: "توقف خرابی (شیفت)" },
  { key: "downtime_sizechange_shifts", label: "توقف تعویض سایز (شیفت)" },
  { key: "downtime_nowork_shifts", label: "توقف بی‌کاری (شیفت)" },
];
function productionValue(key: string): string {
  const v = productionPreview.value?.[key];
  return v == null || v === "" ? "—" : num(v);
}

const btn = "px-2.5 py-1 text-xs rounded-md border disabled:opacity-50 transition-colors";

onMounted(load);
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-xl font-bold text-ink">کارتابل تایید اطلاعات</h1>
        <p v-if="!auth.isExecutive" class="text-xs text-slate-400 mt-0.5">
          تأیید نهایی بر عهده‌ی مدیرعامل است؛ در این صفحه وضعیت درخواست‌های بخش شما نمایش داده می‌شود.
        </p>
      </div>
      <span
        class="text-sm px-3 py-1 rounded-full"
        :class="totalPending ? 'bg-amber-100 text-amber-700' : 'bg-green-100 text-green-700'"
      >
        {{ totalPending ? `${num(totalPending)} مورد در انتظار` : "موردی در انتظار نیست ✓" }}
      </span>
    </div>

    <DashboardSkeleton v-if="loading" :cards="0" :charts="0" :rows="5" />

    <template v-else>
      <!-- ============ Sales: one row per sheet ============ -->
      <div v-if="sheets.length" class="bg-surface rounded-card shadow-soft p-4">
        <h2 class="text-sm font-semibold text-ink">فروش — در انتظار تایید</h2>
        <p class="text-xs text-slate-400 mt-0.5 mb-3">
          هر ردیف یک دوره‌ی کامل است: همه‌ی کارشناس‌ها و استان‌های آن کانال، که با هم تأیید یا برگشت داده می‌شوند.
        </p>
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[680px]">
            <thead>
              <tr class="text-slate-400 border-b border-slate-100">
                <th class="text-right font-medium py-2">دوره</th>
                <th class="text-right font-medium py-2">کانال</th>
                <th class="text-right font-medium py-2">محتوا</th>
                <th class="text-left font-medium py-2">جمع فروش</th>
                <th class="text-right font-medium py-2">ارسال</th>
                <th class="text-left font-medium py-2">وضعیت / اقدام</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="s in sheets" :key="s.key"
                class="border-b border-slate-50 hover:bg-slate-50/60 transition-colors"
              >
                <td class="py-2.5">
                  <span class="text-ink">{{ s.period.label }}</span>
                  <span class="text-[11px] text-slate-400 bg-slate-100 rounded-full px-2 py-0.5 mr-1.5">
                    {{ GRAIN_FA[s.period.kind] ?? s.period.kind }}
                  </span>
                </td>
                <td class="py-2.5 text-slate-500">{{ s.channel_label }}</td>
                <td class="py-2.5 text-slate-500 whitespace-nowrap">
                  {{ num(s.totals.salespeople) }} کارشناس
                  <template v-if="s.totals.provinces"> · {{ num(s.totals.provinces) }} استان</template>
                  <template v-if="s.totals.customer_groups"> · {{ num(s.totals.customer_groups) }} گروه مشتری</template>
                </td>
                <td class="py-2.5 text-left ltr-nums whitespace-nowrap">{{ rial(s.totals.people_revenue_rial) }}</td>
                <td class="py-2.5 text-xs text-slate-400 whitespace-nowrap">
                  {{ s.submitted_by || "—" }}<br />{{ when(s.submitted_at) }}
                </td>
                <td class="py-2.5 text-left whitespace-nowrap">
                  <div class="flex items-center justify-end gap-1">
                    <button
                      :class="[btn, 'border-slate-300 text-slate-600 hover:bg-slate-50']"
                      @click="salesPreview = s"
                    >بررسی</button>
                    <template v-if="auth.isExecutive">
                      <button
                        :class="[btn, 'border-green-600 text-green-700 hover:bg-green-50']"
                        :disabled="busy === `sheet-${s.key}`"
                        @click="decideSheet(s, 'approve')"
                      >تایید</button>
                      <button
                        :class="[btn, 'border-amber-500 text-amber-600 hover:bg-amber-50']"
                        :disabled="busy === `sheet-${s.key}`"
                        @click="decideSheet(s, 'request-revision')"
                      >ارسال برای اصلاح</button>
                      <button
                        :class="[btn, 'border-red-600 text-red-600 hover:bg-red-50']"
                        :disabled="busy === `sheet-${s.key}`"
                        @click="decideSheet(s, 'reject')"
                      >رد</button>
                    </template>
                    <span v-else class="px-2.5 py-1 text-xs rounded-full bg-amber-50 text-amber-600">
                      {{ STATUS_FA[s.status] ?? "در انتظار تأیید مدیرعامل" }}
                    </span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ============ Production pending ============ -->
      <div v-if="visibleProduction.length" class="bg-surface rounded-card shadow-soft p-4">
        <h2 class="text-sm font-semibold text-ink mb-3">تولید — در انتظار تایید</h2>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-slate-400 border-b border-slate-100">
              <th class="text-right font-medium py-2">خط تولید</th>
              <th class="text-left font-medium py-2">تولید</th>
              <th class="text-left font-medium py-2">شیفت</th>
              <th class="text-left font-medium py-2">دوره</th>
              <th class="text-left font-medium py-2 w-72">وضعیت / اقدام</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in visibleProduction" :key="r.id" class="border-b border-slate-50 hover:bg-slate-50/60 transition-colors">
              <td class="py-2">{{ r.machine_name }}</td>
              <td class="py-2 text-left ltr-nums">{{ num(r.output_units) }}</td>
              <td class="py-2 text-left ltr-nums">{{ num(r.active_shifts) }}</td>
              <td class="py-2 text-left">{{ r.period_label }}</td>
              <td class="py-2 text-left whitespace-nowrap">
                <div class="flex items-center justify-end gap-1">
                  <button
                    :class="[btn, 'border-slate-300 text-slate-600 hover:bg-slate-50']"
                    @click="productionPreview = r"
                  >پیش‌نمایش</button>
                  <template v-if="auth.isExecutive">
                    <button
                      :class="[btn, 'border-green-600 text-green-700 hover:bg-green-50']"
                      :disabled="busy === `production-${r.id}`"
                      @click="decideProduction(r, 'approve')"
                    >تایید</button>
                    <button
                      :class="[btn, 'border-red-600 text-red-600 hover:bg-red-50']"
                      :disabled="busy === `production-${r.id}`"
                      @click="decideProduction(r, 'reject')"
                    >رد</button>
                    <button
                      :class="[btn, 'border-amber-500 text-amber-600 hover:bg-amber-50']"
                      :disabled="busy === `production-${r.id}`"
                      @click="decideProduction(r, 'request-revision')"
                    >ارسال برای اصلاح</button>
                  </template>
                  <span v-else class="px-2.5 py-1 text-xs rounded-full bg-amber-50 text-amber-600">
                    {{ STATUS_FA[r.status] ?? "در انتظار تأیید مدیرعامل" }}
                  </span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="!totalPending" class="bg-surface rounded-card shadow-soft">
        <EmptyState
          icon="✅"
          title="کارتابل شما خالی است"
          hint="همه‌ی اطلاعات ارسال‌شده تعیین تکلیف شده‌اند. وقتی رکورد جدیدی ارسال شود، اعلان دریافت می‌کنید و اینجا ظاهر می‌شود."
        />
      </div>
    </template>

    <!-- ============ Sales sheet review ============ -->
    <div
      v-if="salesPreview"
      class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4"
      dir="rtl"
      @click.self="salesPreview = null"
    >
      <div class="bg-surface rounded-card shadow-pop w-full max-w-3xl max-h-[90vh] flex flex-col animate-pop">
        <header class="px-6 py-4 border-b border-slate-100 flex items-start justify-between gap-3 shrink-0">
          <div>
            <h3 class="font-bold text-ink">
              {{ salesPreview.channel_label }} · {{ salesPreview.period.label }}
            </h3>
            <p class="text-xs text-slate-400 mt-0.5">
              {{ GRAIN_FA[salesPreview.period.kind] }} · ارسال توسط {{ salesPreview.submitted_by || "—" }}
              · {{ when(salesPreview.submitted_at) }}
            </p>
          </div>
          <button class="text-slate-400 hover:text-slate-600 text-xl leading-none" @click="salesPreview = null">×</button>
        </header>

        <div class="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          <!-- Totals first: the two numbers an approver compares. -->
          <div class="grid grid-cols-2 gap-3">
            <div class="bg-slate-50 rounded-xl p-3">
              <p class="text-xs text-slate-400">جمع فروش کارشناس‌ها</p>
              <p class="font-bold text-ink ltr-nums mt-0.5">{{ rial(salesPreview.totals.people_revenue_rial) }}</p>
            </div>
            <div class="bg-slate-50 rounded-xl p-3">
              <p class="text-xs text-slate-400">جمع فروش استانی</p>
              <p class="font-bold text-ink ltr-nums mt-0.5">
                {{ salesPreview.totals.provinces ? rial(salesPreview.totals.province_sales_rial) : "وارد نشده" }}
              </p>
            </div>
          </div>
          <p v-if="gap" class="bg-amber-50 text-amber-800 text-xs rounded-xl px-3 py-2">
            جمع استان‌ها با جمع کارشناس‌ها {{ rial(Math.abs(gap)) }}
            {{ gap > 0 ? "کمتر" : "بیشتر" }} است.
          </p>

          <section>
            <h4 class="text-sm font-semibold text-ink mb-2">
              کارشناس‌ها <span class="text-slate-400 font-normal">({{ num(salesPreview.totals.salespeople) }})</span>
            </h4>
            <div class="overflow-x-auto">
              <table class="w-full text-sm">
                <thead>
                  <tr class="text-slate-400 border-b border-slate-100 text-xs">
                    <th class="text-right font-medium py-2">کارشناس</th>
                    <th v-for="c in peopleColumns" :key="c.key" class="text-left font-medium py-2 px-2 whitespace-nowrap">
                      {{ c.label }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="p in salesPreview.salespeople" :key="p.employee_id" class="border-b border-slate-50">
                    <td class="py-2 text-ink whitespace-nowrap">{{ p.name }}</td>
                    <td v-for="c in peopleColumns" :key="c.key" class="py-2 px-2 text-left ltr-nums whitespace-nowrap">
                      {{ cell(p, c) }}
                    </td>
                  </tr>
                  <tr v-if="!salesPreview.salespeople.length">
                    <td :colspan="peopleColumns.length + 1" class="py-3 text-center text-xs text-slate-400">
                      ردیف کارشناسی ارسال نشده است
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h4 class="text-sm font-semibold text-ink mb-2">
              استان‌ها <span class="text-slate-400 font-normal">({{ num(salesPreview.totals.provinces) }})</span>
            </h4>
            <div v-if="salesPreview.provinces.length" class="grid sm:grid-cols-2 gap-x-6">
              <div
                v-for="p in salesPreview.provinces" :key="p.province_id"
                class="flex items-center justify-between py-1.5 border-b border-slate-50 text-sm"
              >
                <span class="text-slate-600">{{ p.name }}</span>
                <span class="ltr-nums text-ink">{{ rial(p.sales_rial) }}</span>
              </div>
            </div>
            <p v-else class="text-xs text-slate-400">فروش استانی برای این دوره وارد نشده است.</p>
          </section>

          <section v-if="salesPreview.customer_groups.length">
            <h4 class="text-sm font-semibold text-ink mb-2">گروه‌های مشتری</h4>
            <table class="w-full text-sm">
              <thead>
                <tr class="text-slate-400 border-b border-slate-100 text-xs">
                  <th class="text-right font-medium py-2">گروه</th>
                  <th class="text-left font-medium py-2">فروش</th>
                  <th class="text-left font-medium py-2">سود</th>
                  <th class="text-left font-medium py-2">فاکتور</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="g in salesPreview.customer_groups" :key="g.group_id" class="border-b border-slate-50">
                  <td class="py-2 text-ink">{{ g.name }}</td>
                  <td class="py-2 text-left ltr-nums">{{ rial(g.sales_rial) }}</td>
                  <td class="py-2 text-left ltr-nums">{{ rial(g.profit_rial) }}</td>
                  <td class="py-2 text-left ltr-nums">{{ num(g.invoice_count) }}</td>
                </tr>
              </tbody>
            </table>
          </section>
        </div>

        <footer class="px-6 py-3 border-t border-slate-100 shrink-0">
          <div v-if="auth.isExecutive" class="flex justify-end gap-2">
            <button
              class="px-3 py-1.5 text-sm rounded-lg border border-amber-500 text-amber-600 hover:bg-amber-50 transition-colors disabled:opacity-50"
              :disabled="busy === `sheet-${salesPreview.key}`"
              @click="decideSheet(salesPreview, 'request-revision')"
            >ارسال برای اصلاح</button>
            <button
              class="px-3 py-1.5 text-sm rounded-lg border border-red-600 text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
              :disabled="busy === `sheet-${salesPreview.key}`"
              @click="decideSheet(salesPreview, 'reject')"
            >رد</button>
            <button
              class="px-3 py-1.5 text-sm rounded-lg bg-green-600 text-white hover:bg-green-700 transition-colors disabled:opacity-50"
              :disabled="busy === `sheet-${salesPreview.key}`"
              @click="decideSheet(salesPreview, 'approve')"
            >تایید کل دوره</button>
          </div>
          <p v-else class="text-xs text-slate-400 text-center">
            وضعیت: {{ STATUS_FA[salesPreview.status] ?? "در انتظار تأیید مدیرعامل" }}
          </p>
        </footer>
      </div>
    </div>

    <!-- ============ Production record preview ============ -->
    <div
      v-if="productionPreview"
      class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4"
      @click.self="productionPreview = null"
    >
      <div class="bg-surface rounded-card shadow-pop w-full max-w-md p-6 animate-pop">
        <div class="flex items-start justify-between mb-4">
          <div>
            <h3 class="font-bold text-ink">جزئیات تولید</h3>
            <p class="text-sm text-slate-400 mt-0.5">
              {{ productionPreview.machine_name }} · {{ productionPreview.period_label }}
            </p>
          </div>
          <button class="text-slate-400 hover:text-slate-600 text-xl leading-none" @click="productionPreview = null">×</button>
        </div>

        <dl class="divide-y divide-slate-100">
          <div v-for="f in PRODUCTION_FIELDS" :key="f.key" class="flex items-center justify-between py-2 text-sm">
            <dt class="text-slate-500">{{ f.label }}</dt>
            <dd class="ltr-nums font-medium text-ink">{{ productionValue(f.key) }}</dd>
          </div>
        </dl>

        <div v-if="auth.isExecutive" class="flex justify-end gap-2 pt-4 mt-2 border-t border-slate-100">
          <button
            class="px-3 py-1.5 text-sm rounded-lg border border-amber-500 text-amber-600 hover:bg-amber-50 transition-colors"
            :disabled="busy === `production-${productionPreview.id}`"
            @click="decideProduction(productionPreview, 'request-revision')"
          >ارسال برای اصلاح</button>
          <button
            class="px-3 py-1.5 text-sm rounded-lg border border-red-600 text-red-600 hover:bg-red-50 transition-colors"
            :disabled="busy === `production-${productionPreview.id}`"
            @click="decideProduction(productionPreview, 'reject')"
          >رد</button>
          <button
            class="px-3 py-1.5 text-sm rounded-lg bg-green-600 text-white hover:bg-green-700 transition-colors"
            :disabled="busy === `production-${productionPreview.id}`"
            @click="decideProduction(productionPreview, 'approve')"
          >تایید</button>
        </div>
        <p v-else class="text-xs text-slate-400 pt-4 mt-2 border-t border-slate-100 text-center">
          وضعیت: {{ STATUS_FA[productionPreview.status] ?? "در انتظار تأیید مدیرعامل" }}
        </p>
      </div>
    </div>
  </div>
</template>
