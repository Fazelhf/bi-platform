<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { inboxApi } from "@/api/platform";
import { useAuthStore } from "@/stores/auth";
import { toast, prompt } from "@/composables/useUi";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import { num, rial } from "@/utils/format";

const auth = useAuthStore();
const sales = ref<any[]>([]);
const production = ref<any[]>([]);
const loading = ref(true);
const busy = ref<string>("");
// The record currently open in the preview dialog (CEO reviews before deciding).
const preview = ref<{ kind: "sales" | "production"; row: any } | null>(null);

// A manager only sees their own section; only the CEO can actually decide.
const DEPT_CHANNEL: Record<string, string> = {
  sales_team: "team",
  sales_org: "organizational",
  sales_b2b: "b2b",
};
const visibleSales = computed(() => {
  if (auth.isExecutive) return sales.value;
  const ch = DEPT_CHANNEL[auth.department];
  return ch ? sales.value.filter((r) => r.channel === ch) : [];
});
const visibleProduction = computed(() =>
  auth.isExecutive || auth.department === "production" ? production.value : [],
);
const totalPending = computed(
  () => visibleSales.value.length + visibleProduction.value.length,
);

async function load() {
  loading.value = true;
  try {
    [sales.value, production.value] = await Promise.all([
      inboxApi.pendingSales(),
      inboxApi.pendingProduction(),
    ]);
  } finally {
    loading.value = false;
  }
}

async function decide(
  kind: "sales" | "production",
  row: any,
  action: "approve" | "reject" | "request-revision",
) {
  let note = "";
  if (action === "request-revision") {
    const r = await prompt({ title: "ارسال برای اصلاح", message: "توضیح برای فروشنده (اختیاری):", placeholder: "مثلاً: عدد فروش را بازبینی کنید" });
    if (r === null) return; // cancelled
    note = r;
  }
  busy.value = `${kind}-${row.id}`;
  try {
    if (kind === "sales") await inboxApi.decideSales(row.id, action, note);
    else await inboxApi.decideProduction(row.id, action, note);
    const verb = action === "approve" ? "تأیید شد" : action === "reject" ? "رد شد" : "برای اصلاح ارسال شد";
    toast.success(`مورد ${verb}.`);
    preview.value = null;
    await load();
  } catch {
    toast.error("انجام نشد یا دسترسی ندارید.");
  } finally {
    busy.value = "";
  }
}

const CHANNEL_FA: Record<string, string> = {
  team: "فروش همکار",
  organizational: "فروش بانکی",
  b2b: "فروش B2B",
};

const STATUS_FA: Record<string, string> = {
  draft: "پیش‌نویس",
  submitted: "در انتظار تأیید مدیرعامل",
  needs_revision: "برگشت برای اصلاح",
  approved: "تأییدشده",
  rejected: "ردشده",
};

