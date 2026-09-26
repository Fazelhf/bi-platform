<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { sales2Api, type ReceivableRow } from "@/api/sales2";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import { apiError } from "@/components/crm/formError";

/**
 * مطالبات — for each customer, what they owe and how it has been met:
 * نقدی، چک ثبت‌شده در صیاد، چک ثبت‌نشده (still inside its 48 hours), and
 * the rest, پرداخت‌نشده. A cheque not registered in time leaves this page
 * entirely; its amount is simply part of پرداخت‌نشده again.
 */
const router = useRouter();
const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));

const rows = ref<ReceivableRow[]>([]);
const totals = ref<Record<string, string>>({});
const graceHours = ref(48);
const loading = ref(true);
const error = ref("");
const q = ref("");
const onlyOpen = ref(true);

async function load() {
  loading.value = true;
  try {
    const data = await sales2Api.receivables({ q: q.value.trim(), open: onlyOpen.value ? 1 : "" });
    rows.value = data.rows;
    totals.value = data.totals;
    graceHours.value = data.grace_hours;
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

let timer: ReturnType<typeof setTimeout> | undefined;
watch(q, () => { clearTimeout(timer); timer = setTimeout(load, 300); });
watch(onlyOpen, load);
onMounted(load);

function hoursLeft(deadline: string | null): number {
  if (!deadline) return 0;
  return Math.max(0, Math.ceil((new Date(deadline).getTime() - Date.now()) / 3_600_000));
}

/** How much of the bill each part covers, for the bar under the name. */
function share(r: ReceivableRow, key: keyof ReceivableRow): string {
  const due = Number(r.due_rial);
  if (due <= 0) return "0%";
  return `${Math.max(0, Math.min(100, (Number(r[key]) / due) * 100))}%`;
}

const TILES = computed(() => [
  { label: "کل مطالبات", key: "due_rial", cls: "text-ink" },
  { label: "دریافت نقدی", key: "cash_rial", cls: "text-emerald-600" },
  { label: "چک ثبت‌شده در صیاد", key: "cheque_registered_rial", cls: "text-sky-600" },
  { label: "چک ثبت‌نشده", key: "cheque_unregistered_rial", cls: "text-amber-600" },
  { label: "در انتظار تأیید مالی", key: "pending_finance_rial", cls: "text-violet-600" },
  { label: "پرداخت‌نشده", key: "unpaid_rial", cls: "text-red-600" },
]);
</script>

<template>
  <div class="space-y-4">
    <div class="grid grid-cols-2 lg:grid-cols-6 gap-3">
      <div v-for="t in TILES" :key="t.key" class="bg-surface rounded-card shadow-soft p-4">
        <p class="text-xs text-slate-500">{{ t.label }}</p>
        <p class="text-lg font-bold ltr-nums mt-1" :class="t.cls">{{ fa(totals[t.key]) }}</p>
      </div>
    </div>

    <p class="text-xs text-slate-500 px-1">
      چکی که ثبت شده ولی تا {{ FA.format(graceHours) }} ساعت در سامانه صیاد ثبت نشود، از مطالبات خارج می‌شود و مبلغش به «پرداخت‌نشده» برمی‌گردد.
      ثبت در صیاد را از صفحه‌ی «دریافت و چک» علامت بزنید.
    </p>

    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-3">
      <input
        v-model="q" placeholder="نام مشتری…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none flex-1 min-w-[180px]"
      />
      <label class="flex items-center gap-2 text-sm text-slate-600">
        <input v-model="onlyOpen" type="checkbox" /> فقط مشتریان بدهکار
      </label>
      <span class="text-xs text-slate-400">{{ FA.format(rows.length) }} مشتری · مبالغ به ریال</span>
    </div>

    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">{{ error }}</p>
    <div v-if="loading" class="space-y-2"><Skeleton v-for="i in 6" :key="i" class="h-12 rounded-xl" /></div>
    <EmptyState v-else-if="!rows.length" title="مطالبه‌ای نیست" hint="هیچ مشتری بدهی باز ندارد." />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-x-auto">
      <table class="w-full text-sm min-w-[920px]">
        <thead>
          <tr class="text-xs text-slate-400 bg-slate-50">
            <th class="text-right font-medium px-4 py-3">مشتری</th>
            <th class="text-right font-medium px-3">باید بدهد</th>
            <th class="text-right font-medium px-3">نقدی</th>
            <th class="text-right font-medium px-3">چک ثبت‌شده</th>
            <th class="text-right font-medium px-3">چک ثبت‌نشده</th>
            <th class="text-right font-medium px-3">در انتظار تأیید مالی</th>
            <th class="text-right font-medium px-3">پرداخت‌نشده</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="r in rows" :key="r.customer"
            class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer align-top"
            @click="router.push({ name: 'sales2-customer', params: { id: r.customer } })"
          >
            <td class="px-4 py-2.5">
              <p class="text-ink font-medium">{{ r.name }}</p>
              <!-- The bill as one bar: green paid, blue registered, amber waiting, red open. -->
              <div class="flex h-1.5 rounded-full overflow-hidden bg-red-200 mt-1.5 w-48">
                <span class="bg-emerald-500" :style="{ width: share(r, 'cash_rial') }" />
                <span class="bg-sky-500" :style="{ width: share(r, 'cheque_registered_rial') }" />
                <span class="bg-amber-400" :style="{ width: share(r, 'cheque_unregistered_rial') }" />
              </div>
            </td>
            <td class="px-3 ltr-nums font-medium text-ink">{{ fa(r.due_rial) }}</td>
            <td class="px-3 ltr-nums text-emerald-600">{{ Number(r.cash_rial) ? fa(r.cash_rial) : "—" }}</td>
            <td class="px-3 ltr-nums text-sky-600">{{ Number(r.cheque_registered_rial) ? fa(r.cheque_registered_rial) : "—" }}</td>
            <td class="px-3 ltr-nums text-amber-600">
              {{ Number(r.cheque_unregistered_rial) ? fa(r.cheque_unregistered_rial) : "—" }}
              <p v-if="r.unregistered_deadline" class="text-[11px]">
                {{ FA.format(hoursLeft(r.unregistered_deadline)) }} ساعت تا خروج
              </p>
            </td>
            <td class="px-3 ltr-nums text-violet-600">{{ Number(r.pending_finance_rial) ? fa(r.pending_finance_rial) : "—" }}</td>
            <td class="px-3 ltr-nums font-bold" :class="Number(r.unpaid_rial) > 0 ? 'text-red-600' : 'text-slate-400'">
              {{ fa(r.unpaid_rial) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
