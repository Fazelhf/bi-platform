<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { crmApi, type Deal } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { pct, rial } from "@/utils/format";
import FormModal from "./FormModal.vue";
import { apiError } from "./formError";

/**
 * ثبت / ویرایش معامله، همراه با اقلام.
 *
 * The line editor is the important half: margin reporting is only as good as
 * the lines behind it, so quantity/price/discount are captured per product
 * and the resulting profit is shown live — a rep discounting into a loss sees
 * it before saving, not in next month's report.
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
const customerSearch = ref("");
const customerResults = ref<{ id: number; name_fa: string; province_name: string }[]>([]);
const searching = ref(false);

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
const stages = computed(() => crm.options?.stages ?? []);
const selectedStage = computed(() => stages.value.find((s) => s.id === form.stage));
const isLostStage = computed(() => selectedStage.value?.kind === "lost");
const isEdit = computed(() => !!props.deal);

onMounted(async () => {
  await crm.loadOptions();
  if (props.deal) {
    const d = props.deal;
    Object.assign(form, {
      customer: d.customer,
      customer_label: d.customer_name,
      title: d.title,
      owner: d.owner ?? "",
      stage: d.stage ?? "",
      lead_source: (d as any).lead_source ?? "",
      lost_reason: (d as any).lost_reason ?? "",
      lost_note: d.lost_note ?? "",
      discount_rial: String(Number(d.discount_rial ?? 0)),
      shipping_cost_rial: String(Number(d.shipping_cost_rial ?? 0)),
      other_cost_rial: String(Number(d.other_cost_rial ?? 0)),
      expected_close_date: d.expected_close_date ?? "",
      items: (d.items ?? []).map((i) => ({
        product: i.product,
        quantity: String(Number(i.quantity)),
        unit_price_rial: String(Number(i.unit_price_rial)),
        unit_cost_rial: String(Number(i.unit_cost_rial)),
        discount_pct: String(Number(i.discount_pct)),
      })),
    });
  } else {
    if (crm.me?.employee) form.owner = crm.me.employee;
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

// ---- customer picker ------------------------------------------------------
let searchTimer: number | undefined;
watch(customerSearch, (q) => {
  window.clearTimeout(searchTimer);
  if (!q.trim()) {
    customerResults.value = [];
    return;
  }
  searching.value = true;
  searchTimer = window.setTimeout(async () => {
    try {
      const res = await crmApi.customers({ search: q, page_size: 8 });
      customerResults.value = res.results as any;
    } finally {
      searching.value = false;
    }
  }, 300);
});

function pickCustomer(c: any) {
  form.customer = c.id;
  form.customer_label = c.name_fa;
  customerSearch.value = "";
  customerResults.value = [];
}

// ---- lines ----------------------------------------------------------------
function addLine() {
  form.items.push({ product: "", quantity: "1", unit_price_rial: "0", unit_cost_rial: "0", discount_pct: "0" });
}
function removeLine(i: number) {
  form.items.splice(i, 1);
}

/** Selecting a product fills price and cost from the price list. */
function onProduct(line: Line) {
  const p = products.value.find((x) => x.id === line.product);
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
  return { gross, amount, cost, profit: amount - cost, margin: amount ? ((amount - cost) / amount) * 100 : 0 };
});

