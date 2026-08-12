<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import { useMoney } from "@/composables/useMoney";
import {
  commercialApi,
  type PurchaseRequest,
  type Quote,
  type QuoteReason,
} from "@/api/commercial";

/**
 * انتخاب تامین‌کننده.
 *
 * The losers are on this screen on purpose. Recording only the winner would
 * throw away the answer to «چرا از بقیه نخریدیم؟» — which is the whole reason
 * the price file is kept, and the number every supplier statistic is built on.
 */
const props = defineProps<{
  request: PurchaseRequest;
  quotes: Quote[];
  /** Opened from a «برنده» button on one row — start with that one chosen. */
  preselect?: number | null;
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";

const { exact, unitLabel } = useMoney();

const winReasons = ref<QuoteReason[]>([]);
const loseReasons = ref<QuoteReason[]>([]);
const saving = ref(false);
const error = ref("");

const current = props.quotes.find((q) => q.is_selected) ?? null;
const opening = props.preselect
  ? props.quotes.find((q) => q.id === props.preselect) ?? current
  : current;

const winner = ref<number | null>(opening?.id ?? null);
const winReason = ref<number | null>(
  // Only carry a reason over when the same quote is still the winner — the
  // reason «قیمت مناسب» belonged to the old choice, not to this one.
  opening && opening.id === current?.id ? opening.reason : null,
);
const winNote = ref(
  opening && opening.id === current?.id ? opening.decision_note : "",
);

const winReasonOptions = computed(
  () => winReasons.value.map((r) => ({ value: r.id, label: r.name_fa })),
);
const loseReasonOptions = computed(
  () => loseReasons.value.map((r) => ({ value: r.id, label: r.name_fa })),
);

/** Per losing quote: why it was not chosen. Keyed by quote id. */
const rejections = ref<Record<number, { reason: number | null; note: string }>>(
  Object.fromEntries(
    props.quotes.map((q) => [
      q.id,
      { reason: q.is_selected ? null : q.reason, note: q.is_selected ? "" : q.decision_note },
    ]),
  ),
);

onMounted(async () => {
  [winReasons.value, loseReasons.value] = await Promise.all([
    commercialApi.reasons("win"),
    commercialApi.reasons("lose"),
  ]);
});

async function save() {
  if (!winner.value) {
    error.value = "تامین‌کننده برنده را انتخاب کنید.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await commercialApi.award(props.request.id, {
      quote: winner.value,
      reason: winReason.value,
      decision_note: winNote.value,
      rejections: props.quotes
        .filter((q) => q.id !== winner.value)
        .map((q) => ({
          quote: q.id,
          reason: rejections.value[q.id]?.reason ?? null,
          decision_note: rejections.value[q.id]?.note ?? "",
        })),
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
    title="انتخاب تامین‌کننده"
    :subtitle="`${request.request_no} · ${request.material_name} × ${request.quantity} ${request.material_unit}`"
    :saving="saving"
    :error="error"
    save-label="ثبت انتخاب"
    wide
    @close="emit('close')"
    @save="save"
  >
    <p class="text-xs text-slate-400">
      یکی را برنده کنید و برای بقیه دلیل رد را ثبت کنید. همین دلیل‌ها هستند که
      دفعه بعد قیمت‌گیری را آسان می‌کنند.
    </p>

    <div class="space-y-2">
      <label
        v-for="q in quotes" :key="q.id"
        class="block rounded-xl border p-3 cursor-pointer transition-colors"
        :class="winner === q.id
          ? 'border-emerald-400 bg-emerald-50'
          : 'border-slate-200 hover:bg-slate-50'"
      >
        <div class="flex items-start gap-3">
          <input v-model="winner" type="radio" :value="q.id" class="mt-1 shrink-0" />
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span class="font-medium text-ink">{{ q.supplier_name }}</span>
              <span class="ltr-nums text-sm text-ink">
                {{ exact(q.unit_price_rial, true) }}
              </span>
              <span class="text-xs text-slate-400">
                تحویل {{ q.delivery_days }} روز · اعتبار {{ q.validity_days }} روز
              </span>
            </div>
            <p class="text-xs text-slate-400 mt-0.5">
              مبلغ کل: <span class="ltr-nums">{{ exact(q.total_rial, true) }}</span>
              <span v-if="q.note"> · {{ q.note }}</span>
            </p>

            <!-- The winner names why it was chosen; everyone else why not. -->
            <div v-if="winner === q.id" class="mt-2 grid sm:grid-cols-2 gap-2" @click.stop>
              <PickerField
                v-model="winReason" :options="winReasonOptions"
                placeholder="دلیل انتخاب…"
              />
              <input v-model="winNote" :class="inp" placeholder="توضیح (اختیاری)" />
            </div>
            <div
              v-else-if="rejections[q.id]"
              class="mt-2 grid sm:grid-cols-2 gap-2"
              @click.stop
            >
              <PickerField
                v-model="rejections[q.id].reason" :options="loseReasonOptions"
                placeholder="دلیل عدم انتخاب…"
              />
              <input
                v-model="rejections[q.id].note" :class="inp"
                placeholder="توضیح (اختیاری)"
              />
            </div>
          </div>
        </div>
      </label>
    </div>

    <p class="text-xs text-slate-400">
      همه مبالغ به {{ unitLabel }} است.
    </p>
  </FormModal>
</template>
