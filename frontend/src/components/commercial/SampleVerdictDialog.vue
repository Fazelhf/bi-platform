<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import { faDate } from "@/utils/adminFormat";
import {
  commercialApi,
  type QuoteReason,
  type Sample,
} from "@/api/commercial";

/**
 * تایید یا رد نمونه.
 *
 * One screen for a decision that is four facts at once — the outcome, the
 * date, the person, and on a rejection the reason. They go to the server in a
 * single call, so a sample never sits in the state «رد شد» with no reason
 * attached, which is the state someone would screenshot and argue about.
 *
 * A rejection reason is required and a rejection note is asked for, because
 * the value of a rejected sample is entirely in what it teaches the next
 * person who buys this material.
 */
const props = defineProps<{ sample: Sample }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
const lbl = "text-xs text-slate-500 mb-1 block";

const reasons = ref<QuoteReason[]>([]);
const saving = ref(false);
const error = ref("");

const approve = ref(props.sample.status !== "rejected");
const decidedOn = ref(
  props.sample.decided_on ?? new Date().toISOString().slice(0, 10),
);
const reason = ref<number | null>(props.sample.reason);
const labNote = ref(props.sample.lab_note);

const reasonOptions = computed(
  () => reasons.value.map((r) => ({ value: r.id, label: r.name_fa })),
);

onMounted(async () => {
  reasons.value = await commercialApi.reasons("sample");
});

async function save() {
  if (!approve.value && !reason.value) {
    error.value = "برای رد نمونه، دلیل رد را انتخاب کنید.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await commercialApi.sampleVerdict(props.sample.id, {
      approve: approve.value,
      decided_on: decidedOn.value || null,
      reason: approve.value ? null : reason.value,
      lab_note: labNote.value,
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
    title="نتیجه بررسی نمونه"
    :subtitle="`${sample.sample_no} · ${sample.material_name} از ${sample.supplier_name}`"
    :saving="saving"
    :error="error"
    save-label="ثبت نتیجه"
    @close="emit('close')"
    @save="save"
  >
    <div v-if="sample.spec" class="bg-slate-50 rounded-xl px-3 py-2">
      <p class="text-xs text-slate-400">مشخصات درخواستی</p>
      <p class="text-sm text-ink">{{ sample.spec }}</p>
    </div>

    <p class="text-xs text-slate-400">
      درخواست {{ faDate(sample.requested_on) }}
      <span v-if="sample.received_on"> · دریافت {{ faDate(sample.received_on) }}</span>
    </p>

    <!-- The verdict itself: two tiles rather than a dropdown, because this is
         the one field on the screen that must not be set by accident. -->
    <div class="grid grid-cols-2 gap-2">
      <button
        type="button"
        class="rounded-xl border-2 px-3 py-3 text-sm transition-colors"
        :class="approve
          ? 'border-emerald-400 bg-emerald-50 text-emerald-700 font-medium'
          : 'border-slate-200 text-slate-500 hover:bg-slate-50'"
        @click="approve = true"
      >✔ تایید می‌شود</button>
      <button
        type="button"
        class="rounded-xl border-2 px-3 py-3 text-sm transition-colors"
        :class="!approve
          ? 'border-red-400 bg-red-50 text-red-600 font-medium'
          : 'border-slate-200 text-slate-500 hover:bg-slate-50'"
        @click="approve = false"
      >✕ رد می‌شود</button>
    </div>

    <div class="grid sm:grid-cols-2 gap-3">
      <div>
        <label :class="lbl">تاریخ تصمیم *</label>
        <input v-model="decidedOn" :class="inp" type="date" dir="ltr" />
      </div>
      <div v-if="!approve">
        <label :class="lbl">دلیل رد *</label>
        <PickerField
          v-model="reason" :options="reasonOptions"
          placeholder="دلیل رد را انتخاب کنید…"
        />
      </div>
    </div>

    <div>
      <label :class="lbl">
        نتیجه آزمایش
        <span v-if="!approve" class="text-slate-400">— چه چیزی اندازه‌گیری شد</span>
      </label>
      <textarea
        v-model="labNote" :class="inp" rows="3"
        :placeholder="approve
          ? 'مثلاً گرماژ ۴۸، مطابق مشخصات'
          : 'مثلاً گرماژ ۴۶ اندازه‌گیری شد، خارج از تلورانس ±۱'"
      />
    </div>

    <p class="text-xs text-slate-400">
      نام شما و همین تاریخ روی نمونه ثبت می‌شود، تا اگر محموله با نمونه نخواند
      معلوم باشد چه چیزی و بر چه اساسی تایید شده بود.
    </p>
  </FormModal>
</template>
