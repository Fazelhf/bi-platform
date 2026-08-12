<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import SupplierForm from "@/components/commercial/SupplierForm.vue";
import { apiError } from "@/components/crm/formError";
import { commercialApi, type Suggestions, type Supplier } from "@/api/commercial";
import {
  foreignApi,
  type Bank,
  type ForeignOrder,
  type ForeignOptions,
} from "@/api/commercialForeign";

/**
 * پرونده واردات — the proforma, its ثبت سفارش, and the dates that decide
 * whether it lives or quietly expires.
 *
 * The dates are grouped by the gate they belong to rather than listed flat,
 * because that is the order they get filled in: nothing about تخصیص is known
 * on the day the file is opened.
 */
const props = defineProps<{ order?: ForeignOrder | null }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved", o: ForeignOrder): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
const lbl = "text-xs text-slate-500 mb-1 block";

const banks = ref<Bank[]>([]);
const suppliers = ref<Supplier[]>([]);
const options = ref<ForeignOptions | null>(null);
const seen = ref<Suggestions | null>(null);
const showSupplierForm = ref(false);
const saving = ref(false);
const error = ref("");

const form = ref({
  pi_no: props.order?.pi_no ?? "",
  registration_no: props.order?.registration_no ?? "",
  statistical_no: props.order?.statistical_no ?? "",
  supplier: props.order?.supplier ?? (null as number | null),
  country: props.order?.country ?? "",
  brand: props.order?.brand ?? "",
  goods_desc: props.order?.goods_desc ?? "",
  weight_ton: props.order?.weight_ton ?? "",
  currency: props.order?.currency ?? "USD",
  amount: props.order?.amount ?? "",
  bank: props.order?.bank ?? (null as number | null),
  registered_on: props.order?.registered_on ?? new Date().toISOString().slice(0, 10),
  valid_until: props.order?.valid_until ?? "",
  queued_on: props.order?.queued_on ?? "",
  allocated_on: props.order?.allocated_on ?? "",
  purchase_deadline: props.order?.purchase_deadline ?? "",
  expected_queue_days: props.order?.expected_queue_days ?? 60,
  status: props.order?.status ?? "draft",
  note: props.order?.note ?? "",
});

/**
 * Foreign sellers first, but not only them.
 *
 * A company that supplies both halves exists, and a file whose seller is
 * filed as داخلی is a data-entry slip that has to stay fixable from here —
 * so domestic rows follow, labelled, instead of being filtered out.
 */
const supplierOptions = computed(() => {
  const rows = [...suppliers.value].sort(
    (a, b) => Number(b.origin === "foreign") - Number(a.origin === "foreign"),
  );
  return rows.map((s) => ({
    value: s.id,
    label: s.name_fa,
    hint: [s.name_en, s.country || (s.origin === "domestic" ? "داخلی" : "")]
      .filter(Boolean).join(" · "),
    keywords: `${s.code} ${s.name_en} ${s.country}`,
  }));
});

const bankOptions = computed(() => banks.value.map((b) => ({
  value: b.id, label: b.name_fa, keywords: b.code,
})));
const currencyOptions = computed(
  () => (options.value?.currencies ?? []).map((c) => ({ value: c.value, label: c.label })),
);
const statusOptions = computed(
  () => (options.value?.order_statuses ?? []).map((s) => ({ value: s.value, label: s.label })),
);
const textOptions = (rows: string[] | undefined) =>
  (rows ?? []).map((v) => ({ value: v, label: v }));

async function loadSuppliers() {
  suppliers.value = await commercialApi.suppliers({ is_active: true });
}

/** A file is often opened before its seller exists as a row. Sending the user
 *  away to تامین‌کنندگان to create one loses everything typed so far. */
async function afterSupplierAdded() {
  showSupplierForm.value = false;
  await loadSuppliers();
  const newest = suppliers.value.reduce(
    (a, b) => (a && a.id > b.id ? a : b), null as Supplier | null,
  );
  if (newest && !form.value.supplier) form.value.supplier = newest.id;
}

onMounted(async () => {
  [banks.value, options.value] = await Promise.all([
    foreignApi.banks(),
    foreignApi.options(),
  ]);
  await loadSuppliers();
  try {
    seen.value = await commercialApi.suggestions();
  } catch { /* suggestions are optional */ }
});

