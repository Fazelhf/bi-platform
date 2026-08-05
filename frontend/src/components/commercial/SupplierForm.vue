<script setup lang="ts">
import { ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import { apiError } from "@/components/crm/formError";
import { commercialApi, type Supplier } from "@/api/commercial";

/** افزودن / ویرایش تامین‌کننده. */
const props = defineProps<{ supplier?: Supplier | null }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";

const saving = ref(false);
const error = ref("");

const form = ref({
  name_fa: props.supplier?.name_fa ?? "",
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
      <div class="col-span-2">
        <label class="text-xs text-slate-500 mb-1 block">نام شرکت *</label>
        <input v-model="form.name_fa" :class="inp" placeholder="مثلاً بازرگانی پارس گستر" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">شخص تماس</label>
        <input v-model="form.contact_name" :class="inp" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">نوع فعالیت</label>
        <input v-model="form.activity" :class="inp" placeholder="مثلاً تولید فیلم پلاستیکی" />
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
