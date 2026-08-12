<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import MoneyInput from "@/components/MoneyInput.vue";
import { useMoney } from "@/composables/useMoney";
import {
  commercialApi,
  type PaymentTerm,
  type PurchaseRequest,
  type Quote,
  type Supplier,
} from "@/api/commercial";
import { PAYMENT_METHODS } from "@/components/commercial/payment";

/** ثبت قیمت یک تامین‌کننده برای یک استعلام. */
const props = defineProps<{
  request: PurchaseRequest;
  quote?: Quote | null;
  /** Suppliers that already priced this request — they cannot quote twice. */
  takenSupplierIds: number[];
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";

const { unitLabel, exact } = useMoney();
const suppliers = ref<Supplier[]>([]);
const terms = ref<PaymentTerm[]>([]);
const saving = ref(false);
const error = ref("");

const form = ref({
  supplier: props.quote?.supplier ?? null as number | null,
  unit_price_rial: props.quote?.unit_price_rial ?? "",
  quoted_on: props.quote?.quoted_on ?? new Date().toISOString().slice(0, 10),
  delivery_days: props.quote?.delivery_days ?? 0,
  validity_days: props.quote?.validity_days ?? 0,
  payment_term: props.quote?.payment_term ?? (null as number | null),
  payment_method: props.quote?.payment_method ?? "",
  payment_note: props.quote?.payment_note ?? "",
  note: props.quote?.note ?? "",
});

/** The schedule is the hint, so «۶۰ روزه» and «۵۰٪ پیش‌پرداخت» are comparable
 *  in the dropdown itself rather than only after both are chosen. */
const termOptions = computed(() => terms.value.map((t) => ({
  value: t.id,
  label: t.name_fa,
  hint: Number(t.advance_pct)
    ? `${t.advance_pct}٪ پیش‌پرداخت${t.days ? ` · مابقی ${t.days} روز` : ""}`
    : (t.days ? `${t.days} روز پس از تحویل` : "بدون مهلت"),
})));

/**
 * One price per supplier per استعلام.
 *
 * The ones that already quoted stay on the list, greyed out and labelled,
 * rather than disappearing. Hiding them answers «کجاست؟» with silence — the
 * user searches for a supplier they know exists, finds nothing, and cannot
 * tell whether it was never entered or has already been priced.
 */
const choices = computed(() => suppliers.value.map((s) => {
  const taken = s.id !== props.quote?.supplier && props.takenSupplierIds.includes(s.id);
  return {
    value: s.id,
    label: s.name_fa,
    hint: taken ? "قیمت داده — برای ویرایش از جدول اقدام کنید" : s.activity,
    keywords: `${s.code} ${s.contact_name} ${s.mobile}`,
    disabled: taken,
  };
}));

const available = computed(() => choices.value.filter((c) => !c.disabled).length);

const lineTotal = computed(() =>
  exact(Number(form.value.unit_price_rial || 0) * Number(props.request.quantity || 0), true),
);

onMounted(async () => {
  [suppliers.value, terms.value] = await Promise.all([
    commercialApi.suppliers({ is_active: true }),
    commercialApi.paymentTerms({ is_active: true }),
  ]);
});

async function save() {
  if (!form.value.supplier) {
    error.value = "تامین‌کننده را انتخاب کنید.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const payload: Record<string, unknown> = {
      ...form.value,
      request: props.request.id,
      unit_price_rial: form.value.unit_price_rial || 0,
    };
    if (!payload.quoted_on) payload.quoted_on = null;
    await commercialApi.saveQuote(payload, props.quote?.id);
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
    :title="quote ? 'ویرایش استعلام' : 'ثبت استعلام قیمت'"
    :subtitle="`${request.material_name} · ${request.quantity} ${request.material_unit}`"
    :saving="saving"
    :error="error"
    @close="emit('close')"
    @save="save"
  >
    <div>
      <label class="text-xs text-slate-500 mb-1 block">تامین‌کننده *</label>
      <PickerField
        v-model="form.supplier"
        :options="choices"
        placeholder="تامین‌کننده را انتخاب کنید…"
        search-placeholder="نام، فعالیت یا شماره تماس…"
        empty-text="تامین‌کننده‌ای با این مشخصات نیست"
      />
      <p v-if="!available" class="text-xs text-amber-600 mt-1">
        همه تامین‌کنندگان فعال برای این درخواست قیمت داده‌اند.
      </p>
    </div>

    <div>
      <label class="text-xs text-slate-500 mb-1 block">
        قیمت واحد ({{ unitLabel }}) *
      </label>
      <MoneyInput v-model="form.unit_price_rial" :class="inp" />
      <p class="text-xs text-slate-400 mt-1">
        مبلغ کل برای این مقدار: <span class="ltr-nums">{{ lineTotal }}</span>
      </p>
    </div>

    <div class="grid grid-cols-3 gap-3">
      <div>
        <label class="text-xs text-slate-500 mb-1 block">زمان تحویل (روز)</label>
        <input v-model.number="form.delivery_days" :class="inp" inputmode="numeric" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">اعتبار قیمت (روز)</label>
        <input v-model.number="form.validity_days" :class="inp" inputmode="numeric" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">تاریخ استعلام</label>
        <input v-model="form.quoted_on" :class="inp" type="date" dir="ltr" />
      </div>
    </div>

    <!-- Terms are part of the offer, not an afterthought on the order: a
         price two percent lower against full prepayment is usually worse. -->
    <div class="border-t border-slate-100 pt-3">
      <p class="text-xs text-slate-400 mb-2">
        شرایط پرداخت — همان چیزی که تعیین می‌کند قیمت ارزان‌تر واقعا ارزان‌تر است یا نه
      </p>
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
        placeholder="توضیح شرایط (اختیاری) — مثلاً چک ۴ ماهه از تاریخ تحویل"
      />
    </div>

    <div>
      <label class="text-xs text-slate-500 mb-1 block">توضیح</label>
      <input v-model="form.note" :class="inp" />
    </div>
  </FormModal>
</template>
