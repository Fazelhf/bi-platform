<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { sales2Api, type Options, type Receipt } from "@/api/sales2";
import ReceiptForm from "@/components/sales2/ReceiptForm.vue";
import ExcelImport from "@/components/ExcelImport.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import { apiError } from "@/components/crm/formError";
import { prompt, toast } from "@/composables/useUi";
import { faDate } from "@/utils/adminFormat";

/**
 * دریافت‌ها و چک‌ها. The «چک‌های در جریان» tab is the one finance lives in:
 * every cheque not yet cleared, soonest due first, with its status one click
 * away — a cheque marked برگشتی re-opens the invoices it had paid.
 */
const route = useRoute();
const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));

const rows = ref<Receipt[]>([]);
const options = ref<Options | null>(null);
const loading = ref(true);
const error = ref("");
const tab = ref<"all" | "cheques">("all");
const search = ref("");
const method = ref("");
const showForm = ref(false);

const CHEQUE_CLASS: Record<string, string> = {
  in_hand: "bg-sky-100 text-sky-700",
  deposited: "bg-violet-100 text-violet-700",
  cleared: "bg-emerald-100 text-emerald-700",
  bounced: "bg-red-100 text-red-600",
  returned: "bg-slate-100 text-slate-500",
};

async function load() {
  loading.value = true;
  try {
    const p = tab.value === "cheques"
      ? { method: "cheque", status: "issued", ordering: "due", search: search.value.trim() }
      : { method: method.value, search: search.value.trim(), customer: route.query.customer as string };
    let list = await sales2Api.receipts(p);
    if (tab.value === "cheques") list = list.filter((r) => ["in_hand", "deposited"].includes(r.cheque_status));
    rows.value = list;
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

let timer: ReturnType<typeof setTimeout> | undefined;
watch(search, () => { clearTimeout(timer); timer = setTimeout(load, 300); });
watch([tab, method], load);
onMounted(async () => {
  options.value = await sales2Api.options();
  if (route.query.new) showForm.value = true;
  await load();
});

const total = computed(() => rows.value.filter((r) => r.counts_as_paid).reduce((s, r) => s + Number(r.amount_rial), 0));
const today = new Date().toISOString().slice(0, 10);

async function setStatus(r: Receipt, status: string) {
  try {
    await sales2Api.chequeStatus(r.id, status);
    toast.success("وضعیت چک به‌روز شد.");
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}

async function markSayad(r: Receipt, registered: boolean) {
  try {
    await sales2Api.sayad(r.id, registered);
    toast.success(registered ? "چک ثبت‌شده در صیاد علامت خورد." : "علامت صیاد برداشته شد.");
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}

/** «۳۱ ساعت مانده» — how long an unregistered cheque still counts. */
function hoursLeft(r: Receipt): number {
  if (!r.sayad_deadline) return 0;
  return Math.max(0, Math.ceil((new Date(r.sayad_deadline).getTime() - Date.now()) / 3_600_000));
}

async function cancel(r: Receipt) {
  const reason = await prompt({ title: `ابطال دریافت ${r.number}`, message: "دلیل ابطال؟ تسویه‌های این دریافت هم برداشته می‌شود." });
  if (!reason?.trim()) return;
  try {
    await sales2Api.cancelReceipt(r.id, reason.trim());
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}

async function autoAllocate(r: Receipt) {
  try {
    await sales2Api.allocate(r.id, "auto");
    toast.success("دریافت روی فاکتورهای باز تسویه شد.");
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}

function onSaved(r: Receipt) {
  showForm.value = false;
  toast.success(`دریافت ${r.number} ثبت شد.`);
  load();
}
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <div class="flex bg-slate-100 rounded-xl p-1 text-sm">
        <button class="px-3 py-1.5 rounded-lg" :class="tab === 'all' ? 'bg-surface shadow-soft text-ink' : 'text-slate-500'" @click="tab = 'all'">همه دریافت‌ها</button>
        <button class="px-3 py-1.5 rounded-lg" :class="tab === 'cheques' ? 'bg-surface shadow-soft text-ink' : 'text-slate-500'" @click="tab = 'cheques'">چک‌های در جریان</button>
      </div>
      <ExcelImport import-key="sales2-receipts" label="اکسل دریافت‌ها" @done="load" />
      <input
        v-model="search" placeholder="شماره، مشتری، شماره چک یا صیاد…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none flex-1 min-w-[180px]"
      />
      <select v-if="tab === 'all'" v-model="method" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
        <option value="">همه روش‌ها</option>
        <option v-for="m in options?.receipt_methods" :key="m.value" :value="m.value">{{ m.label }}</option>
      </select>
      <span class="text-xs text-slate-400 px-2">{{ FA.format(rows.length) }} مورد · جمع <span class="ltr-nums">{{ fa(total) }}</span></span>
      <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm" @click="showForm = true">+ ثبت دریافت</button>
    </div>

    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">{{ error }}</p>

    <ReceiptForm
      v-if="showForm && options" :options="options"
      :customer="route.query.customer ? Number(route.query.customer) : null"
      @close="showForm = false" @saved="onSaved"
    />

    <div v-if="loading" class="space-y-2"><Skeleton v-for="i in 6" :key="i" class="h-12 rounded-xl" /></div>
    <EmptyState v-else-if="!rows.length" title="دریافتی ثبت نشده" :hint="tab === 'cheques' ? 'چک وصول‌نشده‌ای در جریان نیست.' : ''" />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-x-auto">
      <table class="w-full text-sm min-w-[960px]">
        <thead>
          <tr class="text-xs text-slate-400 bg-slate-50">
            <th class="text-right font-medium px-4 py-3">شماره</th>
            <th class="text-right font-medium px-3">تاریخ</th>
            <th class="text-right font-medium px-3">مشتری</th>
            <th class="text-right font-medium px-3">روش</th>
            <th class="text-right font-medium px-3">مبلغ</th>
            <th class="text-right font-medium px-3">چک</th>
            <th class="text-right font-medium px-3">تسویه</th>
            <th class="px-3"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id" class="border-t border-slate-100 align-top" :class="r.status === 'cancelled' ? 'opacity-50' : ''">
            <td class="px-4 py-2.5 ltr-nums text-ink font-medium">
              {{ r.number }}
              <p v-if="r.status === 'cancelled'" class="text-xs text-red-500">ابطال: {{ r.cancel_reason }}</p>
            </td>
            <td class="px-3 text-xs text-slate-500">{{ faDate(r.received_on) }}</td>
            <td class="px-3">
              <router-link :to="{ name: 'sales2-customer', params: { id: r.customer } }" class="text-ink hover:text-sky-600">{{ r.customer_name }}</router-link>
            </td>
            <td class="px-3 text-slate-500">
              {{ r.method_label }}
              <p v-if="r.bank_account_label" class="text-xs text-slate-400">{{ r.bank_account_label }}</p>
              <p v-if="r.reference_no" class="text-xs text-slate-400 ltr-nums">{{ r.reference_no }}</p>
            </td>
            <td class="px-3 ltr-nums font-medium text-ink">
              {{ fa(r.amount_rial) }}
              <p class="text-[11px]" :class="{ 'text-amber-600': r.finance_status === 'pending', 'text-emerald-600': r.finance_status === 'confirmed', 'text-red-600': r.finance_status === 'rejected' }">
                {{ r.finance_status_label }}<template v-if="r.finance_note"> — {{ r.finance_note }}</template>
              </p>
            </td>
            <td class="px-3 text-xs">
              <template v-if="r.method === 'cheque'">
                <p class="ltr-nums">{{ r.cheque_no }} · {{ r.cheque_bank }}</p>
                <p :class="r.cheque_due_date && r.cheque_due_date < today && ['in_hand','deposited'].includes(r.cheque_status) ? 'text-red-600' : 'text-slate-500'">
                  سررسید {{ faDate(r.cheque_due_date) }}
                </p>
                <select
                  v-if="r.status === 'issued'" :value="r.cheque_status"
                  class="mt-1 rounded-lg px-2 py-1 text-xs outline-none" :class="CHEQUE_CLASS[r.cheque_status]"
                  @change="setStatus(r, ($event.target as HTMLSelectElement).value)"
                >
                  <option v-for="s in options?.cheque_statuses" :key="s.value" :value="s.value">{{ s.label }}</option>
                </select>
                <p v-if="r.sayad_registered" class="mt-1 text-emerald-600">
                  ثبت در صیاد ✓
                  <button v-if="r.status === 'issued'" class="text-slate-400 mr-1" @click="markSayad(r, false)">برداشتن</button>
                </p>
                <p v-else-if="r.status === 'issued'" class="mt-1" :class="r.is_lapsed ? 'text-red-600' : 'text-amber-600'">
                  {{ r.is_lapsed ? "ثبت نشد — از مطالبات خارج شد" : `ثبت‌نشده در صیاد · ${FA.format(hoursLeft(r))} ساعت مانده` }}
                  <button class="text-sky-600 mr-1" @click="markSayad(r, true)">ثبت شد</button>
                </p>
              </template>
            </td>
            <td class="px-3 text-xs">
              <p v-for="a in (r.counts_as_paid ? r.allocations : [])" :key="a.id" class="ltr-nums text-slate-500">{{ a.invoice_number }}: {{ fa(a.amount_rial) }}</p>
              <p v-if="Number(r.unallocated_rial) > 0 && r.counts_as_paid" class="text-amber-600">
                علی‌الحساب {{ fa(r.unallocated_rial) }}
                <button class="text-sky-600 mr-1" @click="autoAllocate(r)">تسویه خودکار</button>
              </p>
            </td>
            <td class="px-3 text-left">
              <button v-if="r.status === 'issued'" class="text-xs text-slate-400 hover:text-red-500" @click="cancel(r)">ابطال</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
