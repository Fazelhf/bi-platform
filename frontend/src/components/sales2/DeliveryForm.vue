<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import JalaliDateField from "@/components/JalaliDateField.vue";
import { apiError } from "@/components/crm/formError";
import { prompt } from "@/composables/useUi";
import { sales2Api, type Delivery, type DocSummary, type Options, type SalesDoc } from "@/api/sales2";

/**
 * حواله خروج. Opens on an invoice's lines with what is still to go already
 * filled in; the user trims it to what is actually on the truck.
 */
const props = defineProps<{ options: Options; invoiceId?: number | null; delivery?: Delivery | null }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const FA = new Intl.NumberFormat("fa-IR");
const inp = "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";

const invoices = ref<DocSummary[]>([]);
const invoice = ref<SalesDoc | null>(null);
const saving = ref(false);
const error = ref("");
const d = props.delivery;
const form = ref({
  invoice: d?.invoice ?? props.invoiceId ?? (null as number | null),
  warehouse: d?.warehouse ?? props.options.settings.default_warehouse,
  delivery_date: d?.delivery_date ?? new Date().toISOString().slice(0, 10),
  receiver_name: d?.receiver_name ?? "",
  driver_name: d?.driver_name ?? "",
  driver_phone: d?.driver_phone ?? "",
  vehicle_plate: d?.vehicle_plate ?? "",
  waybill_no: d?.waybill_no ?? "",
  shipping_address: d?.shipping_address ?? "",
  note: d?.note ?? "",
});
const qty = ref<Record<number, string>>({});

onMounted(async () => {
  invoices.value = await sales2Api.documents({ kind: "invoice", status: "issued" });
});

watch(() => form.value.invoice, async (id) => {
  invoice.value = null;
  if (!id) return;
  invoice.value = await sales2Api.document(id);
  if (!form.value.shipping_address) form.value.shipping_address = invoice.value.customer_address;
  const next: Record<number, string> = {};
  for (const l of invoice.value.lines) {
    const existing = d?.lines.find((x) => x.invoice_line === l.id);
    next[l.id!] = existing ? String(Number(existing.quantity)) : String(Math.max(0, room(l.id!)));
  }
  qty.value = next;
}, { immediate: true });

function room(lineId: number): number {
  const l = invoice.value?.lines.find((x) => x.id === lineId);
  if (!l) return 0;
  return Number(l.deliverable_qty ?? l.quantity);
}

const invoiceOptions = computed(() => invoices.value.map((i) => ({
  value: i.id, label: `${i.number} · ${i.display_customer}`, keywords: i.number,
})));

/**
 * Issue, asking for a reason when the customer is on hold or over their
 * limit — the same rule as issuing the invoice.
 */
async function issueWithReason(id: number) {
  try {
    await sales2Api.issueDelivery(id);
  } catch (e: any) {
    const data = e?.response?.data;
    if (!data?.needs_reason) throw e;
    const reason = await prompt({
      title: "صدور حواله با عبور از کنترل",
      message: (data.checks ?? []).map((c: { message: string }) => `• ${c.message}`).join("\n") + "\n\nدلیل صدور را بنویسید.",
    });
    if (!reason?.trim()) throw new Error("صدور حواله لغو شد.");
    await sales2Api.issueDelivery(id, reason.trim());
  }
}

async function save(issue: boolean) {
  if (!form.value.invoice) { error.value = "فاکتور را انتخاب کنید."; return; }
  saving.value = true;
  error.value = "";
  try {
    const lines = Object.entries(qty.value).map(([invoice_line, quantity]) => ({
      invoice_line: Number(invoice_line), quantity: quantity || 0,
    }));
    const saved = await sales2Api.saveDelivery({ ...form.value, lines }, d?.id);
    if (issue) await issueWithReason(saved.id);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <FormModal
    :title="d ? `حواله ${d.number || 'پیش‌نویس'}` : 'حواله خروج جدید'"
    :saving="saving" :error="error" wide save-label="ذخیره و صدور"
    @close="emit('close')" @save="save(true)"
  >
    <div class="grid sm:grid-cols-2 gap-3">
      <div class="sm:col-span-2">
        <label class="text-xs text-slate-500 mb-1 block">فاکتور *</label>
        <PickerField v-model="form.invoice" :options="invoiceOptions" :disabled="!!d" placeholder="انتخاب فاکتور صادرشده…" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">تاریخ خروج</label>
        <JalaliDateField v-model="form.delivery_date" :clearable="false" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">انبار</label>
        <select v-model="form.warehouse" :class="inp">
          <option :value="null">—</option>
          <option v-for="w in options.warehouses" :key="w.id" :value="w.id">{{ w.name_fa }}</option>
        </select>
      </div>
      <div><label class="text-xs text-slate-500 mb-1 block">تحویل‌گیرنده</label><input v-model="form.receiver_name" :class="inp" /></div>
      <div><label class="text-xs text-slate-500 mb-1 block">شماره بارنامه</label><input v-model="form.waybill_no" :class="inp" /></div>
      <div><label class="text-xs text-slate-500 mb-1 block">راننده</label><input v-model="form.driver_name" :class="inp" /></div>
      <div><label class="text-xs text-slate-500 mb-1 block">تلفن راننده</label><input v-model="form.driver_phone" :class="inp" /></div>
      <div><label class="text-xs text-slate-500 mb-1 block">پلاک</label><input v-model="form.vehicle_plate" :class="inp" /></div>
      <div><label class="text-xs text-slate-500 mb-1 block">توضیحات</label><input v-model="form.note" :class="inp" /></div>
      <div class="sm:col-span-2"><label class="text-xs text-slate-500 mb-1 block">نشانی تحویل</label><input v-model="form.shipping_address" :class="inp" /></div>
    </div>

    <table v-if="invoice" class="w-full text-sm">
      <thead>
        <tr class="text-xs text-slate-400"><th class="text-right py-1">کالا</th><th class="text-right">فاکتور</th><th class="text-right">تحویل‌شده</th><th class="text-right">باقی</th><th class="text-right w-32">این حواله</th></tr>
      </thead>
      <tbody>
        <tr v-for="l in invoice.lines" :key="l.id" class="border-t border-slate-100">
          <td class="py-1.5">{{ l.product_name }} <span class="text-xs text-slate-400">{{ l.unit }}</span></td>
          <td class="ltr-nums">{{ FA.format(Number(l.quantity)) }}</td>
          <td class="ltr-nums text-slate-500">{{ FA.format(Number(l.delivered_qty ?? 0)) }}</td>
          <td class="ltr-nums">{{ FA.format(room(l.id!)) }}</td>
          <td><input v-model="qty[l.id!]" :class="inp" inputmode="decimal" /></td>
        </tr>
      </tbody>
    </table>
    <button type="button" class="text-xs text-slate-500 underline" :disabled="saving" @click="save(false)">فقط ذخیره پیش‌نویس</button>
  </FormModal>
</template>
