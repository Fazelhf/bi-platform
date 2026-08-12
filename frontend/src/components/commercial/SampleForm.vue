<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import {
  commercialApi,
  type Material,
  type PurchaseRequest,
  type Quote,
  type Sample,
  type Supplier,
} from "@/api/commercial";

/**
 * درخواست نمونه.
 *
 * Opened either on its own — the department is sizing up a supplier before
 * any استعلام — or from a request, in which case the کالا is already known
 * and comes pre-filled and locked to it.
 *
 * The verdict is deliberately *not* here. Approving a sample is a separate,
 * dated act by a named person, and putting a «تایید شد» option in the same
 * dropdown as «دریافت شد» invites it to be set while typing something else.
 */
const props = defineProps<{
  sample?: Sample | null;
  request?: PurchaseRequest | null;
  quote?: Quote | null;
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
const lbl = "text-xs text-slate-500 mb-1 block";

const materials = ref<Material[]>([]);
const suppliers = ref<Supplier[]>([]);
const saving = ref(false);
const error = ref("");

const today = new Date().toISOString().slice(0, 10);

const form = ref({
  supplier: props.sample?.supplier ?? props.quote?.supplier ?? (null as number | null),
  material: props.sample?.material ?? props.request?.material ?? (null as number | null),
  quantity: props.sample?.quantity ?? "",
  spec: props.sample?.spec ?? "",
  requested_on: props.sample?.requested_on ?? today,
  received_on: props.sample?.received_on ?? "",
  // Only the three pre-verdict states. تایید / رد go through the verdict
  // action, which also captures the date, the person and the reason.
  status: props.sample?.status ?? "requested",
  note: props.sample?.note ?? "",
});

/** Locked when the sample belongs to a request — that request names the کالا. */
const materialLocked = computed(() => !!props.request && !props.sample);

const OPEN_STATUSES = [
  { value: "requested", label: "درخواست شد", hint: "از تامین‌کننده خواسته شده" },
  { value: "received", label: "دریافت شد", hint: "رسیده، هنوز آزمایش نشده" },
  { value: "testing", label: "در حال آزمایش", hint: "دست کنترل کیفیت است" },
];

const materialOptions = computed(() => materials.value.map((m) => ({
  value: m.id, label: m.name_fa, hint: m.category_name || "",
  badge: m.unit_label, keywords: m.code,
})));
const supplierOptions = computed(() => suppliers.value.map((s) => ({
  value: s.id, label: s.name_fa, hint: s.activity,
  keywords: `${s.code} ${s.contact_name} ${s.mobile}`,
})));

const materialUnit = computed(
  () => materials.value.find((m) => m.id === form.value.material)?.unit_label ?? "",
);

onMounted(async () => {
  [materials.value, suppliers.value] = await Promise.all([
    commercialApi.materials({ is_active: true }),
    commercialApi.suppliers({ is_active: true }),
  ]);
});

async function save() {
  if (!form.value.supplier || !form.value.material) {
    error.value = "تامین‌کننده و کالا الزامی است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const payload: Record<string, unknown> = {
      ...form.value,
      request: props.sample?.request ?? props.request?.id ?? null,
      quote: props.sample?.quote ?? props.quote?.id ?? null,
      quantity: form.value.quantity || 0,
    };
    // An empty date is «هنوز نرسیده», not an invalid date.
    if (!payload.received_on) payload.received_on = null;
    await commercialApi.saveSample(payload, props.sample?.id);
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
    :title="sample ? `نمونه ${sample.sample_no}` : 'درخواست نمونه'"
    :subtitle="request?.request_no ? `از درخواست ${request.request_no}` : ''"
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
          v-model="form.supplier"
          :options="supplierOptions"
          placeholder="تامین‌کننده را انتخاب کنید…"
          search-placeholder="نام، فعالیت یا شماره تماس…"
        />
      </div>
      <div>
        <label :class="lbl">کالا *</label>
        <PickerField
          v-model="form.material"
          :options="materialOptions"
          :disabled="materialLocked"
          placeholder="کالا را انتخاب کنید…"
          search-placeholder="نام یا کد کالا…"
        />
        <p v-if="materialLocked" class="text-xs text-slate-400 mt-1">
          کالای این درخواست است و تغییر نمی‌کند.
        </p>
      </div>
      <div>
        <label :class="lbl">
          مقدار نمونه
          <span v-if="materialUnit" class="text-slate-400">({{ materialUnit }})</span>
        </label>
        <input v-model="form.quantity" :class="inp" inputmode="decimal" />
      </div>
      <div>
        <label :class="lbl">وضعیت</label>
        <PickerField v-model="form.status" :options="OPEN_STATUSES" :clearable="false" />
      </div>
      <div class="sm:col-span-2">
        <label :class="lbl">
          مشخصات درخواستی
          <span class="text-slate-400">— معیاری که نمونه با آن سنجیده می‌شود</span>
        </label>
        <input
          v-model="form.spec" :class="inp"
          placeholder="مثلاً گرماژ ۴۸، عرض ۸۰ سانتی‌متر، بدون لکه"
        />
      </div>
      <div>
        <label :class="lbl">تاریخ درخواست</label>
        <input v-model="form.requested_on" :class="inp" type="date" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">تاریخ دریافت</label>
        <input v-model="form.received_on" :class="inp" type="date" dir="ltr" />
      </div>
    </div>

    <div>
      <label :class="lbl">توضیحات</label>
      <textarea v-model="form.note" :class="inp" rows="2" />
    </div>

    <p class="text-xs text-slate-400">
      تایید یا رد نمونه از روی همین فهرست و با ثبت تاریخ و دلیل انجام می‌شود.
    </p>
  </FormModal>
</template>