// Field lists for the full-record preview (CEO reviews before deciding).
const SALES_FIELDS: { key: string; label: string; money?: boolean }[] = [
  { key: "revenue_rial", label: "فروش ریالی", money: true },
  { key: "target_rial", label: "تارگت فروش", money: true },
  { key: "profit_rial", label: "سود فروش", money: true },
  { key: "cost_rial", label: "هزینه فروش", money: true },
  { key: "invoice_count", label: "تعداد فاکتور" },
  { key: "active_customers", label: "مشتری فعال" },
  { key: "new_customers", label: "مشتری جدید" },
  { key: "calls", label: "تعداد تماس" },
];
const PRODUCTION_FIELDS: { key: string; label: string }[] = [
  { key: "output_units", label: "تعداد تولید" },
  { key: "active_shifts", label: "شیفت فعال" },
  { key: "waste_pct", label: "درصد ضایعات" },
  { key: "repair_count", label: "تعداد تعمیر" },
  { key: "downtime_breakdown_shifts", label: "توقف خرابی (شیفت)" },
  { key: "downtime_sizechange_shifts", label: "توقف تعویض سایز (شیفت)" },
  { key: "downtime_nowork_shifts", label: "توقف بی‌کاری (شیفت)" },
];
const previewFields = computed(() =>
  preview.value?.kind === "sales" ? SALES_FIELDS : PRODUCTION_FIELDS,
);
function fieldValue(f: { key: string; money?: boolean }): string {
  const v = preview.value?.row?.[f.key];
  if (v == null || v === "") return "—";
  return f.money ? rial(v) : num(v);
}

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
      <!-- Sales pending -->
      <div v-if="visibleSales.length" class="bg-surface rounded-card shadow-soft p-4">
        <h2 class="text-sm font-semibold text-ink mb-3">فروش — در انتظار تایید</h2>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-slate-400 border-b border-slate-100">
              <th class="text-right font-medium py-2">فروشنده</th>
              <th class="text-right font-medium py-2">کانال</th>
              <th class="text-left font-medium py-2">فروش ریالی</th>
              <th class="text-left font-medium py-2">دوره</th>
              <th class="text-left font-medium py-2 w-72">وضعیت / اقدام</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in visibleSales" :key="r.id" class="border-b border-slate-50 hover:bg-slate-50/60 transition-colors">
              <td class="py-2">{{ r.employee_name }}</td>
              <td class="py-2 text-slate-500">{{ CHANNEL_FA[r.channel] ?? r.channel }}</td>
              <td class="py-2 text-left ltr-nums">{{ rial(r.revenue_rial) }}</td>
              <td class="py-2 text-left">{{ r.period_label }}</td>
              <td class="py-2 text-left whitespace-nowrap">
                <div class="flex items-center justify-end gap-1">
                  <button
                    class="px-2.5 py-1 text-xs rounded-md border border-slate-300 text-slate-600 hover:bg-slate-50 transition-colors"
                    @click="preview = { kind: 'sales', row: r }"
                  >پیش‌نمایش</button>
                  <template v-if="auth.isExecutive">
                    <button
                      class="px-2.5 py-1 text-xs rounded-md border border-green-600 text-green-700 hover:bg-green-50 disabled:opacity-50 transition-colors"
                      :disabled="busy === `sales-${r.id}`"
                      @click="decide('sales', r, 'approve')"
                    >تایید</button>
                    <button
                      class="px-2.5 py-1 text-xs rounded-md border border-red-600 text-red-600 hover:bg-red-50 disabled:opacity-50 transition-colors"
                      :disabled="busy === `sales-${r.id}`"
                      @click="decide('sales', r, 'reject')"
                    >رد</button>
                    <button
                      class="px-2.5 py-1 text-xs rounded-md border border-amber-500 text-amber-600 hover:bg-amber-50 disabled:opacity-50 transition-colors"
                      :disabled="busy === `sales-${r.id}`"
                      @click="decide('sales', r, 'request-revision')"
                    >ارسال برای اصلاح</button>
                  </template>
                  <span
                    v-else
                    class="px-2.5 py-1 text-xs rounded-full bg-amber-50 text-amber-600"
                  >{{ STATUS_FA[r.status] ?? "در انتظار تأیید مدیرعامل" }}</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Production pending -->
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
                    class="px-2.5 py-1 text-xs rounded-md border border-slate-300 text-slate-600 hover:bg-slate-50 transition-colors"
                    @click="preview = { kind: 'production', row: r }"
                  >پیش‌نمایش</button>
                  <template v-if="auth.isExecutive">
                    <button
                      class="px-2.5 py-1 text-xs rounded-md border border-green-600 text-green-700 hover:bg-green-50 disabled:opacity-50 transition-colors"
                      :disabled="busy === `production-${r.id}`"
                      @click="decide('production', r, 'approve')"
                    >تایید</button>
                    <button
                      class="px-2.5 py-1 text-xs rounded-md border border-red-600 text-red-600 hover:bg-red-50 disabled:opacity-50 transition-colors"
                      :disabled="busy === `production-${r.id}`"
                      @click="decide('production', r, 'reject')"
                    >رد</button>
                    <button
                      class="px-2.5 py-1 text-xs rounded-md border border-amber-500 text-amber-600 hover:bg-amber-50 disabled:opacity-50 transition-colors"
                      :disabled="busy === `production-${r.id}`"
                      @click="decide('production', r, 'request-revision')"
                    >ارسال برای اصلاح</button>
                  </template>
                  <span
                    v-else
                    class="px-2.5 py-1 text-xs rounded-full bg-amber-50 text-amber-600"
                  >{{ STATUS_FA[r.status] ?? "در انتظار تأیید مدیرعامل" }}</span>
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

    <!-- ============ Full-record preview dialog ============ -->
    <div
      v-if="preview"
      class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4"
      @click.self="preview = null"
    >
      <div class="bg-surface rounded-card shadow-pop w-full max-w-md p-6 animate-pop">
        <div class="flex items-start justify-between mb-4">
          <div>
            <h3 class="font-bold text-ink">
              {{ preview.kind === "sales" ? "جزئیات فروش" : "جزئیات تولید" }}
            </h3>
            <p class="text-sm text-slate-400 mt-0.5">
              {{ preview.kind === "sales" ? preview.row.employee_name : preview.row.machine_name }}
              · {{ preview.row.period_label }}
            </p>
          </div>
          <button class="text-slate-400 hover:text-slate-600 text-xl leading-none" @click="preview = null">×</button>
        </div>

        <dl class="divide-y divide-slate-100">
          <div v-for="f in previewFields" :key="f.key" class="flex items-center justify-between py-2 text-sm">
            <dt class="text-slate-500">{{ f.label }}</dt>
            <dd class="ltr-nums font-medium text-ink">{{ fieldValue(f) }}</dd>
          </div>
        </dl>

        <!-- Only the CEO decides; managers see a read-only status line. -->
        <div v-if="auth.isExecutive" class="flex justify-end gap-2 pt-4 mt-2 border-t border-slate-100">
          <button
            class="px-3 py-1.5 text-sm rounded-lg border border-amber-500 text-amber-600 hover:bg-amber-50 transition-colors"
            :disabled="busy === `${preview.kind}-${preview.row.id}`"
            @click="decide(preview.kind, preview.row, 'request-revision')"
          >ارسال برای اصلاح</button>
          <button
            class="px-3 py-1.5 text-sm rounded-lg border border-red-600 text-red-600 hover:bg-red-50 transition-colors"
            :disabled="busy === `${preview.kind}-${preview.row.id}`"
            @click="decide(preview.kind, preview.row, 'reject')"
          >رد</button>
          <button
            class="px-3 py-1.5 text-sm rounded-lg bg-green-600 text-white hover:bg-green-700 transition-colors"
            :disabled="busy === `${preview.kind}-${preview.row.id}`"
            @click="decide(preview.kind, preview.row, 'approve')"
          >تایید</button>
        </div>
        <p v-else class="text-xs text-slate-400 pt-4 mt-2 border-t border-slate-100 text-center">
          وضعیت: {{ STATUS_FA[preview.row.status] ?? "در انتظار تأیید مدیرعامل" }}
        </p>
      </div>
    </div>
  </div>
</template>
