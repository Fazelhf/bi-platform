<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { crmApi } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import FormModal from "./FormModal.vue";
import { apiError } from "./formError";

/** ثبت کار / یادآوری آینده. */
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
const customerSearch = ref("");
const customerResults = ref<any[]>([]);

function localDt(d: Date): string {
  const p = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
/** Default: tomorrow at 10:00 — the usual "call them back" slot. */
function tomorrow(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
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
  due_at: tomorrow(),
  note: "",
});

const isEdit = computed(() => !!props.task);

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
  } else if (crm.me?.employee) {
    form.owner = crm.me.employee;
  }
});

let t: number | undefined;
watch(customerSearch, (q) => {
  window.clearTimeout(t);
  if (!q.trim()) {
    customerResults.value = [];
    return;
  }
  t = window.setTimeout(async () => {
    customerResults.value = (await crmApi.customers({ search: q, page_size: 8 })).results as any;
  }, 300);
});

function pickCustomer(c: any) {
  form.customer = c.id;
  form.customer_label = c.name_fa;
  customerSearch.value = "";
  customerResults.value = [];
}

async function save() {
  if (!form.title.trim()) {
    error.value = "عنوان کار الزامی است.";
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
const lbl = "block text-xs text-slate-500 mb-1";
</script>

<template>
  <FormModal
    :title="isEdit ? 'ویرایش کار' : 'کار جدید'"
    :subtitle="form.customer_label"
    :saving="saving" :error="error" :can-delete="isEdit"
    @close="emit('close')" @save="save" @delete="remove"
  >
    <div>
      <label :class="lbl">عنوان *</label>
      <input v-model="form.title" :class="inp" placeholder="مثلاً پیگیری پیش‌فاکتور" />
    </div>

    <div v-if="!customerId" class="relative">
      <label :class="lbl">مشتری</label>
      <div v-if="form.customer" class="flex items-center gap-2">
        <span class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink flex-1">{{ form.customer_label }}</span>
        <button class="text-xs text-slate-400 hover:text-ink px-2" @click="form.customer = ''; form.customer_label = ''">تغییر</button>
      </div>
      <template v-else>
        <input v-model="customerSearch" :class="inp" placeholder="جستجوی مشتری (اختیاری)…" />
        <ul v-if="customerResults.length" class="absolute z-10 mt-1 w-full bg-surface rounded-xl shadow-pop border border-slate-100 max-h-52 overflow-y-auto">
          <li v-for="c in customerResults" :key="c.id" class="px-3 py-2 text-sm hover:bg-slate-100 cursor-pointer" @click="pickCustomer(c)">
            {{ c.name_fa }}
          </li>
        </ul>
      </template>
    </div>

    <div class="grid sm:grid-cols-2 gap-3">
      <div>
        <label :class="lbl">نوع</label>
        <select v-model="form.kind" :class="inp">
          <option v-for="k in crm.options?.activity_kinds" :key="k.code" :value="k.code">{{ k.label }}</option>
        </select>
      </div>
      <div>
        <label :class="lbl">موعد</label>
        <input v-model="form.due_at" type="datetime-local" :class="inp" />
      </div>
      <div class="sm:col-span-2">
        <label :class="lbl">کارشناس</label>
        <select v-model="form.owner" :class="inp">
          <option value="">— انتخاب کنید —</option>
          <option v-for="e in crm.options?.employees" :key="e.id" :value="e.id">{{ e.name }}</option>
        </select>
      </div>
      <div class="sm:col-span-2">
        <label :class="lbl">توضیح</label>
        <textarea v-model="form.note" rows="2" :class="inp"></textarea>
      </div>
    </div>
  </FormModal>
</template>
