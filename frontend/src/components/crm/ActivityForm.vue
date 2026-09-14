<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { crmApi, type CrmActivity } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import JalaliDateField from "@/components/JalaliDateField.vue";
import FormModal from "./FormModal.vue";
import MoreFields from "./MoreFields.vue";
import OwnerField from "./OwnerField.vue";
import CustomerPicker from "./CustomerPicker.vue";
import CustomerForm from "./CustomerForm.vue";
import { apiError } from "./formError";

/**
 * ثبت فعالیت — the form a rep touches more than any other, and the one whose
 * cost per use matters most.
 *
 * Three changes to how it used to work, all aimed at the same thing:
 *
 * * **Kind and result are chips, not dropdowns.** Both lists are short and
 *   fixed, and both were dropdowns costing two clicks each on every single
 *   call logged. Laid out flat they cost one, and the reader can see what the
 *   options *are* without opening anything.
 * * **The next follow-up is part of this form.** «زنگ زدم، جواب نداد، هفته
 *   بعد دوباره» is one thought and used to be two forms — and the second one
 *   was the one that got skipped, which is exactly how a pipeline goes quiet.
 *   Choosing «بی‌پاسخ» or «نیاز به پیگیری» now ticks the follow-up by itself,
 *   because those two answers *mean* «باید دوباره تماس بگیرم».
 * * **A new lead can be created from the customer box.** Logging the first
 *   call to someone not yet in the system used to mean throwing this form
 *   away and starting elsewhere.
 *
 * Everything else — when exactly, for how long, against which deal — is
 * folded away with sane defaults: it is now, it was short, and it is not
 * attached to a deal.
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
const bad = ref("");
/** The activity landed but its follow-up did not — there is nothing left to
 *  retry here, so the footer turns into a way out instead of a second save. */
const savedWithWarning = ref(false);
const picker = ref<InstanceType<typeof CustomerPicker> | null>(null);
const newCustomerName = ref<string | null>(null);

