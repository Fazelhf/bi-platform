<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import {
  commercialApi,
  type Material,
  type MaterialCategory,
  type UnitChoice,
} from "@/api/commercial";

/** افزودن / ویرایش کالای مصرفی. */
const props = defineProps<{ material?: Material | null }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";

const categories = ref<MaterialCategory[]>([]);
const units = ref<UnitChoice[]>([]);
const saving = ref(false);
const error = ref("");

const form = ref({
  name_fa: props.material?.name_fa ?? "",
  code: props.material?.code ?? "",
  category: props.material?.category ?? null,
  unit: props.material?.unit ?? "pcs",
  min_stock: props.material?.min_stock ?? "0",
  is_active: props.material?.is_active ?? true,
  note: props.material?.note ?? "",
});

const unitOptions = computed(
  () => units.value.map((u) => ({ value: u.value, label: u.label })),
);
const categoryOptions = computed(() => categories.value.map((c) => ({
  value: c.id,
  label: c.name_fa,
  badge: c.material_count ? `${c.material_count} کالا` : "",
})));

onMounted(async () => {
  [categories.value, units.value] = await Promise.all([
    commercialApi.categories(),
    commercialApi.units(),
  ]);
});

async function save() {
  if (!form.value.name_fa.trim()) {
    error.value = "نام کالا الزامی است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    // An empty code is omitted, not sent as "": the server derives one from
    // the name, and a Persian name yields no usable slug for a human to type.
    const payload: Record<string, unknown> = { ...form.value };
    if (!String(payload.code).trim()) delete payload.code;
    await commercialApi.saveMaterial(payload, props.material?.id);
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
    :title="material ? 'ویرایش کالا' : 'کالای جدید'"
    :subtitle="material?.name_fa"
    :saving="saving"
    :error="error"
    @close="emit('close')"
    @save="save"
  >
    <div>
      <label class="text-xs text-slate-500 mb-1 block">نام کالا *</label>
      <input v-model="form.name_fa" :class="inp" placeholder="مثلاً نوار شیرینگ" />
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label class="text-xs text-slate-500 mb-1 block">واحد</label>
        <PickerField v-model="form.unit" :options="unitOptions" :clearable="false" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">دسته</label>
        <PickerField
          v-model="form.category" :options="categoryOptions" placeholder="—"
        />
      </div>
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label class="text-xs text-slate-500 mb-1 block">حداقل موجودی</label>
        <input v-model="form.min_stock" :class="inp" inputmode="decimal" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">کد کالا</label>
        <input v-model="form.code" :class="inp" placeholder="خودکار ساخته می‌شود" />
      </div>
    </div>

    <div>
      <label class="text-xs text-slate-500 mb-1 block">توضیحات</label>
      <textarea v-model="form.note" :class="inp" rows="2" />
    </div>

    <label class="flex items-center gap-2 text-sm text-ink">
      <input v-model="form.is_active" type="checkbox" class="rounded" />
      فعال
    </label>
  </FormModal>
</template>
