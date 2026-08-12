<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import { commercialApi, type Material, type PurchaseRequest } from "@/api/commercial";

/** ثبت نیاز کارخانه — یک کالا، یک مقدار. */
const props = defineProps<{ request?: PurchaseRequest | null }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved", r: PurchaseRequest): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";

const materials = ref<Material[]>([]);
const units = ref<string[]>([]);
const saving = ref(false);
const error = ref("");

const today = new Date().toISOString().slice(0, 10);

const form = ref({
  material: props.request?.material ?? null as number | null,
  quantity: props.request?.quantity ?? "",
  requester_unit: props.request?.requester_unit ?? "",
  requested_on: props.request?.requested_on ?? today,
  needed_by: props.request?.needed_by ?? "",
  note: props.request?.note ?? "",
});

const unitLabel = computed(
  () => materials.value.find((m) => m.id === form.value.material)?.unit_label ?? "",
);

/** The category is the hint: two «چسب» rows are told apart by it, not by name. */
const materialOptions = computed(() => materials.value.map((m) => ({
  value: m.id,
  label: m.name_fa,
  hint: m.category_name || "",
  badge: m.unit_label,
  keywords: m.code,
})));

const unitOptions = computed(() => units.value.map((u) => ({ value: u, label: u })));

onMounted(async () => {
  materials.value = await commercialApi.materials({ is_active: true });
  // Suggestions are a convenience, never a gate: if the endpoint is slow or
  // fails, the field stays a plain text input and the form still saves.
  try {
    units.value = (await commercialApi.suggestions()).requester_units;
  } catch { /* leave the list empty */ }
});

async function save() {
  if (!form.value.material) {
    error.value = "کالا را انتخاب کنید.";
    return;
  }
  if (!Number(form.value.quantity)) {
    error.value = "مقدار درخواستی را وارد کنید.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const payload: Record<string, unknown> = { ...form.value };
    // An empty date must be null, not "": DRF rejects the empty string on an
    // optional date and the user sees a validation error for a field they
    // deliberately left blank.
    if (!payload.needed_by) payload.needed_by = null;
    const saved = await commercialApi.saveRequest(payload, props.request?.id);
    emit("saved", saved);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <FormModal
    :title="request ? 'ویرایش درخواست خرید' : 'درخواست خرید جدید'"
    :subtitle="request?.request_no"
    :saving="saving"
    :error="error"
    @close="emit('close')"
    @save="save"
  >
    <div>
      <label class="text-xs text-slate-500 mb-1 block">کالا *</label>
      <PickerField
        v-model="form.material"
        :options="materialOptions"
        placeholder="کالا را انتخاب کنید…"
        search-placeholder="نام یا کد کالا…"
        empty-text="کالایی با این نام نیست"
      />
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label class="text-xs text-slate-500 mb-1 block">
          مقدار * <span v-if="unitLabel" class="text-slate-400">({{ unitLabel }})</span>
        </label>
        <input v-model="form.quantity" :class="inp" inputmode="decimal" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">واحد درخواست‌کننده</label>
        <PickerField
          v-model="form.requester_unit"
          :options="unitOptions"
          creatable
          placeholder="مثلاً خط بسته‌بندی"
        />
      </div>
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label class="text-xs text-slate-500 mb-1 block">تاریخ درخواست</label>
        <input v-model="form.requested_on" :class="inp" type="date" dir="ltr" />
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">موعد نیاز</label>
        <input v-model="form.needed_by" :class="inp" type="date" dir="ltr" />
      </div>
    </div>

    <div>
      <label class="text-xs text-slate-500 mb-1 block">توضیحات</label>
      <textarea v-model="form.note" :class="inp" rows="2" />
    </div>
  </FormModal>
</template>
