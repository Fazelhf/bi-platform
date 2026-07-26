<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { crmApi, type CrmCustomer } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import FormModal from "./FormModal.vue";
import { apiError } from "./formError";

/** ثبت / ویرایش مشتری. */
const props = defineProps<{ customer?: CrmCustomer | null }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved", id: number): void }>();

const crm = useCrmStore();
const saving = ref(false);
const error = ref("");

const form = reactive({
  name_fa: "",
  kind: "company",
  status: "lead",
  group: "" as number | "",
  province: "" as number | "",
  city: "",
  lead_source: "" as number | "",
  owner: "" as number | "",
  contact_name: "",
  phone: "",
  mobile: "",
  email: "",
  national_id: "",
  address: "",
  note: "",
});

onMounted(async () => {
  await crm.loadOptions();
  if (props.customer) {
    Object.assign(form, {
      name_fa: props.customer.name_fa,
      kind: props.customer.kind,
      status: props.customer.status,
      group: (props.customer as any).group ?? "",
      province: (props.customer as any).province ?? "",
      city: props.customer.city ?? "",
      lead_source: (props.customer as any).lead_source ?? "",
      owner: props.customer.owner ?? "",
      contact_name: props.customer.contact_name ?? "",
      phone: props.customer.phone ?? "",
      mobile: props.customer.mobile ?? "",
      email: (props.customer as any).email ?? "",
      national_id: (props.customer as any).national_id ?? "",
      address: (props.customer as any).address ?? "",
      note: (props.customer as any).note ?? "",
    });
  } else if (crm.me?.employee) {
    // Pre-select the logged-in rep; a manager can still reassign.
    form.owner = crm.me.employee;
  }
});

const isEdit = computed(() => !!props.customer);

async function save() {
  if (!form.name_fa.trim()) {
    error.value = "نام مشتری الزامی است.";
    return;
  }
  // Same reason as on the deal form: "مشتریان جدید بر اساس کارشناس" cannot
  // count an account nobody owns.
  if (!form.owner) {
    error.value = "انتخاب کارشناس مسئول الزامی است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const payload: Record<string, any> = { ...form };
    for (const k of ["group", "province", "lead_source", "owner"]) {
      if (payload[k] === "") payload[k] = null;
    }
    const saved = await crmApi.saveCustomer(payload, props.customer?.id);
    emit("saved", saved.id ?? props.customer!.id);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  saving.value = true;
  try {
    await crmApi.deleteCustomer(props.customer!.id);
    emit("saved", 0);
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
    :title="isEdit ? 'ویرایش مشتری' : 'مشتری جدید'"
    :subtitle="isEdit ? customer!.name_fa : 'اطلاعات پایه مشتری را وارد کنید'"
    :saving="saving" :error="error" :can-delete="isEdit" wide
    @close="emit('close')" @save="save" @delete="remove"
  >
    <div class="grid sm:grid-cols-2 gap-3">
      <div class="sm:col-span-2">
        <label :class="lbl">نام مشتری *</label>
        <input v-model="form.name_fa" :class="inp" placeholder="مثلاً بازرگانی پارس گستر" />
      </div>

      <div>
        <label :class="lbl">نوع</label>
        <select v-model="form.kind" :class="inp">
          <option value="company">شرکت / سازمان</option>
          <option value="person">شخص حقیقی</option>
        </select>
      </div>
      <div>
        <label :class="lbl">وضعیت</label>
        <select v-model="form.status" :class="inp">
          <option value="lead">سرنخ</option>
          <option value="active">مشتری فعال</option>
          <option value="dormant">راکد</option>
          <option value="lost">از دست رفته</option>
        </select>
      </div>

      <div>
        <label :class="lbl">گروه مشتری</label>
        <select v-model="form.group" :class="inp">
          <option value="">— انتخاب کنید —</option>
          <option v-for="g in crm.options?.groups" :key="g.id" :value="g.id">{{ g.name_fa }}</option>
        </select>
      </div>
      <div>
        <label :class="lbl">منبع سرنخ</label>
        <select v-model="form.lead_source" :class="inp">
          <option value="">— انتخاب کنید —</option>
          <option v-for="s in crm.options?.sources" :key="s.id" :value="s.id">{{ s.name_fa }}</option>
        </select>
      </div>

      <div>
        <label :class="lbl">استان</label>
        <select v-model="form.province" :class="inp">
          <option value="">— انتخاب کنید —</option>
          <option v-for="p in crm.options?.provinces" :key="p.id" :value="p.id">{{ p.name_fa }}</option>
        </select>
      </div>
      <div>
        <label :class="lbl">شهر</label>
        <input v-model="form.city" :class="inp" />
      </div>

      <div>
        <label :class="lbl">کارشناس مسئول *</label>
        <select v-model="form.owner" :class="inp">
          <option value="">— انتخاب کنید —</option>
          <option v-for="e in crm.options?.employees" :key="e.id" :value="e.id">{{ e.name }}</option>
        </select>
      </div>
      <div>
        <label :class="lbl">نام رابط</label>
        <input v-model="form.contact_name" :class="inp" />
      </div>

      <div>
        <label :class="lbl">موبایل</label>
        <input v-model="form.mobile" :class="inp" dir="ltr" placeholder="09121234567" />
      </div>
      <div>
        <label :class="lbl">تلفن</label>
        <input v-model="form.phone" :class="inp" dir="ltr" />
      </div>

      <div>
        <label :class="lbl">ایمیل</label>
        <input v-model="form.email" :class="inp" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">شناسه ملی / کد اقتصادی</label>
        <input v-model="form.national_id" :class="inp" dir="ltr" />
      </div>

      <div class="sm:col-span-2">
        <label :class="lbl">آدرس</label>
        <input v-model="form.address" :class="inp" />
      </div>
      <div class="sm:col-span-2">
        <label :class="lbl">یادداشت</label>
        <textarea v-model="form.note" rows="2" :class="inp"></textarea>
      </div>
    </div>
  </FormModal>
</template>
