<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import MoneyInput from "@/components/MoneyInput.vue";
import {
  foreignApi,
  type Choice,
  type RateKind,
} from "@/api/commercialForeign";

/** ثبت دستی نرخ ارز. */
const props = defineProps<{
  currency?: string;
  kind?: RateKind;
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
const lbl = "text-xs text-slate-500 mb-1 block";

const currencies = ref<Choice[]>([]);
const kinds = ref<Choice[]>([]);
const saving = ref(false);
const error = ref("");

const form = ref({
  currency: props.currency ?? "USD",
  kind: (props.kind ?? "centre") as RateKind,
  on_date: new Date().toISOString().slice(0, 10),
  rate_rial: "",
  note: "",
});

const currencyOptions = computed(
  () => currencies.value.map((c) => ({ value: c.value, label: c.label })),
);
const kindOptions = computed(
  () => kinds.value.map((k) => ({ value: k.value, label: k.label })),
);

onMounted(async () => {
  const board = await foreignApi.rateBoard();
  currencies.value = board.currencies;
  kinds.value = board.kinds;
});

async function save() {
  if (!Number(form.value.rate_rial)) {
    error.value = "نرخ باید بزرگ‌تر از صفر باشد.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await foreignApi.saveRate({ ...form.value });
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
    title="ثبت نرخ ارز"
    :saving="saving"
    :error="error"
    @close="emit('close')"
    @save="save"
  >
    <div class="grid sm:grid-cols-2 gap-3">
      <div>
        <label :class="lbl">ارز</label>
        <PickerField v-model="form.currency" :options="currencyOptions" :clearable="false" />
      </div>
      <div>
        <label :class="lbl">نوع نرخ</label>
        <PickerField v-model="form.kind" :options="kindOptions" :clearable="false" />
      </div>
      <div>
        <label :class="lbl">تاریخ</label>
        <input v-model="form.on_date" :class="inp" type="date" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">نرخ (ریال)</label>
        <MoneyInput v-model="form.rate_rial" :class="inp" />
      </div>
    </div>

    <div>
      <label :class="lbl">توضیح</label>
      <input v-model="form.note" :class="inp" placeholder="مثلاً نرخ اعلامی کشتیرانی" />
    </div>

    <p class="text-xs text-slate-400">
      نرخی که دستی ثبت شود، با هیچ به‌روزرسانی خودکاری بازنویسی نمی‌شود.
    </p>
  </FormModal>
</template>
