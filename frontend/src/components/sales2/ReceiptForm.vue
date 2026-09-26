<script setup lang="ts">
import { computed, ref, watch } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import JalaliDateField from "@/components/JalaliDateField.vue";
import CustomerSearch from "@/components/sales2/CustomerSearch.vue";
import { apiError } from "@/components/crm/formError";
import { sales2Api, type CustomerDetail, type Options, type Receipt } from "@/api/sales2";
import { faDate } from "@/utils/adminFormat";

/**
 * ثبت دریافت. The amount is spread over the customer's open invoices, oldest
 * due first, unless the user says which invoices it pays — which is what
 * finance does when a customer writes «بابت فاکتور ۱۲» on the transfer.
 */
const props = defineProps<{ options: Options; customer?: number | null }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved", r: Receipt): void }>();

const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));
const inp = "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";

const form = ref({
  customer: props.customer ?? (null as number | null),
  received_on: new Date().toISOString().slice(0, 10),
  method: "transfer",
  amount_rial: "",
  bank_account: null as number | null,
  reference_no: "",
  cheque_no: "",
  sayad_no: "",
  cheque_bank: "",
  cheque_due_date: "",
  cheque_drawer: "",
  sayad_registered: false,
  note: "",
});
const customerLabel = ref("");
const detail = ref<CustomerDetail | null>(null);
const mode = ref<"auto" | "manual" | "none">("auto");
const manual = ref<Record<number, string>>({});
const saving = ref(false);
const error = ref("");

watch(() => form.value.customer, async (id) => {
  detail.value = null;
  manual.value = {};
  if (!id) return;
  detail.value = await sales2Api.customer(id);
  customerLabel.value = detail.value.name_fa;
}, { immediate: true });

const openTotal = computed(() => (detail.value?.open_invoices ?? []).reduce((s, i) => s + Number(i.remaining_rial), 0));
const manualTotal = computed(() => Object.values(manual.value).reduce((s, v) => s + Number(v || 0), 0));

function fillManual() {
  let left = Number(form.value.amount_rial || 0);
  const next: Record<number, string> = {};
  for (const inv of detail.value?.open_invoices ?? []) {
    const take = Math.min(left, Number(inv.remaining_rial));
    if (take > 0) next[inv.id] = String(take);
    left -= take;
  }
  manual.value = next;
}

