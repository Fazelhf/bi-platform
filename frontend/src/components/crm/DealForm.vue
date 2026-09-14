<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { crmApi, type Deal } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { pct, rial } from "@/utils/format";
import PickerField from "@/components/PickerField.vue";
import JalaliDateField from "@/components/JalaliDateField.vue";
import FormModal from "./FormModal.vue";
import MoreFields from "./MoreFields.vue";
import OwnerField from "./OwnerField.vue";
import MoneyInput from "./MoneyInput.vue";
import CustomerPicker from "./CustomerPicker.vue";
import CustomerForm from "./CustomerForm.vue";
import { apiError } from "./formError";

/**
 * ثبت / ویرایش معامله، همراه با اقلام.
 *
 * The line editor is still the important half: margin reporting is only as
 * good as the lines behind it, so quantity/price/discount are captured per
 * product and the resulting profit is shown live — a rep discounting into a
 * loss sees it before saving, not in next month's report.
 *
 * What changed is the order the form asks things in. Opening a deal is three
 * answers — who, at what stage, for what — and the previous layout mixed
 * those with the source, the expected close date and three deal-level cost
 * boxes that are almost always zero. Those now sit behind the fold, and the
 * costs only surface while the numbers they feed are on screen.
 *
 * Products are a searchable picker rather than a `<select>`. The list grows
 * every month, and scrolling it was the slowest thing in the form.
 */
