<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import { commercialApi, type Supplier } from "@/api/commercial";

/**
 * افزودن / ویرایش تامین‌کننده — one form for both halves of بازرگانی.
 *
 * `origin` decides which half a company belongs to, and the two fields that
 * only matter abroad (نام لاتین, کشور) appear when it is set to خارجی. Without
 * this control there was no way to record a foreign mill at all: the API left
 * `origin` out of the payload, so every seller created here came back «داخلی»
 * and turned up in the domestic supplier list.
 */
const props = defineProps<{
  supplier?: Supplier | null;
  /** Opened from the foreign side, so the new company starts as خارجی. */
  defaultOrigin?: "domestic" | "foreign";
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";

const saving = ref(false);
const error = ref("");
const countries = ref<string[]>([]);
const activities = ref<string[]>([]);

const form = ref({
  name_fa: props.supplier?.name_fa ?? "",
  name_en: props.supplier?.name_en ?? "",
  origin: props.supplier?.origin ?? props.defaultOrigin ?? "domestic",
  country: props.supplier?.country ?? "",
  code: props.supplier?.code ?? "",
  contact_name: props.supplier?.contact_name ?? "",
  mobile: props.supplier?.mobile ?? "",
  phone: props.supplier?.phone ?? "",
  email: props.supplier?.email ?? "",
  address: props.supplier?.address ?? "",
  activity: props.supplier?.activity ?? "",
  is_active: props.supplier?.is_active ?? true,
  note: props.supplier?.note ?? "",
});

const isForeign = computed(() => form.value.origin === "foreign");

const ORIGINS = [
  { value: "domestic", label: "داخلی", hint: "خرید ریالی از بازار داخل" },
  { value: "foreign", label: "خارجی", hint: "فروشنده پرونده واردات" },
];

const countryOptions = computed(
  () => countries.value.map((c) => ({ value: c, label: c })),
);
const activityOptions = computed(
  () => activities.value.map((a) => ({ value: a, label: a })),
);

onMounted(async () => {
  try {
    const s = await commercialApi.suggestions();
    countries.value = s.countries;
    activities.value = s.activities;
  } catch { /* suggestions are optional — the fields stay plain text */ }
});

async function save() {
  if (!form.value.name_fa.trim()) {
    error.value = "نام شرکت الزامی است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const payload: Record<string, unknown> = { ...form.value };
    if (!String(payload.code).trim()) delete payload.code;
    await commercialApi.saveSupplier(payload, props.supplier?.id);
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
    :title="supplier ? 'ویرایش تامین‌کننده' : 'تامین‌کننده جدید'"
    :subtitle="supplier?.name_fa"
    :saving="saving"
    :error="error"
    wide
    @close="emit('close')"
    @save="save"
  >
    <div class="grid grid-cols-2 gap-3">
      <div>
        <label class="text-xs text-slate-500 mb-1 block">نوع تامین‌کننده</label>
        <PickerField v-model="form.origin" :options="ORIGINS" :clearable="false" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">
          کشور <span v-if="isForeign" class="text-slate-400">— مبدأ بار</span>
        </label>
        <PickerField
          v-model="form.country" :options="countryOptions" creatable
          placeholder="مثلاً چین"
        />
      </div>
      <div :class="isForeign ? '' : 'col-span-2'">
        <label class="text-xs text-slate-500 mb-1 block">نام شرکت *</label>
        <input v-model="form.name_fa" :class="inp" placeholder="مثلاً بازرگانی پارس گستر" />
      </div>
      <div v-if="isForeign">
        <label class="text-xs text-slate-500 mb-1 block">
          نام لاتین <span class="text-slate-400">— روی اسناد</span>
        </label>
        <input v-model="form.name_en" :class="inp" dir="ltr" placeholder="Oriental Paper" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">شخص تماس</label>
        <input v-model="form.contact_name" :class="inp" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">نوع فعالیت</label>
        <PickerField
          v-model="form.activity" :options="activityOptions" creatable
          placeholder="مثلاً تولید فیلم پلاستیکی"
        />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">موبایل</label>
        <input v-model="form.mobile" :class="inp" inputmode="tel" dir="ltr" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">تلفن</label>
        <input v-model="form.phone" :class="inp" inputmode="tel" dir="ltr" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">ایمیل</label>
        <input v-model="form.email" :class="inp" type="email" dir="ltr" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">کد</label>
        <input v-model="form.code" :class="inp" placeholder="خودکار ساخته می‌شود" />
      </div>
      <div class="col-span-2">
        <label class="text-xs text-slate-500 mb-1 block">آدرس</label>
        <input v-model="form.address" :class="inp" />
      </div>
      <div class="col-span-2">
        <label class="text-xs text-slate-500 mb-1 block">توضیحات</label>
        <textarea v-model="form.note" :class="inp" rows="2" />
      </div>
    </div>

    <label class="flex items-center gap-2 text-sm text-ink">
      <input v-model="form.is_active" type="checkbox" class="rounded" />
      فعال
    </label>
  </FormModal>
</template>
