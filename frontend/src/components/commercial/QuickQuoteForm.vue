<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import { apiError } from "@/components/crm/formError";
import { useMoney } from "@/composables/useMoney";
import { faDate } from "@/utils/adminFormat";
import {
  commercialApi,
  type Material,
  type PaymentTerm,
  type PurchaseRequest,
  type Supplier,
} from "@/api/commercial";
import { PAYMENT_METHODS } from "@/components/commercial/payment";

/**
 * ثبت استعلام از پرونده تامین‌کننده یا کالا.
 *
 * Opened on a supplier's page the supplier is fixed and the کالا is chosen;
 * on a material's page the other way round. The quote can join a request
 * that is already collecting prices for that کالا, or open a new one in the
 * same save — nobody should have to leave the page to raise a request first.
 */
const props = defineProps<{
  supplierId?: number | null;
  materialId?: number | null;
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
const lbl = "text-xs text-slate-500 mb-1 block";

const { unitLabel, exact } = useMoney();
const materials = ref<Material[]>([]);
const suppliers = ref<Supplier[]>([]);
const terms = ref<PaymentTerm[]>([]);
const openRequests = ref<PurchaseRequest[]>([]);
const saving = ref(false);
const error = ref("");

const VAT_PCT = 10;
const NEW_REQUEST = 0;
const today = new Date().toISOString().slice(0, 10);

const form = ref({
  supplier: props.supplierId ?? (null as number | null),
  material: props.materialId ?? (null as number | null),
  /** An open request's id, or NEW_REQUEST to open one with `quantity`. */
  request: NEW_REQUEST as number | null,
  quantity: "",
  unit_price_rial: "",
  is_official: false,
  quoted_on: today,
  delivery_days: 0,
  validity_days: 0,
  payment_term: null as number | null,
  payment_method: "",
  note: "",
});

const materialOptions = computed(() => materials.value.map((m) => ({
  value: m.id, label: m.name_fa, hint: m.category_name || "",
  badge: m.unit_label, keywords: m.code,
})));
const supplierOptions = computed(() => suppliers.value.map((s) => ({
  value: s.id, label: s.name_fa, hint: s.activity,
  keywords: `${s.code} ${s.contact_name} ${s.mobile}`,
})));
const termOptions = computed(() => terms.value.map((t) => ({
  value: t.id, label: t.name_fa,
})));

const chosenRequest = computed(
  () => openRequests.value.find((r) => r.id === form.value.request) ?? null,
);
const materialUnit = computed(
  () => materials.value.find((m) => m.id === form.value.material)?.unit_label ?? "",
);

/** A supplier that already priced a request is shown, but cannot price it twice. */
const requestOptions = computed(() => [
  { value: NEW_REQUEST, label: "درخواست خرید جدید", hint: "با مقداری که همین‌جا وارد می‌کنید" },
  ...openRequests.value.map((r) => {
    const taken = !!form.value.supplier
      && !!r.quotes?.some((q) => q.supplier === form.value.supplier);
    return {
      value: r.id,
      label: `${r.request_no} · ${r.quantity} ${r.material_unit}`,
      hint: taken
        ? "این تامین‌کننده قبلا برای این درخواست قیمت داده"
        : `${r.status_label} · ${faDate(r.requested_on)}`,
      disabled: taken,
    };
  }),
]);

const quantity = computed(() =>
  Number(chosenRequest.value ? chosenRequest.value.quantity : form.value.quantity || 0),
);
const amounts = computed(() => {
  const total = Math.round(Number(form.value.unit_price_rial || 0) * quantity.value);
  const vat = form.value.is_official ? Math.round(total * VAT_PCT / 100) : 0;
  return { total, vat, grand: total + vat };
});

async function loadRequests() {
  openRequests.value = [];
  form.value.request = NEW_REQUEST;
  if (!form.value.material) return;
  const [open, quoting] = await Promise.all([
    commercialApi.requests({ material: form.value.material, status: "open" }),
    commercialApi.requests({ material: form.value.material, status: "quoting" }),
  ]);
  // The list endpoint leaves quotes out; the detail carries them, and it is
  // what tells us whether this supplier has already priced the request.
  openRequests.value = await Promise.all(
    [...open, ...quoting].map((r) => commercialApi.request(r.id)),
  );
}

watch(() => form.value.material, loadRequests);

onMounted(async () => {
  [materials.value, suppliers.value, terms.value] = await Promise.all([
    commercialApi.materials({ is_active: true }),
    commercialApi.suppliers({ is_active: true }),
    commercialApi.paymentTerms({ is_active: true }),
  ]);
  await loadRequests();
});

async function save() {
  if (!form.value.supplier || !form.value.material) {
    error.value = "تامین‌کننده و کالا الزامی است.";
    return;
  }
  if (!chosenRequest.value && !Number(form.value.quantity)) {
    error.value = "مقدار درخواستی را وارد کنید.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await commercialApi.quickQuote({
      ...form.value,
      request: chosenRequest.value?.id ?? null,
      unit_price_rial: form.value.unit_price_rial || 0,
      quoted_on: form.value.quoted_on || null,
    });
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
    title="ثبت استعلام قیمت"
    :saving="saving"
    :error="error"
    wide
    @close="emit('close')"
    @save="save"
  >
    <div class="grid sm:grid-cols-2 gap-3">
      <div>
        <label :class="lbl">تامین‌کننده *</label>
        <PickerField
          v-model="form.supplier" :options="supplierOptions"
          :disabled="!!supplierId"
          placeholder="تامین‌کننده را انتخاب کنید…"
          search-placeholder="نام، فعالیت یا شماره تماس…"
        />
      </div>
      <div>
        <label :class="lbl">کالا *</label>
        <PickerField
          v-model="form.material" :options="materialOptions"
          :disabled="!!materialId"
          placeholder="کالا را انتخاب کنید…"
          search-placeholder="نام یا کد کالا…"
        />
      </div>
      <div>
        <label :class="lbl">درخواست خرید</label>
        <PickerField
          v-model="form.request" :options="requestOptions" :clearable="false"
          :disabled="!form.material"
        />
      </div>
      <div>
        <label :class="lbl">
          مقدار <span v-if="materialUnit" class="text-slate-400">({{ materialUnit }})</span>
          <span v-if="!chosenRequest">*</span>
        </label>
        <input
          v-if="!chosenRequest" v-model="form.quantity" :class="inp" inputmode="decimal"
        />
        <input v-else :value="chosenRequest.quantity" :class="inp" disabled />
      </div>
    </div>

    <div>
      <label :class="lbl">قیمت واحد ({{ unitLabel }}) — بدون ارزش افزوده</label>
      <MoneyInput v-model="form.unit_price_rial" :class="inp" />
    </div>

    <label class="flex items-center gap-2 text-sm text-ink">
      <input v-model="form.is_official" type="checkbox" class="rounded" />
      فاکتور رسمی
      <span class="text-xs text-slate-400">— {{ VAT_PCT }}٪ ارزش افزوده به قیمت اضافه می‌شود</span>
    </label>

    <div class="bg-slate-50 rounded-xl px-3 py-2 text-sm space-y-1">
      <div class="flex justify-between">
        <span class="text-slate-500">مبلغ کل</span>
        <span class="ltr-nums text-ink">{{ exact(amounts.total, true) }}</span>
      </div>
      <template v-if="form.is_official">
        <div class="flex justify-between">
          <span class="text-slate-500">ارزش افزوده ({{ VAT_PCT }}٪)</span>
          <span class="ltr-nums text-ink">{{ exact(amounts.vat, true) }}</span>
        </div>
        <div class="flex justify-between font-medium">
          <span class="text-slate-500">جمع با ارزش افزوده</span>
          <span class="ltr-nums text-ink">{{ exact(amounts.grand, true) }}</span>
        </div>
      </template>
    </div>

    <div class="grid grid-cols-3 gap-3">
      <div>
        <label :class="lbl">زمان تحویل (روز)</label>
        <input v-model.number="form.delivery_days" :class="inp" inputmode="numeric" />
      </div>
      <div>
        <label :class="lbl">اعتبار قیمت (روز)</label>
        <input v-model.number="form.validity_days" :class="inp" inputmode="numeric" />
      </div>
      <div>
        <label :class="lbl">تاریخ استعلام</label>
        <input v-model="form.quoted_on" :class="inp" type="date" dir="ltr" />
      </div>
    </div>

    <div class="grid sm:grid-cols-2 gap-3">
      <div>
        <label :class="lbl">شرایط پرداخت</label>
        <PickerField v-model="form.payment_term" :options="termOptions" placeholder="مثلاً ۶۰ روزه…" />
      </div>
      <div>
        <label :class="lbl">روش پرداخت</label>
        <PickerField v-model="form.payment_method" :options="PAYMENT_METHODS" placeholder="نقدی، چک، حواله…" />
      </div>
    </div>

    <div>
      <label :class="lbl">توضیح</label>
      <input v-model="form.note" :class="inp" />
    </div>
  </FormModal>
</template>
