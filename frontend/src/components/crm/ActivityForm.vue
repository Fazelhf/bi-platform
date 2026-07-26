<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { crmApi, type CrmActivity } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import FormModal from "./FormModal.vue";
import { apiError } from "./formError";

/**
 * ثبت فعالیت (تماس، جلسه، اعلام قیمت…).
 *
 * This is the form reps touch most, so it defaults everything it can: the
 * activity is theirs, it happened now, and it succeeded. A call log that
 * takes four dropdowns to save does not get saved.
 */
const props = defineProps<{
  activity?: CrmActivity | null;
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

/** `datetime-local` wants "YYYY-MM-DDTHH:mm" in local time. */
function localNow(d = new Date()): string {
  const p = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

const form = reactive({
  kind: "call_out",
  customer: (props.customerId ?? "") as number | "",
  customer_label: props.customerLabel ?? "",
  deal: (props.dealId ?? "") as number | "",
  owner: "" as number | "",
  at: localNow(),
  duration_min: "5",
  result: "success",
  note: "",
});

const isEdit = computed(() => !!props.activity);

onMounted(async () => {
  await crm.loadOptions();
  if (props.activity) {
    const a = props.activity;
    Object.assign(form, {
      kind: a.kind,
      customer: a.customer,
      customer_label: a.customer_name,
      deal: a.deal ?? "",
      owner: (a as any).owner ?? "",
      at: localNow(new Date(a.at)),
      duration_min: String(a.duration_min),
      result: a.result,
      note: a.note ?? "",
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
  if (!form.customer) {
    error.value = "انتخاب مشتری الزامی است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await crmApi.saveActivity({
      kind: form.kind,
      customer: form.customer,
      deal: form.deal || null,
      owner: form.owner || null,
      at: new Date(form.at).toISOString(),
      duration_min: Number(form.duration_min) || 0,
      result: form.result,
      note: form.note,
    }, props.activity?.id);
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
    await crmApi.deleteActivity(props.activity!.id);
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
    :title="isEdit ? 'ویرایش فعالیت' : 'ثبت فعالیت'"
    :subtitle="form.customer_label"
    :saving="saving" :error="error" :can-delete="isEdit"
    save-label="ثبت"
    @close="emit('close')" @save="save" @delete="remove"
  >
    <div v-if="!customerId" class="relative">
      <label :class="lbl">مشتری *</label>
      <div v-if="form.customer" class="flex items-center gap-2">
        <span class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink flex-1">{{ form.customer_label }}</span>
        <button class="text-xs text-slate-400 hover:text-ink px-2" @click="form.customer = ''; form.customer_label = ''">تغییر</button>
      </div>
      <template v-else>
        <input v-model="customerSearch" :class="inp" placeholder="نام مشتری را جستجو کنید…" />
        <ul v-if="customerResults.length" class="absolute z-10 mt-1 w-full bg-surface rounded-xl shadow-pop border border-slate-100 max-h-52 overflow-y-auto">
          <li v-for="c in customerResults" :key="c.id" class="px-3 py-2 text-sm hover:bg-slate-100 cursor-pointer" @click="pickCustomer(c)">
            {{ c.name_fa }}
          </li>
        </ul>
      </template>
    </div>

    <div class="grid sm:grid-cols-2 gap-3">
      <div>
        <label :class="lbl">نوع فعالیت</label>
        <select v-model="form.kind" :class="inp">
          <option v-for="k in crm.options?.activity_kinds" :key="k.code" :value="k.code">{{ k.label }}</option>
        </select>
      </div>
      <div>
        <label :class="lbl">نتیجه</label>
        <select v-model="form.result" :class="inp">
          <option v-for="r in crm.options?.activity_results" :key="r.code" :value="r.code">{{ r.label }}</option>
        </select>
      </div>

      <div>
        <label :class="lbl">زمان</label>
        <input v-model="form.at" type="datetime-local" :class="inp" />
      </div>
      <div>
        <label :class="lbl">مدت (دقیقه)</label>
        <input v-model="form.duration_min" :class="inp" dir="ltr" />
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
        <textarea v-model="form.note" rows="2" :class="inp" placeholder="خلاصه گفتگو یا نتیجه پیگیری"></textarea>
      </div>
    </div>
  </FormModal>
</template>