const props = defineProps<{
  deal?: Deal | null;
  customerId?: number | null;
  stageId?: number | null;
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved", id: number): void }>();

const crm = useCrmStore();
const saving = ref(false);
const error = ref("");
const bad = ref("");
const picker = ref<InstanceType<typeof CustomerPicker> | null>(null);
const newCustomerName = ref<string | null>(null);

interface Line {
  product: number | "";
  quantity: string;
  unit_price_rial: string;
  unit_cost_rial: string;
  discount_pct: string;
}

const form = reactive({
  customer: (props.customerId ?? "") as number | "",
  customer_label: "",
  title: "",
  owner: "" as number | "",
  stage: (props.stageId ?? "") as number | "",
  lead_source: "" as number | "",
  lost_reason: "" as number | "",
  lost_note: "",
  discount_rial: "0",
  shipping_cost_rial: "0",
  other_cost_rial: "0",
  expected_close_date: "",
  items: [] as Line[],
});

const products = computed(() => crm.options?.products ?? []);
const productOptions = computed(() =>
  products.value.map((p) => ({
    value: p.id,
    label: p.name_fa,
    badge: p.unit || undefined,
  })),
);
const stages = computed(() => crm.options?.stages ?? []);
const selectedStage = computed(() => stages.value.find((s) => s.id === form.stage));
const isLostStage = computed(() => selectedStage.value?.kind === "lost");
const isEdit = computed(() => !!props.deal);

const sourceOptions = computed(() =>
  (crm.options?.sources ?? []).map((s) => ({ value: s.id, label: s.name_fa })),
);
const reasonOptions = computed(() =>
  (crm.options?.reasons ?? []).map((r) => ({ value: r.id, label: r.name_fa })),
);

onMounted(async () => {
  await crm.loadOptions();
  if (props.deal) {
    const d = props.deal as any;
    Object.assign(form, {
      customer: d.customer,
      customer_label: d.customer_name,
      title: d.title,
      owner: d.owner ?? "",
      stage: d.stage ?? "",
      lead_source: d.lead_source ?? "",
      lost_reason: d.lost_reason ?? "",
      lost_note: d.lost_note ?? "",
      discount_rial: String(Number(d.discount_rial ?? 0)),
      shipping_cost_rial: String(Number(d.shipping_cost_rial ?? 0)),
      other_cost_rial: String(Number(d.other_cost_rial ?? 0)),
      expected_close_date: d.expected_close_date ?? "",
      items: (d.items ?? []).map((i: any) => ({
        product: i.product,
        quantity: String(Number(i.quantity)),
        unit_price_rial: String(Number(i.unit_price_rial)),
        unit_cost_rial: String(Number(i.unit_cost_rial)),
        discount_pct: String(Number(i.discount_pct)),
      })),
    });
  } else {
    if (!form.stage) {
      form.stage = stages.value.find((s) => s.kind === "open")?.id ?? "";
    }
    if (props.customerId) {
      const c = await crmApi.customer(props.customerId);
      form.customer_label = c.name_fa;
      if ((c as any).lead_source) form.lead_source = (c as any).lead_source;
    }
    addLine();
  }
});

function onCustomerCreated(id: number, name: string) {
  newCustomerName.value = null;
  if (id) picker.value?.select(id, name);
}

// ---- lines ----------------------------------------------------------------
function addLine() {
  form.items.push({
    product: "", quantity: "1", unit_price_rial: "0",
    unit_cost_rial: "0", discount_pct: "0",
  });
}
function removeLine(i: number) {
  form.items.splice(i, 1);
}

/** Selecting a product fills price and cost from the price list. */
function onProduct(line: Line, value: number | null) {
  line.product = value ?? "";
  const p = products.value.find((x) => x.id === value);
  if (!p) return;
  line.unit_price_rial = String(Number(p.list_price_rial));
  line.unit_cost_rial = String(Number((p as any).unit_cost_rial ?? 0));
}

const n = (v: any) => Number(String(v).replace(/[^\d.-]/g, "")) || 0;

function lineTotal(l: Line) {
  return n(l.quantity) * n(l.unit_price_rial) * (100 - n(l.discount_pct)) / 100;
}
function lineCost(l: Line) {
  return n(l.quantity) * n(l.unit_cost_rial);
}

const totals = computed(() => {
  const gross = form.items.reduce((s, l) => s + lineTotal(l), 0);
  const lineCosts = form.items.reduce((s, l) => s + lineCost(l), 0);
  const amount = gross - n(form.discount_rial);
  const cost = lineCosts + n(form.shipping_cost_rial) + n(form.other_cost_rial);
  return {
    gross, amount, cost,
    profit: amount - cost,
    margin: amount ? ((amount - cost) / amount) * 100 : 0,
  };
});

/** Folded fields that already say something, so nothing looks lost. */
const filledExtra = computed(() =>
  [
    form.title, form.lead_source, form.expected_close_date,
    n(form.discount_rial) || "", n(form.shipping_cost_rial) || "",
    n(form.other_cost_rial) || "",
  ].filter((v) => v !== "" && v !== null).length,
);

// ---- save -----------------------------------------------------------------
async function save() {
  bad.value = "";
  if (!form.customer) {
    error.value = "مشتری را انتخاب کنید.";
    bad.value = "customer";
    return;
  }
  const lines = form.items.filter((l) => l.product !== "");
  if (!lines.length) {
    error.value = "حداقل یک قلم محصول اضافه کنید — مبلغ معامله از روی اقلام محاسبه می‌شود.";
    bad.value = "items";
    return;
  }
  // An ownerless deal is invisible in every per-rep report, which is most of
  // them. A rep never sees this: OwnerField filled it in for them.
  if (!form.owner) {
    error.value = "انتخاب کارشناس الزامی است — بدون آن، این معامله در گزارش‌های کارشناسان دیده نمی‌شود.";
    bad.value = "owner";
    return;
  }
  if (isLostStage.value && !form.lost_reason) {
    error.value = "برای ثبت فرصت از دست رفته، انتخاب دلیل الزامی است.";
    bad.value = "lost_reason";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const payload: Record<string, any> = {
      customer: form.customer,
      title: form.title || undefined,
      owner: form.owner || null,
      stage: form.stage || null,
      lead_source: form.lead_source || null,
      lost_reason: isLostStage.value ? form.lost_reason || null : null,
      lost_note: isLostStage.value ? form.lost_note : "",
      discount_rial: n(form.discount_rial),
      shipping_cost_rial: n(form.shipping_cost_rial),
      other_cost_rial: n(form.other_cost_rial),
      expected_close_date: form.expected_close_date || null,
      items: lines.map((l) => ({
        product: l.product,
        quantity: n(l.quantity),
        unit_price_rial: Math.round(n(l.unit_price_rial)),
        unit_cost_rial: Math.round(n(l.unit_cost_rial)),
        discount_pct: n(l.discount_pct),
      })),
    };
    const saved = await crmApi.saveDeal(payload, props.deal?.id);
    emit("saved", saved.id ?? props.deal!.id);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  saving.value = true;
  try {
    await crmApi.deleteDeal(props.deal!.id);
    emit("saved", 0);
  } catch (e) {
    error.value = apiError(e);
    saving.value = false;
  }
}

const inp = "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";
const cell = "w-full bg-slate-100 rounded-lg px-2 py-1.5 text-sm text-ink outline-none";
const lbl = "block text-xs text-slate-500 mb-1";
const chip = "px-3 py-1.5 rounded-xl text-sm transition-colors";
const chipOn = "bg-panel text-white";
const chipOff = "bg-slate-100 text-slate-600 hover:bg-slate-200";
</script>

<template>
  <FormModal
    :title="isEdit ? 'ویرایش معامله' : 'معامله جدید'"
    :subtitle="form.customer_label"
    :saving="saving" :error="error" :can-delete="isEdit" wide
    @close="emit('close')" @save="save" @delete="remove"
  >
    <!-- ===== Who ===== -->
    <div>
      <label :class="lbl">مشتری *</label>
      <CustomerPicker
        ref="picker"
        v-model="form.customer"
        v-model:label="form.customer_label"
        :locked="!!customerId"
        :invalid="bad === 'customer'"
        @create="newCustomerName = $event"
      />
    </div>

    <!-- ===== Where in the pipeline — the whole path, visible at once ===== -->
    <div>
      <label :class="lbl">مرحله فروش</label>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="s in stages" :key="s.id"
          type="button" :class="[chip, form.stage === s.id ? chipOn : chipOff]"
          @click="form.stage = s.id"
        >{{ s.name_fa }}</button>
      </div>
    </div>

    <!-- Only asked when the chosen stage makes it a real question. -->
    <div v-if="isLostStage" class="grid sm:grid-cols-2 gap-3">
      <div>
        <label :class="lbl">دلیل از دست رفتن *</label>
        <PickerField
          v-model="form.lost_reason"
          :options="reasonOptions"
          placeholder="— انتخاب کنید —"
          :invalid="bad === 'lost_reason'"
        />
      </div>
      <div>
        <label :class="lbl">توضیح</label>
        <input v-model="form.lost_note" :class="inp" />
      </div>
    </div>

    <!-- ===== What ===== -->
    <div>
      <div class="flex items-center justify-between mb-2">
        <h3 class="text-sm font-semibold" :class="bad === 'items' ? 'text-red-500' : 'text-ink'">
          اقلام
        </h3>
        <button
          type="button"
          class="text-xs bg-slate-100 hover:bg-slate-200 rounded-lg px-3 py-1.5 text-slate-600"
          @click="addLine"
        >+ افزودن قلم</button>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[620px]">
          <thead>
            <tr class="text-xs text-slate-400">
              <th class="text-right font-medium pb-1">محصول</th>
              <th class="text-right font-medium pb-1 w-20">تعداد</th>
              <th class="text-right font-medium pb-1 w-36">قیمت واحد</th>
              <th class="text-right font-medium pb-1 w-20">تخفیف٪</th>
              <th class="text-left font-medium pb-1 w-28">مبلغ</th>
              <th class="w-8"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(l, i) in form.items" :key="i">
              <td class="py-1 pl-1">
                <PickerField
                  :model-value="l.product === '' ? null : l.product"
                  :options="productOptions"
                  placeholder="— انتخاب محصول —"
                  search-placeholder="نام محصول…"
                  @update:model-value="onProduct(l, $event as number | null)"
                />
              </td>
              <td class="py-1 pl-1"><input v-model="l.quantity" :class="cell" dir="ltr" /></td>
              <td class="py-1 pl-1"><MoneyInput v-model="l.unit_price_rial" cell /></td>
              <td class="py-1 pl-1"><input v-model="l.discount_pct" :class="cell" dir="ltr" /></td>
              <td class="py-1 text-left text-ink whitespace-nowrap">{{ rial(lineTotal(l)) }}</td>
              <td class="py-1 text-center">
                <button
                  type="button" class="text-slate-300 hover:text-red-500"
                  @click="removeLine(i)"
                >×</button>
              </td>
            </tr>
            <tr v-if="!form.items.length">
              <td colspan="6" class="text-xs text-slate-400 py-3 text-center">
                هنوز قلمی اضافه نشده است
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Live margin — the reason the line editor is worth its length. -->
    <div class="bg-slate-50 rounded-xl p-3 grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
      <div>
        <p class="text-xs text-slate-400">مبلغ فرصت</p>
        <p class="font-bold text-ink">{{ rial(totals.amount) }}</p>
      </div>
      <div>
        <p class="text-xs text-slate-400">بهای تمام‌شده</p>
        <p class="font-bold text-ink">{{ rial(totals.cost) }}</p>
      </div>
      <div>
        <p class="text-xs text-slate-400">سود</p>
        <p class="font-bold" :class="totals.profit >= 0 ? 'text-emerald-600' : 'text-red-500'">
          {{ rial(totals.profit) }}
        </p>
      </div>
      <div>
        <p class="text-xs text-slate-400">حاشیه سود</p>
        <p
          class="font-bold"
          :class="totals.margin >= 15 ? 'text-emerald-600' : totals.margin >= 5 ? 'text-amber-600' : 'text-red-500'"
        >{{ pct(totals.margin) }}</p>
      </div>
    </div>

    <OwnerField v-model="form.owner" :invalid="bad === 'owner'" />

    <!-- ===== The rest ===== -->
    <MoreFields :filled="filledExtra" :start-open="isEdit">
      <div class="grid sm:grid-cols-2 gap-3">
        <div class="sm:col-span-2">
          <label :class="lbl">
            عنوان <span class="text-slate-300">(خالی بگذارید تا خودکار ساخته شود)</span>
          </label>
          <input v-model="form.title" :class="inp" />
        </div>
        <div>
          <label :class="lbl">منبع سرنخ</label>
          <PickerField v-model="form.lead_source" :options="sourceOptions" placeholder="— انتخاب کنید —" />
        </div>
        <div>
          <label :class="lbl">تاریخ پیش‌بینی بسته شدن</label>
          <JalaliDateField v-model="form.expected_close_date" placeholder="انتخاب تاریخ" />
        </div>
      </div>

      <div class="grid sm:grid-cols-3 gap-3">
        <div>
          <label :class="lbl">تخفیف کل (ریال)</label>
          <MoneyInput v-model="form.discount_rial" />
        </div>
        <div>
          <label :class="lbl">هزینه حمل (ریال)</label>
          <MoneyInput v-model="form.shipping_cost_rial" />
        </div>
        <div>
          <label :class="lbl">سایر هزینه‌ها (ریال)</label>
          <MoneyInput v-model="form.other_cost_rial" />
        </div>
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