async function save() {
  if (!form.value.customer) { error.value = "مشتری را انتخاب کنید."; return; }
  if (mode.value === "manual" && manualTotal.value > Number(form.value.amount_rial || 0)) {
    error.value = "جمع تسویه از مبلغ دریافت بیشتر است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const payload: Record<string, unknown> = { ...form.value };
    if (!payload.cheque_due_date) payload.cheque_due_date = null;
    payload.allocations = mode.value === "auto" ? "auto"
      : mode.value === "none" ? []
        : Object.entries(manual.value).filter(([, v]) => Number(v) > 0)
          .map(([invoice, amount_rial]) => ({ invoice: Number(invoice), amount_rial }));
    emit("saved", await sales2Api.saveReceipt(payload));
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <FormModal title="ثبت دریافت" :saving="saving" :error="error" wide @close="emit('close')" @save="save">
    <div class="grid sm:grid-cols-2 gap-3">
      <div class="sm:col-span-2">
        <label class="text-xs text-slate-500 mb-1 block">مشتری *</label>
        <CustomerSearch v-model="form.customer" :label="customerLabel" />
        <p v-if="detail" class="text-xs text-slate-500 mt-1">
          مانده بدهی: <b class="ltr-nums">{{ fa(detail.balance.balance_rial) }}</b> ریال ·
          {{ FA.format(detail.open_invoices.length) }} فاکتور باز
        </p>
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">تاریخ دریافت</label>
        <JalaliDateField v-model="form.received_on" :clearable="false" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">روش</label>
        <select v-model="form.method" :class="inp">
          <option v-for="m in options.receipt_methods" :key="m.value" :value="m.value">{{ m.label }}</option>
        </select>
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">مبلغ (ریال) *</label>
        <MoneyInput v-model="form.amount_rial" :class="inp" />
      </div>
      <div v-if="form.method !== 'cheque'">
        <label class="text-xs text-slate-500 mb-1 block">حساب / صندوق</label>
        <select v-model="form.bank_account" :class="inp">
          <option :value="null">—</option>
          <option v-for="b in options.bank_accounts" :key="b.id" :value="b.id">{{ b.label }}</option>
        </select>
      </div>
      <div v-if="form.method === 'transfer' || form.method === 'pos'">
        <label class="text-xs text-slate-500 mb-1 block">شماره پیگیری</label>
        <input v-model="form.reference_no" :class="inp" />
      </div>
    </div>

    <div v-if="form.method === 'cheque'" class="grid sm:grid-cols-3 gap-3 bg-slate-50 rounded-xl p-3">
      <div>
        <label class="text-xs text-slate-500 mb-1 block">شماره چک *</label>
        <input v-model="form.cheque_no" :class="inp" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">شناسه صیاد (۱۶ رقم)</label>
        <input v-model="form.sayad_no" :class="inp" inputmode="numeric" maxlength="16" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">سررسید *</label>
        <JalaliDateField v-model="form.cheque_due_date" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">بانک</label>
        <input v-model="form.cheque_bank" :class="inp" />
      </div>
      <div class="sm:col-span-2">
        <label class="text-xs text-slate-500 mb-1 block">صادرکننده</label>
        <input v-model="form.cheque_drawer" :class="inp" placeholder="اگر غیر از خود مشتری است" />
      </div>
      <label class="sm:col-span-3 flex items-center gap-2 text-sm text-ink">
        <input v-model="form.sayad_registered" type="checkbox" />
        در سامانه صیاد ثبت شده
        <span v-if="!form.sayad_registered" class="text-xs text-amber-600">
          — اگر تا ۴۸ ساعت ثبت نشود، از مطالبات خارج و «پرداخت‌نشده» حساب می‌شود.
        </span>
      </label>
    </div>

    <div>
      <label class="text-xs text-slate-500 mb-1 block">توضیحات</label>
      <input v-model="form.note" :class="inp" />
    </div>

    <div v-if="detail?.open_invoices.length" class="border border-slate-100 rounded-xl p-3 space-y-2">
      <div class="flex flex-wrap items-center gap-3 text-sm">
        <span class="text-slate-500">تسویه‌ی فاکتورها:</span>
        <label class="flex items-center gap-1"><input v-model="mode" type="radio" value="auto" /> خودکار (قدیمی‌ترین سررسید)</label>
        <label class="flex items-center gap-1"><input v-model="mode" type="radio" value="manual" @change="fillManual" /> دستی</label>
        <label class="flex items-center gap-1"><input v-model="mode" type="radio" value="none" /> فعلاً نه (علی‌الحساب)</label>
      </div>
      <table v-if="mode === 'manual'" class="w-full text-sm">
        <thead>
          <tr class="text-xs text-slate-400"><th class="text-right py-1">فاکتور</th><th class="text-right">سررسید</th><th class="text-right">مانده</th><th class="text-right w-40">این دریافت</th></tr>
        </thead>
        <tbody>
          <tr v-for="inv in detail.open_invoices" :key="inv.id" class="border-t border-slate-100">
            <td class="py-1 ltr-nums">{{ inv.number }}</td>
            <td class="text-xs text-slate-500">{{ faDate(inv.due_date || inv.doc_date) }}</td>
            <td class="ltr-nums">{{ fa(inv.remaining_rial) }}</td>
            <td><MoneyInput v-model="manual[inv.id]" :class="inp" /></td>
          </tr>
        </tbody>
      </table>
      <p class="text-xs text-slate-400">
        جمع مانده‌ی فاکتورهای باز: <span class="ltr-nums">{{ fa(openTotal) }}</span>
        <template v-if="mode === 'manual'"> · تخصیص‌داده‌شده: <span class="ltr-nums">{{ fa(manualTotal) }}</span></template>
      </p>
    </div>
  </FormModal>
</template>