async function save() {
  if (!form.value.pi_no.trim()) {
    error.value = "شماره پروفرما الزامی است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    // Empty date inputs come through as "", which the API reads as an invalid
    // date rather than as "not set yet".
    const payload: Record<string, unknown> = { ...form.value };
    for (const key of [
      "valid_until", "queued_on", "allocated_on", "purchase_deadline", "registered_on",
    ]) {
      if (!payload[key]) payload[key] = null;
    }
    const saved = await foreignApi.saveOrder(payload, props.order?.id);
    emit("saved", saved);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <FormModal
    :title="order ? `پرونده ${order.file_no}` : 'پرونده واردات جدید'"
    :subtitle="order?.pi_no"
    :saving="saving"
    :error="error"
    wide
    @close="emit('close')"
    @save="save"
  >
    <!-- شناسه پرونده -->
    <div class="grid sm:grid-cols-3 gap-3">
      <div>
        <label :class="lbl">شماره پروفرما (PI) *</label>
        <input v-model="form.pi_no" :class="inp" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">شماره ثبت سفارش</label>
        <input v-model="form.registration_no" :class="inp" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">شماره ثبت آماری</label>
        <input v-model="form.statistical_no" :class="inp" dir="ltr" />
      </div>
    </div>

    <!-- کالا و فروشنده -->
    <div class="grid sm:grid-cols-2 gap-3">
      <div>
        <label :class="lbl" class="flex items-center justify-between">
          <span>فروشنده خارجی</span>
          <button
            type="button"
            class="text-[11px] text-accent-600 hover:underline"
            @click="showSupplierForm = true"
          >+ فروشنده جدید</button>
        </label>
        <PickerField
          v-model="form.supplier"
          :options="supplierOptions"
          placeholder="فروشنده را انتخاب کنید…"
          search-placeholder="نام فارسی، لاتین یا کشور…"
          empty-text="فروشنده‌ای پیدا نشد — می‌توانید جدید بسازید"
        />
      </div>
      <div>
        <label :class="lbl">کشور</label>
        <PickerField
          v-model="form.country" :options="textOptions(seen?.countries)" creatable
          placeholder="مثلاً چین"
        />
      </div>
      <div>
        <label :class="lbl">برند</label>
        <PickerField
          v-model="form.brand" :options="textOptions(seen?.brands)" creatable
          placeholder="مثلاً Oriental"
        />
      </div>
      <div>
        <label :class="lbl">وزن (تن)</label>
        <input v-model="form.weight_ton" :class="inp" inputmode="decimal" dir="ltr" />
      </div>
      <div class="sm:col-span-2">
        <label :class="lbl">شرح کالا</label>
        <PickerField
          v-model="form.goods_desc" :options="textOptions(seen?.goods)" creatable
          placeholder="مثلاً کاغذ حرارتی ۵۵ گرم"
        />
      </div>
    </div>

    <!-- ارز و بانک -->
    <div class="grid sm:grid-cols-3 gap-3">
      <div>
        <label :class="lbl">ارز</label>
        <PickerField
          v-model="form.currency" :options="currencyOptions" :clearable="false"
        />
      </div>
      <div>
        <label :class="lbl">ارزش ارزی</label>
        <input v-model="form.amount" :class="inp" inputmode="decimal" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">بانک عامل</label>
        <PickerField
          v-model="form.bank" :options="bankOptions"
          placeholder="بانک را انتخاب کنید…" search-placeholder="نام بانک…"
        />
      </div>
    </div>

    <!-- گیت‌ها: هر تاریخ یک دروازه است که پرونده باید رد کند -->
    <div class="border-t border-slate-100 pt-3">
      <p class="text-xs text-slate-400 mb-2">
        تاریخ‌ها — فاصله‌ی بین این‌ها همان چیزی است که گزارش‌ها از آن ساخته می‌شوند.
      </p>
      <div class="grid sm:grid-cols-2 gap-3">
        <div>
          <label :class="lbl">تاریخ ثبت سفارش</label>
          <input v-model="form.registered_on" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">اعتبار ثبت سفارش</label>
          <input v-model="form.valid_until" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">ورود به صف تخصیص ارز</label>
          <input v-model="form.queued_on" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">تایید تخصیص ارز</label>
          <input v-model="form.allocated_on" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">مهلت خرید ارز</label>
          <input v-model="form.purchase_deadline" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">
            انتظار اعلامی بانک (روز)
            <span class="text-slate-400">— معیار «دیرکرد»</span>
          </label>
          <input
            v-model.number="form.expected_queue_days" :class="inp"
            inputmode="numeric" dir="ltr"
          />
        </div>
      </div>
    </div>

    <div class="grid sm:grid-cols-2 gap-3">
      <div>
        <label :class="lbl">وضعیت</label>
        <PickerField
          v-model="form.status" :options="statusOptions" :clearable="false"
          search-placeholder="مرحله پرونده…"
        />
      </div>
    </div>

    <div>
      <label :class="lbl">توضیحات</label>
      <textarea v-model="form.note" :class="inp" rows="2" />
    </div>

    <SupplierForm
      v-if="showSupplierForm"
      default-origin="foreign"
      @close="showSupplierForm = false"
      @saved="afterSupplierAdded"
    />
  </FormModal>
</template>
