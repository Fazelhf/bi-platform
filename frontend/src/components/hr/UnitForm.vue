<script setup lang="ts">
import { computed, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import { hrApi, SALES_CHANNELS, UNIT_KINDS, type OrgUnit } from "@/api/hr";

/** افزودن / ویرایش واحد سازمانی. */
const props = defineProps<{
  unit?: OrgUnit | null;
  /** For a new unit: where it goes. */
  parentId?: number | null;
  /** Every unit, flat — for the «زیرمجموعه» picker. */
  units: OrgUnit[];
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";
const lbl = "text-xs text-slate-500 mb-1 block";

const saving = ref(false);
const error = ref("");

const form = ref({
  name_fa: props.unit?.name_fa ?? "",
  kind: props.unit?.kind ?? (props.parentId ? "section" : "department"),
  parent: props.unit ? props.unit.parent : props.parentId ?? null,
  color: props.unit?.color || "#64748b",
  sales_channel: props.unit?.sales_channel ?? "",
  sort_order: props.unit?.sort_order ?? 0,
  is_active: props.unit?.is_active ?? true,
});

/** Itself and anything under it cannot be its parent. */
const descendants = computed(() => {
  const out = new Set<number>();
  if (!props.unit) return out;
  const walk = (id: number) => {
    out.add(id);
    props.units.filter((u) => u.parent === id).forEach((u) => walk(u.id));
  };
  walk(props.unit.id);
  return out;
});

const parentOptions = computed(() => props.units
  .filter((u) => !descendants.value.has(u.id))
  .map((u) => ({
    value: u.id,
    label: u.name_fa,
    hint: props.units.find((p) => p.id === u.parent)?.name_fa ?? "",
  })));

const channelOptions = [{ value: "", label: "— هیچ‌کدام", hint: "افراد این واحد در برگه فروش نیستند" }, ...SALES_CHANNELS];

async function save() {
  if (!form.value.name_fa.trim()) {
    error.value = "نام واحد الزامی است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await hrApi.saveUnit(form.value as Partial<OrgUnit>, props.unit?.id);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!props.unit) return;
  saving.value = true;
  try {
    await hrApi.removeUnit(props.unit.id);
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
    :title="unit ? 'ویرایش واحد' : 'واحد جدید'"
    :subtitle="unit?.name_fa"
    :saving="saving"
    :error="error"
    :can-delete="!!unit"
    @close="emit('close')"
    @save="save"
    @delete="remove"
  >
    <div>
      <label :class="lbl">نام واحد *</label>
      <input v-model="form.name_fa" :class="inp" placeholder="مثلاً فروش همکار" />
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label :class="lbl">نوع</label>
        <PickerField v-model="form.kind" :options="UNIT_KINDS" :clearable="false" />
      </div>
      <div>
        <label :class="lbl">زیرمجموعه‌ی</label>
        <PickerField v-model="form.parent" :options="parentOptions" placeholder="— بالاترین سطح" />
      </div>
    </div>

    <div>
      <label :class="lbl">برگه فروش</label>
      <PickerField v-model="form.sales_channel" :options="channelOptions" :clearable="false" />
      <p class="text-xs text-slate-400 mt-1">
        اگر این واحد یکی از بخش‌های فروش است، افرادی که در آن سمت دارند خودکار در برگه ورود
        اطلاعات همان بخش قرار می‌گیرند. زیرواحدها این انتخاب را به ارث می‌برند.
      </p>
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label :class="lbl">رنگ</label>
        <input v-model="form.color" type="color" class="w-full h-10 rounded-xl bg-slate-100 px-1" />
      </div>
      <div>
        <label :class="lbl">ترتیب نمایش</label>
        <input v-model.number="form.sort_order" :class="inp" inputmode="numeric" />
      </div>
    </div>

    <label class="flex items-center gap-2 text-sm text-ink">
      <input v-model="form.is_active" type="checkbox" class="rounded" />
      فعال
    </label>
    <p class="text-xs text-slate-400">
      واحدی که زیرواحد یا فرد دارد حذف نمی‌شود؛ می‌توانید غیرفعالش کنید.
    </p>
  </FormModal>
</template>