// ---- save -----------------------------------------------------------------
async function save() {
  if (!form.customer) {
    error.value = "انتخاب مشتری الزامی است.";
    return;
  }
  const lines = form.items.filter((l) => l.product !== "");
  if (!lines.length) {
    error.value = "حداقل یک قلم محصول اضافه کنید.";
    return;
  }
  // An ownerless deal is invisible in every per-rep report, which is most of
  // them. Reps never see this message (they are pre-filled); a manager
  // entering on someone's behalf has to say on whose.
  if (!form.owner) {
    error.value = "انتخاب کارشناس الزامی است — بدون آن، این معامله در گزارش‌های کارشناسان دیده نمی‌شود.";
    return;
  }
  if (isLostStage.value && !form.lost_reason) {
    error.value = "برای ثبت فرصت از دست رفته، انتخاب دلیل الزامی است.";
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
</script>

<template>
  <FormModal
    :title="isEdit ? 'ویرایش معامله' : 'معامله جدید'"
    :subtitle="form.customer_label"
    :saving="saving" :error="error" :can-delete="isEdit" wide
    @close="emit('close')" @save="save" @delete="remove"
  >
    <div class="grid sm:grid-cols-2 gap-3">
      <!-- Customer -->
      <div class="sm:col-span-2">
        <label :class="lbl">مشتری *</label>
        <div v-if="form.customer" class="flex items-center gap-2">
          <span class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink flex-1">{{ form.customer_label }}</span>
          <button v-if="!customerId" class="text-xs text-slate-400 hover:text-ink px-2" @click="form.customer = ''; form.customer_label = ''">تغییر</button>
        </div>
        <div v-else class="relative">
          <input v-model="customerSearch" :class="inp" placeholder="نام مشتری را جستجو کنید…" />
          <ul v-if="customerResults.length" class="absolute z-10 mt-1 w-full bg-surface rounded-xl shadow-pop border border-slate-100 max-h-52 overflow-y-auto">
            <li
              v-for="c in customerResults" :key="c.id"
              class="px-3 py-2 text-sm hover:bg-slate-100 cursor-pointer"
              @click="pickCustomer(c)"
            >
              {{ c.name_fa }}
              <span class="text-xs text-slate-400">{{ c.province_name }}</span>
            </li>
          </ul>
          <p v-else-if="customerSearch && !searching" class="text-xs text-slate-400 mt-1">مشتری‌ای پیدا نشد</p>
        </div>
      </div>

      <div class="sm:col-span-2">
        <label :class="lbl">عنوان <span class="text-slate-300">(خالی بگذارید تا خودکار ساخته شود)</span></label>
        <input v-model="form.title" :class="inp" />
      </div>

      <div>
        <label :class="lbl">مرحله فروش</label>
        <select v-model="form.stage" :class="inp">
          <option v-for="s in stages" :key="s.id" :value="s.id">{{ s.name_fa }}</option>
        </select>
      </div>
      <div>
        <label :class="lbl">کارشناس *</label>
        <select v-model="form.owner" :class="inp">
          <option value="">— انتخاب کنید —</option>
          <option v-for="e in crm.options?.employees" :key="e.id" :value="e.id">{{ e.name }}</option>
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
        <label :class="lbl">تاریخ پیش‌بینی بسته شدن</label>
        <input v-model="form.expected_close_date" type="date" :class="inp" />
      </div>

      <!-- Lost reason only when the chosen stage is a loss -->
      <template v-if="isLostStage">
        <div>
          <label :class="lbl">دلیل از دست رفتن *</label>
          <select v-model="form.lost_reason" :class="inp">
            <option value="">— انتخاب کنید —</option>
            <option v-for="r in crm.options?.reasons" :key="r.id" :value="r.id">{{ r.name_fa }}</option>
          </select>
        </div>
        <div>
          <label :class="lbl">توضیح</label>
          <input v-model="form.lost_note" :class="inp" />
        </div>
      </template>
    </div>

    <!-- Lines -->
    <div>
      <div class="flex items-center justify-between mb-2">
        <h3 class="text-sm font-semibold text-ink">اقلام</h3>
        <button class="text-xs bg-slate-100 hover:bg-slate-200 rounded-lg px-3 py-1.5 text-slate-600" @click="addLine">
          + افزودن قلم
        </button>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[600px]">
          <thead>
            <tr class="text-xs text-slate-400">
              <th class="text-right font-medium pb-1">محصول</th>
              <th class="text-right font-medium pb-1 w-20">تعداد</th>
              <th class="text-right font-medium pb-1 w-32">قیمت واحد</th>
              <th class="text-right font-medium pb-1 w-20">تخفیف٪</th>
              <th class="text-left font-medium pb-1 w-28">مبلغ</th>
              <th class="w-8"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(l, i) in form.items" :key="i">
              <td class="py-1 pl-1">
                <select v-model="l.product" :class="cell" @change="onProduct(l)">
                  <option value="">— انتخاب محصول —</option>
                  <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name_fa }}</option>
                </select>
              </td>
              <td class="py-1 pl-1"><input v-model="l.quantity" :class="cell" dir="ltr" /></td>
              <td class="py-1 pl-1"><input v-model="l.unit_price_rial" :class="cell" dir="ltr" /></td>
              <td class="py-1 pl-1"><input v-model="l.discount_pct" :class="cell" dir="ltr" /></td>
              <td class="py-1 text-left text-ink whitespace-nowrap">{{ rial(lineTotal(l)) }}</td>
              <td class="py-1 text-center">
                <button class="text-slate-300 hover:text-red-500" @click="removeLine(i)">×</button>
              </td>
            </tr>
            <tr v-if="!form.items.length">
              <td colspan="6" class="text-xs text-slate-400 py-3 text-center">هنوز قلمی اضافه نشده است</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Deal-level costs -->
    <div class="grid sm:grid-cols-3 gap-3">
      <div>
        <label :class="lbl">تخفیف کل (ریال)</label>
        <input v-model="form.discount_rial" :class="inp" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">هزینه حمل (ریال)</label>
        <input v-model="form.shipping_cost_rial" :class="inp" dir="ltr" />
      </div>
      <div>
        <label :class="lbl">سایر هزینه‌ها (ریال)</label>
        <input v-model="form.other_cost_rial" :class="inp" dir="ltr" />
      </div>
    </div>

    <!-- Live margin -->
    <div class="bg-slate-50 rounded-xl p-3 grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
      <div><p class="text-xs text-slate-400">مبلغ فرصت</p><p class="font-bold text-ink">{{ rial(totals.amount) }}</p></div>
      <div><p class="text-xs text-slate-400">بهای تمام‌شده</p><p class="font-bold text-ink">{{ rial(totals.cost) }}</p></div>
      <div>
        <p class="text-xs text-slate-400">سود</p>
        <p class="font-bold" :class="totals.profit >= 0 ? 'text-emerald-600' : 'text-red-500'">{{ rial(totals.profit) }}</p>
      </div>
      <div>
        <p class="text-xs text-slate-400">حاشیه سود</p>
        <p class="font-bold" :class="totals.margin >= 15 ? 'text-emerald-600' : totals.margin >= 5 ? 'text-amber-600' : 'text-red-500'">
          {{ pct(totals.margin) }}
        </p>
      </div>
    </div>
  </FormModal>
</template>
