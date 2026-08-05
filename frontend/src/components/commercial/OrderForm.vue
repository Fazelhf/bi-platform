<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import { apiError } from "@/components/crm/formError";
import MoneyInput from "@/components/MoneyInput.vue";
import { useMoney } from "@/composables/useMoney";
import {
  commercialApi,
  type Material,
  type PurchaseOrder,
  type PurchaseRequest,
  type Quote,
  type Supplier,
} from "@/api/commercial";

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
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";

const { unitLabel, exact } = useMoney();
const materials = ref<Material[]>([]);
const suppliers = ref<Supplier[]>([]);
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
  material: props.order?.material ?? props.request?.material ?? null as number | null,
  supplier: props.order?.supplier ?? props.quote?.supplier ?? null as number | null,
  quantity: props.order?.quantity ?? props.request?.quantity ?? "",
  unit_price_rial: props.order?.unit_price_rial ?? props.quote?.unit_price_rial ?? "",
  ordered_on: props.order?.ordered_on ?? today,
  delivered_on: props.order?.delivered_on ?? "",
  status: props.order?.status ?? "pending",
  note: props.order?.note ?? "",
});

const total = computed(() =>
  exact(Number(form.value.quantity || 0) * Number(form.value.unit_price_rial || 0), true),
);

const materialUnit = computed(
  () => materials.value.find((m) => m.id === form.value.material)?.unit_label ?? "",
);

// «تحویل شد» without a date is a status the reports cannot use — every lead
// time would skip it — so the field fills itself the moment it is needed.
watch(() => form.value.status, (status) => {
  if (status === "delivered" && !form.value.delivered_on) {
    form.value.delivered_on = today;
  }
});

onMounted(async () => {
  [materials.value, suppliers.value] = await Promise.all([
    commercialApi.materials({ is_active: true }),
    commercialApi.suppliers({ is_active: true }),
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
        <select v-model="form.material" :class="inp">
          <option :value="null">انتخاب کنید…</option>
          <option v-for="m in materials" :key="m.id" :value="m.id">
            {{ m.name_fa }} ({{ m.unit_label }})
          </option>
        </select>
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">تامین‌کننده *</label>
        <select v-model="form.supplier" :class="inp">
          <option :value="null">انتخاب کنید…</option>
          <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.name_fa }}</option>
        </select>
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

    <div class="bg-slate-50 rounded-xl px-3 py-2 text-sm flex justify-between">
      <span class="text-slate-500">مبلغ کل</span>
      <span class="ltr-nums font-medium text-ink">{{ total }}</span>
    </div>

    <div class="grid sm:grid-cols-3 gap-3">
      <div>
        <label class="text-xs text-slate-500 mb-1 block">تاریخ سفارش</label>
        <input v-model="form.ordered_on" :class="inp" type="date" dir="ltr" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">وضعیت</label>
        <select v-model="form.status" :class="inp">
          <option v-for="s in STATUSES" :key="s.value" :value="s.value">{{ s.label }}</option>
        </select>
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">
          تاریخ تحویل
          <span v-if="form.status === 'delivered'" class="text-red-500">*</span>
        </label>
        <input v-model="form.delivered_on" :class="inp" type="date" dir="ltr" />
      </div>
    </div>

    <div>
      <label class="text-xs text-slate-500 mb-1 block">توضیحات</label>
      <textarea v-model="form.note" :class="inp" rows="2" />
    </div>
  </FormModal>
</template>
