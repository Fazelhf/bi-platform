<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useCrmStore } from "@/stores/crm";
import PickerField from "@/components/PickerField.vue";

/**
 * «کارشناس» — the field whose right shape depends entirely on who is typing.
 *
 * A rep owns everything they enter; there has never been a case of one
 * choosing a different name from the list. Asking anyway costs a click and a
 * decision on every single record, and — because the field is required — it
 * is also the most common reason a half-filled form refuses to save. So for a
 * rep this is not a control at all: it is a line of text confirming what the
 * system already decided.
 *
 * For a manager the same field is the opposite: entering on someone's behalf
 * is the normal case, and getting it wrong quietly removes the record from
 * every per-rep report. So a manager gets an explicit, unfilled, required
 * picker that says out loud what it is for.
 *
 * The one case where a rep still sees a picker is an account with no linked
 * employee row — there is nothing to auto-fill, and hiding the field would
 * leave them unable to save at all.
 */
const props = defineProps<{
  modelValue: number | "";
  invalid?: boolean;
}>();
const emit = defineEmits<{ (e: "update:modelValue", v: number | ""): void }>();

const crm = useCrmStore();

const isManager = computed(() => !!crm.me?.is_manager);
const linked = computed(() => crm.me?.employee ?? null);
/** A rep with a linked employee row never has to answer this. */
const silent = computed(() => !isManager.value && linked.value !== null);

const options = computed(() =>
  (crm.options?.employees ?? []).map((e) => ({
    value: e.id,
    label: e.name,
    hint: e.team || undefined,
  })),
);

const name = computed(
  () => crm.options?.employees.find((e) => e.id === props.modelValue)?.name
    ?? crm.me?.employee_name
    ?? "—",
);

onMounted(() => {
  if (props.modelValue === "" && !isManager.value && linked.value !== null) {
    emit("update:modelValue", linked.value);
  }
});

const lbl = "block text-xs text-slate-500 mb-1";
</script>

<template>
  <!-- Rep: a statement, not a question. -->
  <p v-if="silent" class="text-xs text-slate-400">
    ثبت به نام <span class="text-slate-600">{{ name }}</span>
  </p>

  <!-- Manager, or an account with no employee row: an explicit choice. -->
  <div v-else>
    <label :class="lbl">
      {{ isManager ? "به نام کدام کارشناس ثبت شود؟ *" : "کارشناس مسئول *" }}
    </label>
    <PickerField
      :model-value="modelValue === '' ? null : modelValue"
      :options="options"
      placeholder="— انتخاب کنید —"
      :invalid="invalid"
      hint="بدون کارشناس، این رکورد در گزارش‌های کارشناسان دیده نمی‌شود."
      @update:model-value="emit('update:modelValue', (($event as number | null) ?? ''))"
    />
  </div>
</template>
