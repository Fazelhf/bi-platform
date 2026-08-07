<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import { apiError } from "@/components/crm/formError";
import MoneyInput from "@/components/MoneyInput.vue";
import { useMoney } from "@/composables/useMoney";
import {
  foreignApi,
  type ForeignOrder,
  type ForeignOptions,
  type Shipment,
} from "@/api/commercialForeign";

/**
 * محموله — one container.
 *
 * The Free Days block sits apart and shows what the settings mean in Rial,
 * because those three fields are the difference between a container that
 * costs nothing to wait on and one that costs fifty million a day.
 */
const props = defineProps<{
  order: ForeignOrder;
  shipment?: Shipment | null;
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
const lbl = "text-xs text-slate-500 mb-1 block";

const { exact, unitLabel } = useMoney();
const options = ref<ForeignOptions | null>(null);
const saving = ref(false);
const error = ref("");

const form = ref({
  lot_no: props.shipment?.lot_no ?? "",
  bl_no: props.shipment?.bl_no ?? "",
  container_no: props.shipment?.container_no ?? "",
  carrier: props.shipment?.carrier ?? "",
  origin_port: props.shipment?.origin_port ?? "",
  destination_port: props.shipment?.destination_port ?? "",
  goods_desc: props.shipment?.goods_desc ?? props.order.goods_desc ?? "",
  weight_ton: props.shipment?.weight_ton ?? "",
  value_amount: props.shipment?.value_amount ?? "",
  etd: props.shipment?.etd ?? "",
  eta: props.shipment?.eta ?? "",
  arrived_on: props.shipment?.arrived_on ?? "",
  released_on: props.shipment?.released_on ?? "",
  declared_on: props.shipment?.declared_on ?? "",
  cleared_on: props.shipment?.cleared_on ?? "",
  free_days: props.shipment?.free_days ?? 0,
  demurrage_daily_rial: props.shipment?.demurrage_daily_rial ?? "",
  storage_daily_rial: props.shipment?.storage_daily_rial ?? "",
  status: props.shipment?.status ?? "ready",
  note: props.shipment?.note ?? "",
});

/** What one day of delay costs once the free days are gone. */
const dailyCost = computed(() =>
  exact(
    Number(form.value.demurrage_daily_rial || 0) +
    Number(form.value.storage_daily_rial || 0),
    true,
  ),
);

const needsArrival = computed(
  () => form.value.status === "at_port" || form.value.status === "customs",
);

// The API refuses these statuses without an arrival date, because every
// day-count and every Rial of demurrage is measured from it.
watch(() => form.value.status, (status) => {
  if ((status === "at_port" || status === "customs") && !form.value.arrived_on) {
    form.value.arrived_on = new Date().toISOString().slice(0, 10);
  }
  if (status === "cleared" && !form.value.cleared_on) {
    form.value.cleared_on = new Date().toISOString().slice(0, 10);
  }
});

onMounted(async () => { options.value = await foreignApi.options(); });

async function save() {
  saving.value = true;
  error.value = "";
  try {
    const payload: Record<string, unknown> = { ...form.value, order: props.order.id };
    for (const key of [
      "etd", "eta", "arrived_on", "released_on", "declared_on", "cleared_on",
    ]) {
      if (!payload[key]) payload[key] = null;
    }
    for (const key of ["demurrage_daily_rial", "storage_daily_rial", "value_amount"]) {
      if (!payload[key]) payload[key] = 0;
    }
    await foreignApi.saveShipment(payload, props.shipment?.id);
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
    :title="shipment ? 'ویرایش محموله' : 'محموله جدید'"
    :subtitle="`${order.file_no} · ${order.pi_no}`"
    :saving="saving"
    :error="error"
    wide
    @close="emit('close')"
    @save="save"
  >
    <div class="grid sm:grid-cols-3 gap-3">
      <div>
        <label :class="lbl">شماره کانتینر</label>
        <input v-model="form.container_no" :class="inp" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">شماره بارنامه (BL)</label>
        <input v-model="form.bl_no" :class="inp" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">ردیف</label>
        <input v-model="form.lot_no" :class="inp" dir="ltr" placeholder="مثلاً ۱" />
      </div>
      <div>
        <label :class="lbl">شرکت حمل</label>
        <input v-model="form.carrier" :class="inp" />
      </div>
      <div>
        <label :class="lbl">بندر مبدأ</label>
        <input v-model="form.origin_port" :class="inp" />
      </div>
      <div>
        <label :class="lbl">بندر مقصد</label>
        <input v-model="form.destination_port" :class="inp" />
      </div>
      <div class="sm:col-span-2">
        <label :class="lbl">شرح محموله</label>
        <input v-model="form.goods_desc" :class="inp" />
      </div>
      <div>
        <label :class="lbl">وزن (تن)</label>
        <input v-model="form.weight_ton" :class="inp" inputmode="decimal" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">ارزش ({{ order.currency }})</label>
        <input v-model="form.value_amount" :class="inp" inputmode="decimal" dir="ltr" />
      </div>
      <div class="sm:col-span-2">
        <label :class="lbl">وضعیت</label>
        <select v-model="form.status" :class="inp">
          <option
            v-for="s in options?.shipment_statuses ?? []" :key="s.value" :value="s.value"
          >{{ s.label }}</option>
        </select>
      </div>
    </div>

    <div class="border-t border-slate-100 pt-3">
      <p class="text-xs text-slate-400 mb-2">مسیر</p>
      <div class="grid sm:grid-cols-3 gap-3">
        <div>
          <label :class="lbl">ETD — حرکت از مبدأ</label>
          <input v-model="form.etd" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">ETA — رسیدن تخمینی</label>
          <input v-model="form.eta" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">
            رسیدن واقعی به بندر
            <span v-if="needsArrival" class="text-red-500">*</span>
          </label>
          <input v-model="form.arrived_on" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">آزادسازی بار</label>
          <input v-model="form.released_on" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">اظهار گمرکی</label>
          <input v-model="form.declared_on" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">ترخیص</label>
          <input v-model="form.cleared_on" :class="inp" type="date" dir="ltr" />
        </div>
      </div>
      <p v-if="needsArrival" class="text-xs text-slate-400 mt-1">
        بدون تاریخ رسیدن، هیچ روزی شمرده نمی‌شود و دموراژ صفر می‌ماند.
      </p>
    </div>

    <!-- The part that costs money on its own -->
    <div class="border-t border-slate-100 pt-3">
      <p class="text-xs text-slate-400 mb-2">
        دموراژ و انبارداری — تنها هزینه‌هایی که خودشان بزرگ می‌شوند
      </p>
      <div class="grid sm:grid-cols-3 gap-3">
        <div>
          <label :class="lbl">Free Days</label>
          <input v-model.number="form.free_days" :class="inp" inputmode="numeric" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">دموراژ روزانه ({{ unitLabel }})</label>
          <MoneyInput v-model="form.demurrage_daily_rial" :class="inp" />
        </div>
        <div>
          <label :class="lbl">انبارداری روزانه ({{ unitLabel }})</label>
          <MoneyInput v-model="form.storage_daily_rial" :class="inp" />
        </div>
      </div>
      <div class="bg-amber-50 rounded-xl px-3 py-2 text-sm flex justify-between mt-2">
        <span class="text-amber-700">هر روز تأخیر پس از پایان Free Days</span>
        <span class="ltr-nums font-medium text-amber-800">{{ dailyCost }}</span>
      </div>
    </div>

    <div>
      <label :class="lbl">توضیحات</label>
      <textarea v-model="form.note" :class="inp" rows="2" />
    </div>
  </FormModal>
</template>
