<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { inboxApi } from "@/api/platform";
import { useAuthStore } from "@/stores/auth";
import { num, rial } from "@/utils/format";

const auth = useAuthStore();
const sales = ref<any[]>([]);
const production = ref<any[]>([]);
const loading = ref(true);
const busy = ref<string>("");

// A manager only sees (and can only decide) their own section.
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
    note = window.prompt("توضیح برای اصلاح (اختیاری):") ?? "";
  }
  busy.value = `${kind}-${row.id}`;
  try {
    if (kind === "sales") await inboxApi.decideSales(row.id, action, note);
    else await inboxApi.decideProduction(row.id, action, note);
    await load();
  } catch {
    window.alert("خطا در انجام عملیات یا نداشتن دسترسی.");
  } finally {
    busy.value = "";
  }
}

const CHANNEL_FA: Record<string, string> = {
  team: "فروش همکار",
  organizational: "فروش بانکی",
  b2b: "فروش B2B",
};

onMounted(load);
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-slate-800">کارتابل تایید اطلاعات</h1>
      <span
        class="text-sm px-3 py-1 rounded-full"
        :class="totalPending ? 'bg-amber-100 text-amber-700' : 'bg-green-100 text-green-700'"
      >
        {{ totalPending ? `${num(totalPending)} مورد در انتظار` : "موردی در انتظار نیست ✓" }}
      </span>
    </div>

    <div v-if="loading" class="text-slate-500">در حال بارگذاری…</div>

    <template v-else>
      <!-- Sales pending -->
      <div v-if="visibleSales.length" class="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
        <h2 class="text-sm font-semibold text-slate-700 mb-3">فروش — در انتظار تایید</h2>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-slate-400 border-b border-slate-100">
              <th class="text-right font-medium py-2">فروشنده</th>
              <th class="text-right font-medium py-2">کانال</th>
              <th class="text-left font-medium py-2">فروش ریالی</th>
              <th class="text-left font-medium py-2">دوره</th>
              <th class="text-left font-medium py-2 w-56">اقدام</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in visibleSales" :key="r.id" class="border-b border-slate-50">
              <td class="py-2">{{ r.employee_name }}</td>
              <td class="py-2 text-slate-500">{{ CHANNEL_FA[r.channel] ?? r.channel }}</td>
              <td class="py-2 text-left ltr-nums">{{ rial(r.revenue_rial) }}</td>
              <td class="py-2 text-left">{{ r.period_label }}</td>
              <td class="py-2 text-left space-x-1 space-x-reverse whitespace-nowrap">
                <button
                  class="px-2.5 py-1 text-xs rounded-md border border-green-600 text-green-700 hover:bg-green-50 disabled:opacity-50"
                  :disabled="busy === `sales-${r.id}`"
                  @click="decide('sales', r, 'approve')"
                >تایید</button>
                <button
                  class="px-2.5 py-1 text-xs rounded-md border border-red-600 text-red-600 hover:bg-red-50 disabled:opacity-50"
                  :disabled="busy === `sales-${r.id}`"
                  @click="decide('sales', r, 'reject')"
                >رد</button>
                <button
                  class="px-2.5 py-1 text-xs rounded-md border border-amber-500 text-amber-600 hover:bg-amber-50 disabled:opacity-50"
                  :disabled="busy === `sales-${r.id}`"
                  @click="decide('sales', r, 'request-revision')"
                >ارسال برای اصلاح</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Production pending -->
      <div v-if="visibleProduction.length" class="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
        <h2 class="text-sm font-semibold text-slate-700 mb-3">تولید — در انتظار تایید</h2>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-slate-400 border-b border-slate-100">
              <th class="text-right font-medium py-2">خط تولید</th>
              <th class="text-left font-medium py-2">تولید</th>
              <th class="text-left font-medium py-2">شیفت</th>
              <th class="text-left font-medium py-2">دوره</th>
              <th class="text-left font-medium py-2 w-56">اقدام</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in visibleProduction" :key="r.id" class="border-b border-slate-50">
              <td class="py-2">{{ r.machine_name }}</td>
              <td class="py-2 text-left ltr-nums">{{ num(r.output_units) }}</td>
              <td class="py-2 text-left ltr-nums">{{ num(r.active_shifts) }}</td>
              <td class="py-2 text-left">{{ r.period_label }}</td>
              <td class="py-2 text-left space-x-1 space-x-reverse whitespace-nowrap">
                <button
                  class="px-2.5 py-1 text-xs rounded-md border border-green-600 text-green-700 hover:bg-green-50 disabled:opacity-50"
                  :disabled="busy === `production-${r.id}`"
                  @click="decide('production', r, 'approve')"
                >تایید</button>
                <button
                  class="px-2.5 py-1 text-xs rounded-md border border-red-600 text-red-600 hover:bg-red-50 disabled:opacity-50"
                  :disabled="busy === `production-${r.id}`"
                  @click="decide('production', r, 'reject')"
                >رد</button>
                <button
                  class="px-2.5 py-1 text-xs rounded-md border border-amber-500 text-amber-600 hover:bg-amber-50 disabled:opacity-50"
                  :disabled="busy === `production-${r.id}`"
                  @click="decide('production', r, 'request-revision')"
                >ارسال برای اصلاح</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="!totalPending" class="text-slate-400 text-sm">
        همه‌ی اطلاعات ارسال‌شده تعیین تکلیف شده‌اند. وقتی رکورد جدیدی ارسال شود،
        اعلان دریافت می‌کنید و اینجا ظاهر می‌شود.
      </p>
    </template>
  </div>
</template>
