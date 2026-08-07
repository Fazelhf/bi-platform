<script setup lang="ts">
import { onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import { apiError } from "@/components/crm/formError";
import { commercialApi, type Supplier } from "@/api/commercial";
import {
  foreignApi,
  type Bank,
  type ForeignOrder,
  type ForeignOptions,
} from "@/api/commercialForeign";

/**
 * پرونده واردات — the proforma, its ثبت سفارش, and the dates that decide
 * whether it lives or quietly expires.
 *
 * The dates are grouped by the gate they belong to rather than listed flat,
 * because that is the order they get filled in: nothing about تخصیص is known
 * on the day the file is opened.
 */
const props = defineProps<{ order?: ForeignOrder | null }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved", o: ForeignOrder): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
const lbl = "text-xs text-slate-500 mb-1 block";

const banks = ref<Bank[]>([]);
const suppliers = ref<Supplier[]>([]);
const options = ref<ForeignOptions | null>(null);
const saving = ref(false);
const error = ref("");

const form = ref({
  pi_no: props.order?.pi_no ?? "",
  registration_no: props.order?.registration_no ?? "",
  statistical_no: props.order?.statistical_no ?? "",
  supplier: props.order?.supplier ?? (null as number | null),
  country: props.order?.country ?? "",
  brand: props.order?.brand ?? "",
  goods_desc: props.order?.goods_desc ?? "",
  weight_ton: props.order?.weight_ton ?? "",
  currency: props.order?.currency ?? "USD",
  amount: props.order?.amount ?? "",
  bank: props.order?.bank ?? (null as number | null),
  registered_on: props.order?.registered_on ?? new Date().toISOString().slice(0, 10),
  valid_until: props.order?.valid_until ?? "",
  queued_on: props.order?.queued_on ?? "",
  allocated_on: props.order?.allocated_on ?? "",
  purchase_deadline: props.order?.purchase_deadline ?? "",
  expected_queue_days: props.order?.expected_queue_days ?? 60,
  status: props.order?.status ?? "draft",
  note: props.order?.note ?? "",
});

onMounted(async () => {
  [banks.value, suppliers.value, options.value] = await Promise.all([
    foreignApi.banks(),
    commercialApi.suppliers({ is_active: true }),
    foreignApi.options(),
  ]);
});

async function save() {
  if (!form.value.pi_no.trim()) {
    error.value = "شماره پروفرما الزامی است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    // Empty date inputs come through as "", which the API reads as an invalid
    // date rather than as "not set yet".
    const payload: Record<string, unknown> = { ...form.value };
    for (const key of [
      "valid_until", "queued_on", "allocated_on", "purchase_deadline", "registered_on",
    ]) {
      if (!payload[key]) payload[key] = null;
    }
    const saved = await foreignApi.saveOrder(payload, props.order?.id);
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
    :title="order ? `پرونده ${order.file_no}` : 'پرونده واردات جدید'"
    :subtitle="order?.pi_no"
    :saving="saving"
    :error="error"
    wide
    @close="emit('close')"
    @save="save"
  >
    <!-- شناسه پرونده -->
    <div class="grid sm:grid-cols-3 gap-3">
      <div>
        <label :class="lbl">شماره پروفرما (PI) *</label>
        <input v-model="form.pi_no" :class="inp" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">شماره ثبت سفارش</label>
        <input v-model="form.registration_no" :class="inp" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">شماره ثبت آماری</label>
        <input v-model="form.statistical_no" :class="inp" dir="ltr" />
      </div>
    </div>

    <!-- کالا و فروشنده -->
    <div class="grid sm:grid-cols-2 gap-3">
      <div>
        <label :class="lbl">فروشنده خارجی</label>
        <select v-model="form.supplier" :class="inp">
          <option :value="null">انتخاب کنید…</option>
          <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.name_fa }}</option>
        </select>
      </div>
      <div>
        <label :class="lbl">کشور</label>
        <input v-model="form.country" :class="inp" placeholder="مثلاً چین" />
      </div>
      <div>
        <label :class="lbl">برند</label>
        <input v-model="form.brand" :class="inp" placeholder="مثلاً Oriental" />
      </div>
      <div>
        <label :class="lbl">وزن (تن)</label>
        <input v-model="form.weight_ton" :class="inp" inputmode="decimal" dir="ltr" />
      </div>
      <div class="sm:col-span-2">
        <label :class="lbl">شرح کالا</label>
        <input
          v-model="form.goods_desc" :class="inp"
          placeholder="مثلاً کاغذ حرارتی ۵۵ گرم"
        />
      </div>
    </div>

    <!-- ارز و بانک -->
    <div class="grid sm:grid-cols-3 gap-3">
      <div>
        <label :class="lbl">ارز</label>
        <select v-model="form.currency" :class="inp">
          <option v-for="c in options?.currencies ?? []" :key="c.value" :value="c.value">
            {{ c.label }}
          </option>
        </select>
      </div>
      <div>
        <label :class="lbl">ارزش ارزی</label>
        <input v-model="form.amount" :class="inp" inputmode="decimal" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">بانک عامل</label>
        <select v-model="form.bank" :class="inp">
          <option :value="null">انتخاب کنید…</option>
          <option v-for="b in banks" :key="b.id" :value="b.id">{{ b.name_fa }}</option>
        </select>
      </div>
    </div>

    <!-- گیت‌ها: هر تاریخ یک دروازه است که پرونده باید رد کند -->
    <div class="border-t border-slate-100 pt-3">
      <p class="text-xs text-slate-400 mb-2">
        تاریخ‌ها — فاصله‌ی بین این‌ها همان چیزی است که گزارش‌ها از آن ساخته می‌شوند.
      </p>
      <div class="grid sm:grid-cols-2 gap-3">
        <div>
          <label :class="lbl">تاریخ ثبت سفارش</label>
          <input v-model="form.registered_on" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">اعتبار ثبت سفارش</label>
          <input v-model="form.valid_until" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">ورود به صف تخصیص ارز</label>
          <input v-model="form.queued_on" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">تایید تخصیص ارز</label>
          <input v-model="form.allocated_on" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">مهلت خرید ارز</label>
          <input v-model="form.purchase_deadline" :class="inp" type="date" dir="ltr" />
        </div>
        <div>
          <label :class="lbl">
            انتظار اعلامی بانک (روز)
            <span class="text-slate-400">— معیار «دیرکرد»</span>
          </label>
          <input
            v-model.number="form.expected_queue_days" :class="inp"
            inputmode="numeric" dir="ltr"
          />
        </div>
      </div>
    </div>

    <div class="grid sm:grid-cols-2 gap-3">
      <div>
        <label :class="lbl">وضعیت</label>
        <select v-model="form.status" :class="inp">
          <option
            v-for="s in options?.order_statuses ?? []" :key="s.value" :value="s.value"
          >{{ s.label }}</option>
        </select>
      </div>
    </div>

    <div>
      <label :class="lbl">توضیحات</label>
      <textarea v-model="form.note" :class="inp" rows="2" />
    </div>
  </FormModal>
</template>