/** `datetime-local` wants "YYYY-MM-DDTHH:mm" in local time. */
function localDt(d = new Date()): string {
  const p = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
/** N days out, at 10:00 — the slot everyone means by «فردا زنگ می‌زنم». */
function daysOut(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  d.setHours(10, 0, 0, 0);
  return localDt(d);
}

const form = reactive({
  kind: "call_out",
  customer: (props.customerId ?? "") as number | "",
  customer_label: props.customerLabel ?? "",
  deal: (props.dealId ?? "") as number | "",
  owner: "" as number | "",
  at: localDt(),
  duration_min: "5",
  result: "success",
  note: "",
});

/** The chained follow-up. Not part of the activity payload — it becomes a کار. */
const next = reactive({
  on: false,
  /** 1 / 3 / 7 days out, or "custom" for the date box. */
  preset: 1 as number | "custom",
  due_at: daysOut(1),
  title: "",
});

const isEdit = computed(() => !!props.activity);
const kinds = computed(() => crm.options?.activity_kinds ?? []);
const results = computed(() => crm.options?.activity_results ?? []);

/** These two answers are a request to be called back; say so by default. */
const NEEDS_FOLLOW_UP = new Set(["no_answer", "follow_up"]);
watch(() => form.result, (r) => {
  if (isEdit.value) return;      // editing history should not schedule work
  if (NEEDS_FOLLOW_UP.has(r)) next.on = true;
});

watch(() => next.preset, (p) => {
  if (p !== "custom") next.due_at = daysOut(p as number);
});

onMounted(async () => {
  await crm.loadOptions();
  if (props.activity) {
    const a = props.activity as any;
    Object.assign(form, {
      kind: a.kind,
      customer: a.customer,
      customer_label: a.customer_name,
      deal: a.deal ?? "",
      owner: a.owner ?? "",
      at: localDt(new Date(a.at)),
      duration_min: String(a.duration_min),
      result: a.result,
      note: a.note ?? "",
    });
  }
});

function onCreateCustomer(name: string) {
  newCustomerName.value = name;
}

function onCustomerCreated(id: number, name: string) {
  newCustomerName.value = null;
  if (id) picker.value?.select(id, name);
}

/**
 * How many folded fields differ from their defaults. The default timestamp is
 * captured once rather than recomputed — comparing against `localDt()` marked
 * the field "changed" the moment the clock ticked past the minute the form
 * opened in.
 */
const defaultAt = form.at;
const filledExtra = computed(() => {
  let n = 0;
  if (form.duration_min !== "5") n++;
  if (form.at !== defaultAt) n++;
  return n;
});

async function save() {
  if (savedWithWarning.value) { emit("saved"); return; }
  bad.value = "";
  if (!form.customer) {
    error.value = "مشتری را انتخاب کنید.";
    bad.value = "customer";
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

    // The follow-up is deliberately a second request rather than something
    // the activity endpoint grows: a کار is a real, separately editable
    // record, not a field on the call that produced it.
    if (next.on && !isEdit.value) {
      try {
        await crmApi.saveTask({
          title: next.title.trim() || `پیگیری ${form.customer_label}`,
          customer: form.customer,
          deal: form.deal || null,
          owner: form.owner || null,
          kind: "call_out",
          due_at: new Date(next.due_at).toISOString(),
          note: "",
        });
      } catch (e) {
        savedWithWarning.value = true;
        error.value = `فعالیت ثبت شد، اما پیگیری بعدی ثبت نشد:\n${apiError(e)}`;
        return;
      }
    }
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
const chip =
  "px-3 py-1.5 rounded-xl text-sm transition-colors border";
const chipOn = "bg-panel text-white border-transparent";
const chipOff = "bg-slate-100 text-slate-600 border-transparent hover:bg-slate-200";
</script>

<template>
  <FormModal
    :title="isEdit ? 'ویرایش فعالیت' : 'ثبت فعالیت'"
    :subtitle="form.customer_label"
    :saving="saving" :error="error" :can-delete="isEdit"
    :save-label="savedWithWarning ? 'بستن' : 'ثبت'"
    @close="emit('close')" @save="save" @delete="remove"
  >
    <div v-if="!customerId">
      <label :class="lbl">مشتری *</label>
      <CustomerPicker
        ref="picker"
        v-model="form.customer"
        v-model:label="form.customer_label"
        :invalid="bad === 'customer'"
        @create="onCreateCustomer"
      />
    </div>

    <!-- What happened: one tap, and the whole list is visible. -->
    <div>
      <label :class="lbl">چه اتفاقی افتاد؟</label>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="k in kinds" :key="k.code"
          type="button" :class="[chip, form.kind === k.code ? chipOn : chipOff]"
          @click="form.kind = k.code"
        >{{ k.label }}</button>
      </div>
    </div>

    <div>
      <label :class="lbl">نتیجه</label>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="r in results" :key="r.code"
          type="button" :class="[chip, form.result === r.code ? chipOn : chipOff]"
          @click="form.result = r.code"
        >{{ r.label }}</button>
      </div>
    </div>

    <div>
      <label :class="lbl">توضیح</label>
      <textarea
        v-model="form.note" rows="2" :class="inp"
        placeholder="خلاصه گفتگو یا نتیجه پیگیری"
      ></textarea>
    </div>

    <!-- ===== The next step, before the thought is lost ===== -->
    <div v-if="!isEdit" class="bg-slate-50 rounded-xl p-3">
      <label class="flex items-center gap-2 text-sm text-ink cursor-pointer">
        <input v-model="next.on" type="checkbox" class="accent-slate-700 w-4 h-4" />
        <span>پیگیری بعدی را همین حالا ثبت کن</span>
      </label>

      <div v-if="next.on" class="mt-3 space-y-2">
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="p in ([
              { v: 1, label: 'فردا' },
              { v: 3, label: '۳ روز دیگر' },
              { v: 7, label: 'هفته بعد' },
              { v: 'custom', label: 'تاریخ دلخواه' },
            ] as const)"
            :key="String(p.v)"
            type="button"
            :class="[chip, next.preset === p.v ? chipOn : chipOff]"
            @click="next.preset = p.v"
          >{{ p.label }}</button>
        </div>

        <JalaliDateField
          v-if="next.preset === 'custom'"
          v-model="next.due_at" with-time :clearable="false"
        />
        <input
          v-model="next.title" :class="inp"
          :placeholder="`پیگیری ${form.customer_label || 'مشتری'}`"
        />
      </div>
    </div>

    <OwnerField v-model="form.owner" />

    <!-- ===== Defaults worth keeping out of the way ===== -->
    <MoreFields :filled="filledExtra" label="زمان و جزئیات">
      <div class="grid sm:grid-cols-2 gap-3">
        <div>
          <label :class="lbl">زمان</label>
          <JalaliDateField v-model="form.at" with-time :clearable="false" />
        </div>
        <div>
          <label :class="lbl">مدت (دقیقه)</label>
          <input v-model="form.duration_min" :class="inp" dir="ltr" />
        </div>
      </div>
    </MoreFields>

    <!-- A lead that does not exist yet should not cost this form its contents. -->
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
