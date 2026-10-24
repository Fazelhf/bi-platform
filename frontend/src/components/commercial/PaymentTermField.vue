<script setup lang="ts">
import { computed, ref } from "vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import { commercialApi, type PaymentTerm } from "@/api/commercial";

/**
 * زمان‌بندی پرداخت — the list, plus a way to add to it on the spot.
 *
 * The terms are a table the department keeps, but the moment a supplier
 * offers «۴۵ روزه» is the middle of entering a quote, not a visit to a
 * settings page. So a new term is added from here and chosen at once.
 */
const props = defineProps<{ modelValue: number | null; terms: PaymentTerm[] }>();
const emit = defineEmits<{
  (e: "update:modelValue", v: number | null): void;
  (e: "added", t: PaymentTerm): void;
}>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";

const options = computed(() => props.terms.map((t) => ({
  value: t.id,
  label: t.name_fa,
  hint: Number(t.advance_pct)
    ? `${t.advance_pct}٪ پیش‌پرداخت${t.days ? ` · مابقی ${t.days} روز` : ""}`
    : (t.days ? `${t.days} روز پس از تحویل` : "بدون مهلت"),
})));

const adding = ref(false);
const name = ref("");
const days = ref<number | "">("");
const saving = ref(false);
const error = ref("");

/** «۴۵ روزه» → 45, so the usual case needs only the name. */
function guessDays(text: string): number | "" {
  const latin = text.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)));
  const m = latin.match(/\d+/);
  return m ? Number(m[0]) : "";
}

async function add() {
  if (!name.value.trim()) return;
  saving.value = true;
  error.value = "";
  try {
    const term = await commercialApi.savePaymentTerm({
      name_fa: name.value.trim(),
      days: days.value === "" ? guessDays(name.value) || 0 : days.value,
      is_active: true,
    });
    emit("added", term);
    emit("update:modelValue", term.id);
    adding.value = false;
    name.value = "";
    days.value = "";
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div>
    <PickerField
      :model-value="modelValue" :options="options"
      placeholder="مثلاً ۶۰ روزه…"
      @update:model-value="emit('update:modelValue', $event as number | null)"
    />
    <button
      v-if="!adding"
      type="button"
      class="text-xs text-slate-500 hover:text-ink mt-1"
      @click="adding = true"
    >+ زمان‌بندی تازه، که در لیست نیست</button>
    <div v-else class="mt-2 bg-slate-50 rounded-xl p-2 space-y-2">
      <div class="grid grid-cols-3 gap-2">
        <input
          v-model="name" :class="inp" class="col-span-2"
          placeholder="نام، مثلاً ۴۵ روزه"
          @keydown.enter.prevent="add"
        />
        <input
          v-model.number="days" :class="inp" inputmode="numeric"
          :placeholder="`روز${guessDays(name) !== '' ? ` (${guessDays(name)})` : ''}`"
        />
      </div>
      <p v-if="error" class="text-xs text-red-500">{{ error }}</p>
      <div class="flex gap-2">
        <button
          type="button" :disabled="saving || !name.trim()"
          class="bg-panel text-white rounded-lg px-3 py-1.5 text-xs disabled:opacity-50"
          @click="add"
        >افزودن و انتخاب</button>
        <button
          type="button" class="text-xs text-slate-500 px-2"
          @click="adding = false"
        >انصراف</button>
      </div>
    </div>
  </div>
</template>
