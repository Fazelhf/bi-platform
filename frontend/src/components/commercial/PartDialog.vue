<script setup lang="ts">
import { computed, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import JalaliDateField from "@/components/JalaliDateField.vue";
import { apiError } from "@/components/crm/formError";
import { commercialApi, type DeliveryPart, type PurchaseOrder } from "@/api/commercial";
import { todayIso } from "@/utils/jalali";
import { num } from "@/utils/format";

/**
 * ثبت یا ویرایش یک پارت ارسال.
 *
 * Opens on what is left, because the usual last part is «the rest», and on
 * today's date, because a part is usually recorded the day it leaves.
 */
const props = defineProps<{ order: PurchaseOrder; part?: DeliveryPart | null }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";

/** Still to send — the order less every other part, this one excluded. */
const left = computed(() => {
  const others = props.order.parts
    .filter((p) => p.id !== props.part?.id)
    .reduce((sum, p) => sum + Number(p.quantity), 0);
  return Math.max(Number(props.order.quantity) - others, 0);
});

const quantity = ref(props.part ? props.part.quantity : String(left.value));
const shippedOn = ref(props.part?.shipped_on ?? todayIso());
const arrived = ref(!!props.part?.delivered_on);
const deliveredOn = ref(props.part?.delivered_on ?? todayIso());
const note = ref(props.part?.note ?? "");
const saving = ref(false);
const error = ref("");

const partNo = computed(() =>
  props.part
    ? props.order.parts.findIndex((p) => p.id === props.part!.id) + 1
    : props.order.parts.length + 1,
);

async function save() {
  saving.value = true;
  error.value = "";
  try {
    await commercialApi.savePart({
      order: props.order.id,
      quantity: quantity.value,
      shipped_on: shippedOn.value,
      delivered_on: arrived.value ? deliveredOn.value : null,
      note: note.value,
    }, props.part?.id);
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
    :title="`پارت ${num(partNo)}`"
    :subtitle="`${order.order_no} · ${order.supplier_name} · ${order.material_name}`"
    :saving="saving"
    :error="error"
    @close="emit('close')"
    @save="save"
  >
    <div>
      <label class="text-xs text-slate-500 mb-1 block">
        مقدار این پارت ({{ order.material_unit }}) *
      </label>
      <input v-model="quantity" :class="inp" inputmode="decimal" />
      <p class="text-xs text-slate-400 mt-1">
        از {{ num(order.quantity) }} {{ order.material_unit }}،
        {{ num(left) }} هنوز ارسال نشده.
        <button
          v-if="Number(quantity) !== left"
          type="button" class="text-emerald-700 hover:underline"
          @click="quantity = String(left)"
        >همه‌ی باقی‌مانده</button>
      </p>
    </div>
    <div>
      <label class="text-xs text-slate-500 mb-1 block">تاریخ ارسال *</label>
      <JalaliDateField v-model="shippedOn" :clearable="false" />
    </div>
    <label class="flex items-center gap-2 text-sm text-ink">
      <input v-model="arrived" type="checkbox" class="rounded" />
      این پارت به کارخانه رسیده
    </label>
    <div v-if="arrived">
      <label class="text-xs text-slate-500 mb-1 block">تاریخ تحویل</label>
      <JalaliDateField v-model="deliveredOn" :clearable="false" />
    </div>
    <div>
      <label class="text-xs text-slate-500 mb-1 block">توضیح (اختیاری)</label>
      <input v-model="note" :class="inp" placeholder="شماره بارنامه، راننده، …" />
    </div>
  </FormModal>
</template>
