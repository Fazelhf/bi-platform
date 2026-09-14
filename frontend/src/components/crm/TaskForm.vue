<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { crmApi } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import JalaliDateField from "@/components/JalaliDateField.vue";
import FormModal from "./FormModal.vue";
import MoreFields from "./MoreFields.vue";
import OwnerField from "./OwnerField.vue";
import CustomerPicker from "./CustomerPicker.vue";
import CustomerForm from "./CustomerForm.vue";
import { apiError } from "./formError";

/**
 * ثبت کار / یادآوری آینده.
 *
 * The only question that is hard to answer here is "when", and a
 * `datetime-local` box is a poor way to ask it: nobody schedules a callback
 * for 14:37 next Thursday, they mean فردا or هفته بعد. So the common answers
 * are one tap and the exact box stays for the rest.
 */
const props = defineProps<{
  task?: any | null;
  customerId?: number | null;
  customerLabel?: string;
  dealId?: number | null;
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const crm = useCrmStore();
const saving = ref(false);
const error = ref("");
const bad = ref("");
const picker = ref<InstanceType<typeof CustomerPicker> | null>(null);
const newCustomerName = ref<string | null>(null);

function localDt(d: Date): string {
  const p = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
/** N days out at 10:00 — the usual "call them back" slot. */
function daysOut(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  d.setHours(10, 0, 0, 0);
  return localDt(d);
}

const form = reactive({
  title: "",
  customer: (props.customerId ?? "") as number | "",
  customer_label: props.customerLabel ?? "",
  deal: (props.dealId ?? "") as number | "",
  owner: "" as number | "",
  kind: "call_out",
  due_at: daysOut(1),
  note: "",
});

const preset = ref<number | "custom">(1);
watch(preset, (p) => {
  if (p !== "custom") form.due_at = daysOut(p as number);
});

const isEdit = computed(() => !!props.task);
const kinds = computed(() => crm.options?.activity_kinds ?? []);

onMounted(async () => {
  await crm.loadOptions();
  if (props.task) {
    Object.assign(form, {
      title: props.task.title,
      customer: props.task.customer ?? "",
      customer_label: props.task.customer_name ?? "",
      deal: props.task.deal ?? "",
      owner: props.task.owner ?? "",
      kind: props.task.kind,
      due_at: localDt(new Date(props.task.due_at)),
      note: props.task.note ?? "",
    });
    preset.value = "custom";   // an existing date is never one of the presets
  }
});

function onCustomerCreated(id: number, name: string) {
  newCustomerName.value = null;
  if (id) picker.value?.select(id, name);
}

async function save() {
  bad.value = "";
  if (!form.title.trim()) {
    error.value = "عنوان کار را بنویسید.";
    bad.value = "title";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await crmApi.saveTask({
      title: form.title,
      customer: form.customer || null,
      deal: form.deal || null,
      owner: form.owner || null,
      kind: form.kind,
      due_at: new Date(form.due_at).toISOString(),
      note: form.note,
    }, props.task?.id);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  saving.value = true;
  try {
    await crmApi.deleteTask(props.task.id);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
    saving.value = false;
  }
}

const inp = "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";
const badInp = inp + " ring-2 ring-red-300";
const lbl = "block text-xs text-slate-500 mb-1";
const chip = "px-3 py-1.5 rounded-xl text-sm transition-colors border";
const chipOn = "bg-panel text-white border-transparent";
const chipOff = "bg-slate-100 text-slate-600 border-transparent hover:bg-slate-200";
</script>

<template>
  <FormModal
    :title="isEdit ? 'ویرایش کار' : 'کار جدید'"
    :subtitle="form.customer_label"
    :saving="saving" :error="error" :can-delete="isEdit"
    @close="emit('close')" @save="save" @delete="remove"
  >
    <div>
      <label :class="lbl">چه کاری؟ *</label>
      <input
        v-model="form.title"
        :class="bad === 'title' ? badInp : inp"
        placeholder="مثلاً پیگیری پیش‌فاکتور"
        @keydown.enter="save"
      />
    </div>

    <div>
      <label :class="lbl">کِی؟</label>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="p in ([
            { v: 0, label: 'امروز' },
            { v: 1, label: 'فردا' },
            { v: 3, label: '۳ روز دیگر' },
            { v: 7, label: 'هفته بعد' },
            { v: 'custom', label: 'تاریخ دلخواه' },
          ] as const)"
          :key="String(p.v)"
          type="button" :class="[chip, preset === p.v ? chipOn : chipOff]"
          @click="preset = p.v"
        >{{ p.label }}</button>
      </div>
      <div v-if="preset === 'custom'" class="mt-2">
        <JalaliDateField v-model="form.due_at" with-time :clearable="false" />
      </div>
    </div>

    <div v-if="!customerId">
      <label :class="lbl">مشتری <span class="text-slate-300">(اختیاری)</span></label>
      <CustomerPicker
        ref="picker"
        v-model="form.customer"
        v-model:label="form.customer_label"
        placeholder="جستجوی مشتری…"
        @create="newCustomerName = $event"
      />
    </div>

    <OwnerField v-model="form.owner" />

    <MoreFields :filled="(form.note ? 1 : 0) + (form.kind !== 'call_out' ? 1 : 0)">
      <div>
        <label :class="lbl">نوع</label>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="k in kinds" :key="k.code"
            type="button" :class="[chip, form.kind === k.code ? chipOn : chipOff]"
            @click="form.kind = k.code"
          >{{ k.label }}</button>
        </div>
      </div>
      <div>
        <label :class="lbl">توضیح</label>
        <textarea v-model="form.note" rows="2" :class="inp"></textarea>
      </div>
    </MoreFields>

    <CustomerForm
      v-if="newCustomerName !== null"
      quick
      :layer="1"
      :initial-name="newCustomerName"
      @close="newCustomerName = null"
      @saved="onCustomerCreated"
    />
  </FormModal>
</template>
