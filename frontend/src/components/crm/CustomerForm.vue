<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { crmApi, type CrmCustomer } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import PickerField from "@/components/PickerField.vue";
import FormModal from "./FormModal.vue";
import MoreFields from "./MoreFields.vue";
import OwnerField from "./OwnerField.vue";
import { apiError } from "./formError";

/**
 * ثبت / ویرایش مشتری.
 *
 * The form used to put fourteen boxes in front of a rep who wanted to record
 * one name and one mobile number, and then refused to save until «کارشناس
 * مسئول» — a list with exactly one plausible answer — had been chosen. Two
 * fields are genuinely needed to file a lead; everything else is filed
 * *about* a lead once it turns into something, and lives behind the fold.
 *
 * `quick` is the same form opened from inside another one (the customer
 * picker on an activity, say). There it shows only the two essential fields:
 * whoever is halfway through logging a call is not going to stop and fill in
 * an economic code, and offering the option is what makes them abandon the
 * activity instead.
 */
const props = withDefaults(defineProps<{
  customer?: CrmCustomer | null;
  /** Cut down to the essentials — used when nested inside another form. */
  quick?: boolean;
  /** Pre-fill the name, e.g. with whatever was typed into a search box. */
  initialName?: string;
  layer?: number;
}>(), { customer: null, quick: false, initialName: "", layer: 0 });

const emit = defineEmits<{
  (e: "close"): void;
  (e: "saved", id: number, name: string): void;
}>();

const crm = useCrmStore();
const saving = ref(false);
const error = ref("");
/** Which field the last failed save blamed, so it can be marked. */
const bad = ref("");

const form = reactive({
  name_fa: props.initialName,
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

const isEdit = computed(() => !!props.customer);

onMounted(async () => {
  await crm.loadOptions();
  if (props.customer) {
    const c = props.customer as any;
    Object.assign(form, {
      name_fa: c.name_fa,
      kind: c.kind,
      status: c.status,
      group: c.group ?? "",
      province: c.province ?? "",
      city: c.city ?? "",
      lead_source: c.lead_source ?? "",
      owner: c.owner ?? "",
      contact_name: c.contact_name ?? "",
      phone: c.phone ?? "",
      mobile: c.mobile ?? "",
      email: c.email ?? "",
      national_id: c.national_id ?? "",
      address: c.address ?? "",
      note: c.note ?? "",
    });
  }
  // The owner is filled in by OwnerField itself — for a rep it is never a
  // question, and for a manager it must stay empty so the choice is made.
});

const opt = (rows: { id: number; name_fa: string }[] | undefined) =>
  (rows ?? []).map((r) => ({ value: r.id, label: r.name_fa }));

const groups = computed(() => opt(crm.options?.groups));
const sources = computed(() => opt(crm.options?.sources));
const provinces = computed(() => opt(crm.options?.provinces));

/**
 * How many folded fields already hold something, so a collapsed section on an
 * existing customer does not look like the data went missing.
 */
const filledExtra = computed(() =>
  ([
    form.group, form.province, form.city, form.lead_source, form.contact_name,
    form.phone, form.email, form.national_id, form.address, form.note,
  ] as (string | number)[]).filter((v) => v !== "" && v !== null).length,
);

async function save() {
  bad.value = "";
  if (!form.name_fa.trim()) {
    error.value = "نام مشتری را بنویسید.";
    bad.value = "name_fa";
    return;
  }
  // Still required — "مشتریان جدید بر اساس کارشناس" cannot count an account
  // nobody owns — but a rep no longer has to answer it, so this message is
  // now only ever seen by a manager entering on someone's behalf.
  if (!form.owner) {
    error.value = "انتخاب کارشناس الزامی است.";
    bad.value = "owner";
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
    emit("saved", saved.id ?? props.customer!.id, form.name_fa.trim());
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
    emit("saved", 0, "");
  } catch (e) {
    error.value = apiError(e);
    saving.value = false;
  }
}

const inp = "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";
const badInp = inp + " ring-2 ring-red-300";
const lbl = "block text-xs text-slate-500 mb-1";
</script>

<template>
  <FormModal
    :title="isEdit ? 'ویرایش مشتری' : 'مشتری جدید'"
    :subtitle="isEdit ? customer!.name_fa : 'نام و شماره کافی است — بقیه بعداً'"
    :saving="saving" :error="error" :can-delete="isEdit && !quick"
    :wide="!quick" :layer="layer"
    @close="emit('close')" @save="save" @delete="remove"
  >
    <!-- ===== The two fields that actually file a lead ===== -->
    <div>
      <label :class="lbl">نام مشتری *</label>
      <input
        v-model="form.name_fa"
        :class="bad === 'name_fa' ? badInp : inp"
        placeholder="مثلاً بازرگانی پارس گستر"
        @keydown.enter="save"
      />
    </div>

    <div>
      <label :class="lbl">موبایل</label>
      <input
        v-model="form.mobile" :class="inp" dir="ltr" placeholder="09121234567"
        @keydown.enter="save"
      />
    </div>

    <OwnerField v-model="form.owner" :invalid="bad === 'owner'" />

    <!-- ===== Everything else ===== -->
    <MoreFields v-if="!quick" :filled="filledExtra" :start-open="isEdit">
      <div class="grid sm:grid-cols-2 gap-3">
        <div>
          <label :class="lbl">نوع</label>
          <PickerField
            v-model="form.kind"
            :clearable="false"
            :options="[
              { value: 'company', label: 'شرکت / سازمان' },
              { value: 'person', label: 'شخص حقیقی' },
            ]"
          />
        </div>
        <div>
          <label :class="lbl">وضعیت</label>
          <PickerField
            v-model="form.status"
            :clearable="false"
            :options="[
              { value: 'lead', label: 'سرنخ' },
              { value: 'active', label: 'مشتری فعال' },
              { value: 'dormant', label: 'راکد' },
              { value: 'lost', label: 'از دست رفته' },
            ]"
          />
        </div>

        <div>
          <label :class="lbl">گروه مشتری</label>
          <PickerField v-model="form.group" :options="groups" placeholder="— انتخاب کنید —" />
        </div>
        <div>
          <label :class="lbl">منبع سرنخ</label>
          <PickerField v-model="form.lead_source" :options="sources" placeholder="— انتخاب کنید —" />
        </div>

        <div>
          <label :class="lbl">استان</label>
          <PickerField v-model="form.province" :options="provinces" placeholder="— انتخاب کنید —" />
        </div>
        <div>
          <label :class="lbl">شهر</label>
          <input v-model="form.city" :class="inp" />
        </div>

        <div>
          <label :class="lbl">نام رابط</label>
          <input v-model="form.contact_name" :class="inp" />
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
    </MoreFields>
  </FormModal>
</template>
