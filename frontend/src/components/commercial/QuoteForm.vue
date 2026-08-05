<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import { apiError } from "@/components/crm/formError";
import MoneyInput from "@/components/MoneyInput.vue";
import { useMoney } from "@/composables/useMoney";
import {
  commercialApi,
  type PurchaseRequest,
  type Quote,
  type Supplier,
} from "@/api/commercial";

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
const saving = ref(false);
const error = ref("");

const form = ref({
  supplier: props.quote?.supplier ?? null as number | null,
  unit_price_rial: props.quote?.unit_price_rial ?? "",
  quoted_on: props.quote?.quoted_on ?? new Date().toISOString().slice(0, 10),
  delivery_days: props.quote?.delivery_days ?? 0,
  validity_days: props.quote?.validity_days ?? 0,
  note: props.quote?.note ?? "",
});

/** One price per supplier per استعلام, so the ones already in are hidden. */
const choices = computed(() =>
  suppliers.value.filter(
    (s) => s.id === props.quote?.supplier || !props.takenSupplierIds.includes(s.id),
  ),
);

const lineTotal = computed(() =>
  exact(Number(form.value.unit_price_rial || 0) * Number(props.request.quantity || 0), true),
);

onMounted(async () => {
  suppliers.value = await commercialApi.suppliers({ is_active: true });
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
      <select v-model="form.supplier" :class="inp">
        <option :value="null">انتخاب کنید…</option>
        <option v-for="s in choices" :key="s.id" :value="s.id">{{ s.name_fa }}</option>
      </select>
      <p v-if="!choices.length" class="text-xs text-amber-600 mt-1">
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

    <div>
      <label class="text-xs text-slate-500 mb-1 block">توضیح</label>
      <input v-model="form.note" :class="inp" />
    </div>
  </FormModal>
</template>
