<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import MoneyInput from "@/components/MoneyInput.vue";
import { useMoney } from "@/composables/useMoney";
import {
  commercialApi,
  type Material,
  type PaymentTerm,
  type PurchaseOrder,
  type PurchaseRequest,
  type Quote,
  type Supplier,
} from "@/api/commercial";
import { PAYMENT_METHODS } from "@/components/commercial/payment";

/**
 * ثبت سفارش خرید.
 *
 * Usually opened from a won استعلام, in which case the supplier, material,
 * quantity and price are already known and arrive pre-filled. It also opens
 * empty, because an urgent buy with no استعلام is still a purchase and
 * refusing to record it would push the department back to a spreadsheet.
 */
const props = defineProps<{
  order?: PurchaseOrder | null;
  request?: PurchaseRequest | null;
  quote?: Quote | null;
  /** Opened from a supplier's or material's page: that one comes pre-chosen. */
  defaultSupplier?: number | null;
  defaultMaterial?: number | null;
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";

const { unitLabel, exact } = useMoney();
const materials = ref<Material[]>([]);
const suppliers = ref<Supplier[]>([]);
const terms = ref<PaymentTerm[]>([]);
const saving = ref(false);
const error = ref("");

const STATUSES = [
  { value: "pending", label: "در انتظار تایید" },
  { value: "buying", label: "در حال خرید" },
  { value: "shipped", label: "ارسال شده" },
  { value: "delivered", label: "تحویل شد" },
  { value: "cancelled", label: "لغو شد" },
];

const today = new Date().toISOString().slice(0, 10);

const form = ref({
  material: props.order?.material ?? props.request?.material
    ?? props.defaultMaterial ?? null as number | null,
  supplier: props.order?.supplier ?? props.quote?.supplier
    ?? props.defaultSupplier ?? null as number | null,
  quantity: props.order?.quantity ?? props.request?.quantity ?? "",
  unit_price_rial: props.order?.unit_price_rial ?? props.quote?.unit_price_rial ?? "",
  ordered_on: props.order?.ordered_on ?? today,
  delivered_on: props.order?.delivered_on ?? "",
  status: props.order?.status ?? "pending",
  // Carried over from the winning quote — the terms that were offered are the
  // terms being agreed to, unless someone deliberately changes them here.
  payment_term: props.order?.payment_term ?? props.quote?.payment_term ?? (null as number | null),
  payment_method: props.order?.payment_method ?? props.quote?.payment_method ?? "",
  payment_note: props.order?.payment_note ?? props.quote?.payment_note ?? "",
  is_official: props.order?.is_official ?? props.quote?.is_official ?? false,
  note: props.order?.note ?? "",
});

const vatPct = Number(props.order?.vat_pct ?? props.quote?.vat_pct ?? 10);

const termOptions = computed(() => terms.value.map((t) => ({
  value: t.id,
  label: t.name_fa,
  hint: Number(t.advance_pct)
    ? `${t.advance_pct}٪ پیش‌پرداخت${t.days ? ` · مابقی ${t.days} روز` : ""}`
    : (t.days ? `${t.days} روز پس از تحویل` : "بدون مهلت"),
})));

const amounts = computed(() => {
  const total = Math.round(
    Number(form.value.quantity || 0) * Number(form.value.unit_price_rial || 0),
  );
  const vat = form.value.is_official ? Math.round(total * vatPct / 100) : 0;
  return { total, vat, grand: total + vat };
});

const materialUnit = computed(
  () => materials.value.find((m) => m.id === form.value.material)?.unit_label ?? "",
);

const materialOptions = computed(() => materials.value.map((m) => ({
  value: m.id,
  label: m.name_fa,
  hint: m.category_name || "",
  badge: m.unit_label,
  keywords: m.code,
})));

const supplierOptions = computed(() => suppliers.value.map((s) => ({
  value: s.id,
  label: s.name_fa,
  hint: s.activity,
  keywords: `${s.code} ${s.contact_name} ${s.mobile}`,
})));

const statusOptions = STATUSES.map((s) => ({ value: s.value, label: s.label }));

// «تحویل شد» without a date is a status the reports cannot use — every lead
// time would skip it — so the field fills itself the moment it is needed.
watch(() => form.value.status, (status) => {
  if (status === "delivered" && !form.value.delivered_on) {
    form.value.delivered_on = today;
  }
});

onMounted(async () => {
  [materials.value, suppliers.value, terms.value] = await Promise.all([
    commercialApi.materials({ is_active: true }),
    commercialApi.suppliers({ is_active: true }),
    commercialApi.paymentTerms({ is_active: true }),
  ]);
});

async function save() {
  if (!form.value.material || !form.value.supplier) {
    error.value = "کالا و تامین‌کننده الزامی است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const payload: Record<string, unknown> = {
      ...form.value,
      unit_price_rial: form.value.unit_price_rial || 0,
      request: props.order?.request ?? props.request?.id ?? null,
      quote: props.order?.quote ?? props.quote?.id ?? null,
    };
    if (!payload.delivered_on) payload.delivered_on = null;
    await commercialApi.saveOrder(payload, props.order?.id);
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
    :title="order ? `سفارش ${order.order_no}` : 'سفارش خرید جدید'"
    :subtitle="request?.request_no ? `از درخواست ${request.request_no}` : ''"
    :saving="saving"
    :error="error"
    wide
    @close="emit('close')"
    @save="save"
  >
    <div class="grid sm:grid-cols-2 gap-3">
      <div>
        <label class="text-xs text-slate-500 mb-1 block">کالا *</label>
        <PickerField
          v-model="form.material"
          :options="materialOptions"
          placeholder="کالا را انتخاب کنید…"
          search-placeholder="نام یا کد کالا…"
        />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">تامین‌کننده *</label>
        <PickerField
          v-model="form.supplier"
          :options="supplierOptions"
          placeholder="تامین‌کننده را انتخاب کنید…"
          search-placeholder="نام، فعالیت یا شماره تماس…"
        />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">
          تعداد <span v-if="materialUnit" class="text-slate-400">({{ materialUnit }})</span>
        </label>
        <input v-model="form.quantity" :class="inp" inputmode="decimal" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">قیمت واحد ({{ unitLabel }})</label>
        <MoneyInput v-model="form.unit_price_rial" :class="inp" />
      </div>
    </div>

    <label class="flex items-center gap-2 text-sm text-ink">
      <input v-model="form.is_official" type="checkbox" class="rounded" />
      فاکتور رسمی
      <span class="text-xs text-slate-400">— {{ vatPct }}٪ ارزش افزوده به مبلغ اضافه می‌شود</span>
    </label>

    <div class="bg-slate-50 rounded-xl px-3 py-2 text-sm space-y-1">
      <div class="flex justify-between">
        <span class="text-slate-500">مبلغ کل{{ form.is_official ? " (بدون ارزش افزوده)" : "" }}</span>
        <span class="ltr-nums text-ink" :class="form.is_official ? '' : 'font-medium'">
          {{ exact(amounts.total, true) }}
        </span>
      </div>
      <template v-if="form.is_official">
        <div class="flex justify-between">
          <span class="text-slate-500">ارزش افزوده ({{ vatPct }}٪)</span>
          <span class="ltr-nums text-ink">{{ exact(amounts.vat, true) }}</span>
        </div>
        <div class="flex justify-between font-medium">
          <span class="text-slate-500">مبلغ قابل پرداخت</span>
          <span class="ltr-nums text-ink">{{ exact(amounts.grand, true) }}</span>
        </div>
      </template>
    </div>

    <div class="grid sm:grid-cols-3 gap-3">
      <div>
        <label class="text-xs text-slate-500 mb-1 block">تاریخ سفارش</label>
        <input v-model="form.ordered_on" :class="inp" type="date" dir="ltr" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">وضعیت</label>
        <PickerField
          v-model="form.status" :options="statusOptions" :clearable="false"
        />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">
          تاریخ تحویل
          <span v-if="form.status === 'delivered'" class="text-red-500">*</span>
        </label>
        <input v-model="form.delivered_on" :class="inp" type="date" dir="ltr" />
      </div>
    </div>

    <div class="border-t border-slate-100 pt-3">
      <p class="text-xs text-slate-400 mb-2">شرایط پرداخت</p>
      <div class="grid sm:grid-cols-2 gap-3">
        <div>
          <label class="text-xs text-slate-500 mb-1 block">زمان‌بندی</label>
          <PickerField
            v-model="form.payment_term" :options="termOptions"
            placeholder="مثلاً ۶۰ روزه…"
          />
        </div>
        <div>
          <label class="text-xs text-slate-500 mb-1 block">روش پرداخت</label>
          <PickerField
            v-model="form.payment_method" :options="PAYMENT_METHODS"
            placeholder="نقدی، چک، حواله…"
          />
        </div>
      </div>
      <input
        v-model="form.payment_note" :class="inp" class="mt-2"
        placeholder="توضیح شرایط (اختیاری)"
      />
      <p v-if="quote?.payment_term_name" class="text-xs text-slate-400 mt-1">
        در استعلام پیشنهاد شده بود: {{ quote.payment_term_name }}
      </p>
    </div>

    <div>
      <label class="text-xs text-slate-500 mb-1 block">توضیحات</label>
      <textarea v-model="form.note" :class="inp" rows="2" />
    </div>
  </FormModal>
</template>
