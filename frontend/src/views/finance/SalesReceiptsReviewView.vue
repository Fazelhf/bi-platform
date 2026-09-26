<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { sales2Api, type Receipt } from "@/api/sales2";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import { apiError } from "@/components/crm/formError";
import { prompt, toast } from "@/composables/useUi";
import { faDate } from "@/utils/adminFormat";

/**
 * تأیید دریافت‌های فروش — sales records a receipt; finance says whether the
 * money really arrived. A receipt pays its invoices only once confirmed here;
 * a rejected one releases them. The finance department and admins only.
 */
const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));

const tab = ref<"pending" | "confirmed" | "rejected">("pending");
const rows = ref<Receipt[]>([]);
const loading = ref(true);
const error = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try { rows.value = await sales2Api.financeReceipts(tab.value); }
  catch (e) { error.value = apiError(e); }
  finally { loading.value = false; }
}
watch(tab, load);
onMounted(load);

async function confirmOne(r: Receipt) {
  try {
    await sales2Api.reviewReceipt(r.id, true);
    toast.success(`دریافت ${r.number} تأیید شد.`);
    rows.value = rows.value.filter((x) => x.id !== r.id);
  } catch (e) { error.value = apiError(e); }
}

async function rejectOne(r: Receipt) {
  const note = await prompt({ title: `رد دریافت ${r.number}`, message: "دلیل رد؟ تسویه‌های این دریافت برداشته می‌شود." });
  if (!note?.trim()) return;
  try {
    await sales2Api.reviewReceipt(r.id, false, note.trim());
    rows.value = rows.value.filter((x) => x.id !== r.id);
  } catch (e) { error.value = apiError(e); }
}
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <div class="flex bg-slate-100 rounded-xl p-1 text-sm">
        <button v-for="(l, k) in { pending: 'در انتظار تأیید', confirmed: 'تأییدشده', rejected: 'ردشده' }" :key="k"
                class="px-3 py-1.5 rounded-lg" :class="tab === k ? 'bg-surface shadow-soft text-ink' : 'text-slate-500'"
                @click="tab = k as typeof tab">{{ l }}</button>
      </div>
      <span class="text-xs text-slate-400 px-2">
        {{ FA.format(rows.length) }} دریافت · جمع <span class="ltr-nums">{{ fa(rows.reduce((s, r) => s + Number(r.amount_rial), 0)) }}</span> ریال
      </span>
    </div>
    <p class="text-xs text-slate-500 px-1">دریافتی که فروش ثبت کرده تا وقتی این‌جا تأیید نشود، بدهی مشتری را کم نمی‌کند.</p>
    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">{{ error }}</p>

    <div v-if="loading" class="space-y-2"><Skeleton v-for="i in 5" :key="i" class="h-12 rounded-xl" /></div>
    <EmptyState v-else-if="!rows.length" title="دریافتی در این وضعیت نیست" />
    <div v-else class="bg-surface rounded-card shadow-soft overflow-x-auto">
      <table class="w-full text-sm min-w-[860px]">
        <thead>
          <tr class="text-xs text-slate-400 bg-slate-50">
            <th class="text-right font-medium px-4 py-3">شماره</th>
            <th class="text-right font-medium px-3">تاریخ</th>
            <th class="text-right font-medium px-3">مشتری</th>
            <th class="text-right font-medium px-3">روش</th>
            <th class="text-right font-medium px-3">مبلغ (ریال)</th>
            <th class="text-right font-medium px-3">بابت</th>
            <th class="px-3"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id" class="border-t border-slate-100 align-top">
            <td class="px-4 py-2.5 ltr-nums text-ink font-medium">{{ r.number }}</td>
            <td class="px-3 text-xs text-slate-500">{{ faDate(r.received_on) }}</td>
            <td class="px-3">{{ r.customer_name }}</td>
            <td class="px-3 text-slate-500 text-xs">
              {{ r.method_label }}
              <p v-if="r.bank_account_label">{{ r.bank_account_label }}</p>
              <p v-if="r.reference_no" class="ltr-nums">پیگیری {{ r.reference_no }}</p>
              <p v-if="r.method === 'cheque'" class="ltr-nums">چک {{ r.cheque_no }} · {{ r.cheque_bank }} · سررسید {{ faDate(r.cheque_due_date) }}</p>
            </td>
            <td class="px-3 ltr-nums font-medium">{{ fa(r.amount_rial) }}</td>
            <td class="px-3 text-xs text-slate-500">
              <p v-for="a in r.allocations" :key="a.id" class="ltr-nums">{{ a.invoice_number }}: {{ fa(a.amount_rial) }}</p>
              <p v-if="r.finance_note" class="text-red-500">{{ r.finance_note }}</p>
            </td>
            <td class="px-3 text-left whitespace-nowrap">
              <template v-if="tab === 'pending'">
                <button class="text-xs rounded-lg px-3 py-1.5 bg-emerald-600 text-white" @click="confirmOne(r)">تأیید</button>
                <button class="text-xs rounded-lg px-3 py-1.5 text-red-500 hover:bg-red-50 mr-1" @click="rejectOne(r)">رد</button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
