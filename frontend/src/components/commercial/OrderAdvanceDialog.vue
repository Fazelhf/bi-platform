<script setup lang="ts">
import { computed, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import JalaliDateField from "@/components/JalaliDateField.vue";
import { apiError } from "@/components/crm/formError";
import { commercialApi, type OrderStatus, type PurchaseOrder } from "@/api/commercial";
import { ORDER_STEPS } from "@/components/commercial/orderFlow";
import { todayIso } from "@/utils/jalali";

/**
 * یک قدم در جریان سفارش — or its cancellation.
 *
 * A dialog rather than a bare click because two of the steps carry a fact
 * with them: «تحویل شد» needs the day it arrived (every lead-time figure is
 * built on it), and «لغو» needs a why, or the file reads as a purchase that
 * simply vanished.
 */
const props = defineProps<{ order: PurchaseOrder; target: OrderStatus }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";

const deliveredOn = ref(todayIso());
const note = ref("");
const saving = ref(false);
const error = ref("");

const cancelling = computed(() => props.target === "cancelled");
const title = computed(() =>
  cancelling.value
    ? "لغو سفارش"
    : ORDER_STEPS.find((s) => s.status === props.target)?.action ?? "",
);

async function save() {
  if (cancelling.value && !note.value.trim()) {
    error.value = "علت لغو را بنویسید.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await commercialApi.advanceOrder(props.order.id, {
      status: props.target,
      delivered_on: props.target === "delivered" ? deliveredOn.value || null : undefined,
      note: note.value,
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
    :title="title"
    :subtitle="`${order.order_no} · ${order.supplier_name} · ${order.material_name}`"
    :saving="saving"
    :error="error"
    :save-label="cancelling ? 'لغو سفارش' : 'ثبت'"
    @close="emit('close')"
    @save="save"
  >
    <div v-if="target === 'delivered'">
      <label class="text-xs text-slate-500 mb-1 block">تاریخ تحویل *</label>
      <JalaliDateField v-model="deliveredOn" :clearable="false" />
      <p class="text-xs text-slate-400 mt-1">
        زمان واقعی تحویل از همین تاریخ حساب می‌شود و در کارنامه تامین‌کننده می‌آید.
      </p>
    </div>
    <p v-if="cancelling" class="text-xs text-slate-500">
      با لغو، درخواست به «تامین‌کننده انتخاب شد» برمی‌گردد و می‌شود برنده را عوض کرد
      یا دوباره سفارش داد.
    </p>
    <div>
      <label class="text-xs text-slate-500 mb-1 block">
        {{ cancelling ? "علت لغو *" : "توضیح (اختیاری)" }}
      </label>
      <textarea v-model="note" :class="inp" rows="2" />
    </div>
  </FormModal>
</template>
