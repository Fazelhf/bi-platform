<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  sales2Api,
  type Balance,
  type CheckItem,
  type DocKind,
  type Options,
  type ProductRow,
  type Quote,
  type SalesDoc,
} from "@/api/sales2";
import CustomerSearch from "@/components/sales2/CustomerSearch.vue";
import PickerField from "@/components/PickerField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import JalaliDateField from "@/components/JalaliDateField.vue";
import Skeleton from "@/components/Skeleton.vue";
import { apiError } from "@/components/crm/formError";
import { confirm, prompt, toast } from "@/composables/useUi";
import { faDate, faDateTime } from "@/utils/adminFormat";

/**
 * پیش‌فاکتور / فاکتور / مرجوعی — one editor for all three.
 *
 * A draft is a form; an issued document is paper, shown read-only with the
 * actions that follow it (چاپ، تبدیل، مرجوعی، حواله، دریافت، ابطال). The
 * money is computed here as you type so the totals are never a surprise, but
 * the server recomputes everything and its figures are the ones saved.
 */
const route = useRoute();
const router = useRouter();

const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));
const inp = "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";

const KIND_LABEL: Record<DocKind, string> = { proforma: "پیش‌فاکتور", invoice: "فاکتور فروش", return: "مرجوعی" };
const LIST_ROUTE: Record<DocKind, string> = { proforma: "sales2-proformas", invoice: "sales2-invoices", return: "sales2-returns" };
const STATUS_CLASS: Record<string, string> = {
  draft: "bg-slate-100 text-slate-600",
  issued: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-red-100 text-red-600",
};

interface EditLine {
  key: number;
  product: number | null;
  source_line: number | null;
  product_name: string;
  unit: string;
  /** 48/55 for a roll — the same size is priced and costed per grammage. */
  grammage: number | null;
  isRoll: boolean;
  /** Where the suggested price came from: a price sheet's name, or fixed. */
  priceSource: string;
  /** Once the user types a price, a quantity change no longer re-prices it. */
  priceTouched: boolean;
  description: string;
  quantity: string;
  unit_price_rial: string;
  discount_pct: string;
  unit_cost_rial: string;
  min_price_rial: string;
  max_qty: string | null;
  last_sale: Quote["last_sale"];
}

const loading = ref(true);
const saving = ref(false);
const error = ref("");
const doc = ref<SalesDoc | null>(null);
const options = ref<Options | null>(null);
const products = ref<ProductRow[]>([]);
const balance = ref<Balance | null>(null);
const checks = ref<CheckItem[] | null>(null);
let nextKey = 1;

const kind = computed<DocKind>(() => (doc.value?.kind ?? (route.params.kind as DocKind)) || "invoice");
const isDraft = computed(() => !doc.value || doc.value.status === "draft");
const isReturn = computed(() => kind.value === "return");

const form = ref({
  customer: null as number | null,
  customerLabel: "",
  salesperson: null as number | null,
  doc_date: new Date().toISOString().slice(0, 10),
  valid_until: "",
  due_date: "",
  settlement: "cash",
  warehouse: null as number | null,
  is_official: true,
  vat_pct: "10",
  note: "",
});
const lines = ref<EditLine[]>([]);

function blankLine(): EditLine {
  return {
    key: nextKey++, product: null, source_line: null, product_name: "", unit: "",
    grammage: null, isRoll: false, priceSource: "", priceTouched: false,
    description: "", quantity: "1", unit_price_rial: "", discount_pct: "0",
    unit_cost_rial: "0", min_price_rial: "0", max_qty: null, last_sale: null,
  };
}

function fromDoc(d: SalesDoc) {
  doc.value = d;
  form.value = {
    customer: d.customer,
    customerLabel: d.customer_name || d.customer_info.name_fa,
    salesperson: d.salesperson,
    doc_date: d.doc_date,
    valid_until: d.valid_until ?? "",
    due_date: d.due_date ?? "",
    settlement: d.settlement,
    warehouse: d.warehouse,
    is_official: d.is_official,
    vat_pct: d.vat_pct,
    note: d.note,
  };
  lines.value = d.lines.map((l) => ({
    key: nextKey++, product: l.product, source_line: l.source_line,
    product_name: l.product_name, unit: l.unit, description: l.description,
    grammage: l.grammage, isRoll: !!l.grammage || /^\s*\d{2,3}\s*-\s*\d{1,3}/.test(l.product_name) && !l.product_name.includes("لیبل"),
    priceSource: "", priceTouched: true,
    quantity: String(Number(l.quantity)), unit_price_rial: String(Number(l.unit_price_rial)),
    discount_pct: String(Number(l.discount_pct)), unit_cost_rial: l.unit_cost_rial ?? "0",
    min_price_rial: l.min_price_rial ?? "0", max_qty: null, last_sale: null,
  }));
  checks.value = d.status === "draft" ? null : d.issue_checks;
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [opt, prods] = await Promise.all([sales2Api.options(), sales2Api.products({ sellable: 1 })]);
    options.value = opt;
    products.value = prods.rows;
    if (route.params.id) {
      fromDoc(await sales2Api.document(Number(route.params.id)));
    } else {
      doc.value = null;
      form.value.vat_pct = opt.settings.vat_pct;
      form.value.warehouse = opt.settings.default_warehouse;
      const c = Number(route.query.customer);
      if (c) {
        const detail = await sales2Api.customer(c);
        form.value.customer = c;
        form.value.customerLabel = detail.name_fa;
      }
      lines.value = [blankLine()];
    }
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(() => route.fullPath, (to, from) => { if (to !== from) load(); });

watch(() => form.value.customer, async (id) => {
  balance.value = null;
  if (!id || isReturn.value) return;
  try {
    const d = await sales2Api.customer(id);
    balance.value = d.balance;
    if (!form.value.salesperson && d.owner && isDraft.value) form.value.salesperson = d.owner;
  } catch { /* the balance card is a courtesy; the issue check is the rule */ }
});

const productOptions = computed(() => products.value.map((p) => ({
  value: p.id,
  label: p.name_fa,
  hint: [p.category, p.is_roll ? `رول ${p.width_mm}×${p.length_m}` : ""].filter(Boolean).join(" · "),
  badge: p.unit_label,
  keywords: p.code,
})));

async function onProduct(line: EditLine, id: number | null) {
  line.product = id;
  if (!id) return;
  const p = products.value.find((x) => x.id === id);
  line.product_name = p?.name_fa ?? "";
  line.unit = p?.unit_label ?? "";
  line.min_price_rial = p?.min_price_rial ?? "0";
  line.priceTouched = false;
  await requote(line);
}

/**
 * Ask the price list what this line should cost: the formula price for a
 * roll at its grammage, رسمی or not, and quantity tier; its فی حسابداری; and
 * the last price this customer paid. That last price wins when there is one —
 * it is what the customer will expect — and the list price is the fallback.
 */
async function requote(line: EditLine) {
  if (!line.product) return;
  const q = await sales2Api.quote({
    product: line.product, grammage: line.grammage, official: form.value.is_official,
    quantity: line.quantity, customer: form.value.customer, date: form.value.doc_date,
  });
  line.isRoll = q.is_roll;
  if (q.is_roll && !line.grammage) {
    line.priceSource = "گرماژ را انتخاب کنید";
    return;
  }
  line.unit_cost_rial = q.cost_rial ?? "0";
  line.last_sale = q.last_sale;
  line.priceSource = q.source;
  if (line.priceTouched) return;
  const start = q.last_sale?.unit_price_rial ?? q.price_rial;
  if (Number(start)) line.unit_price_rial = String(Number(start));
  if (q.last_sale) line.discount_pct = String(Number(q.last_sale.discount_pct));
}

let requoteTimer: ReturnType<typeof setTimeout> | undefined;
function onQuantity(line: EditLine) {
  clearTimeout(requoteTimer);
  requoteTimer = setTimeout(() => requote(line), 400);
}

// رسمی and غیر رسمی are different sheets, so flipping it re-prices every
// line that has not been priced by hand.
watch(() => form.value.is_official, () => {
  if (isDraft.value) lines.value.forEach((l) => requote(l));
});

function calc(l: EditLine) {
  const gross = Math.round(Number(l.quantity || 0) * Number(l.unit_price_rial || 0));
  const disc = Math.round(gross * Number(l.discount_pct || 0) / 100);
  const net = gross - disc;
  const vat = form.value.is_official ? Math.round(net * Number(form.value.vat_pct || 0) / 100) : 0;
  const cost = Math.round(Number(l.quantity || 0) * Number(l.unit_cost_rial || 0));
  const netUnit = Number(l.quantity) ? net / Number(l.quantity) : 0;
  return {
    gross, disc, net, vat, total: net + vat, cost,
    loss: !isReturn.value && Number(l.unit_cost_rial) > 0 && netUnit < Number(l.unit_cost_rial),
    noCost: !isReturn.value && !Number(l.unit_cost_rial),
    belowMin: !isReturn.value && Number(l.min_price_rial) > 0 && netUnit < Number(l.min_price_rial),
  };
}

const totals = computed(() => {
  const t = { gross: 0, disc: 0, net: 0, vat: 0, total: 0, cost: 0 };
  for (const l of lines.value) {
    const c = calc(l);
    t.gross += c.gross; t.disc += c.disc; t.net += c.net; t.vat += c.vat; t.total += c.total; t.cost += c.cost;
  }
  return t;
});
const profitPct = computed(() => (totals.value.net && totals.value.cost
  ? Math.round(((totals.value.net - totals.value.cost) / totals.value.net) * 1000) / 10 : null));

function payload() {
  return {
    kind: kind.value,
    customer: form.value.customer,
    salesperson: form.value.salesperson,
    doc_date: form.value.doc_date,
    valid_until: form.value.valid_until || null,
    due_date: form.value.due_date || null,
    settlement: form.value.settlement,
    warehouse: form.value.warehouse,
    is_official: form.value.is_official,
    vat_pct: form.value.vat_pct,
    note: form.value.note,
    lines: lines.value.filter((l) => l.product).map((l) => ({
      product: l.product, source_line: l.source_line, grammage: l.grammage, description: l.description,
      quantity: l.quantity || 0, unit_price_rial: l.unit_price_rial || 0, discount_pct: l.discount_pct || 0,
    })),
  };
}

async function save(silent = false): Promise<SalesDoc | null> {
  if (!form.value.customer) { error.value = "مشتری را انتخاب کنید."; return null; }
  saving.value = true;
  error.value = "";
  try {
    const saved = await sales2Api.saveDocument(payload(), doc.value?.id);
    if (!doc.value) {
      await router.replace({ name: "sales2-document", params: { id: saved.id }, query: { kind: saved.kind } });
    }
    fromDoc(saved);
    if (!silent) toast.success("پیش‌نویس ذخیره شد.");
    return saved;
  } catch (e) {
    error.value = apiError(e);
    return null;
  } finally {
    saving.value = false;
  }
}

async function runCheck() {
  const saved = await save(true);
  if (!saved) return;
  checks.value = await sales2Api.check(saved.id);
  if (!checks.value.length) toast.success("سند مشکلی ندارد.");
}

async function issue() {
  const saved = await save(true);
  if (!saved) return;
  saving.value = true;
  try {
    let reason = "";
    const found = await sales2Api.check(saved.id);
    checks.value = found;
    if (found.some((c) => c.level === "error")) {
      error.value = "سند ایراد دارد؛ موارد قرمز را برطرف کنید.";
      return;
    }
    if (found.some((c) => c.level === "block")) {
      const r = await prompt({
        title: "صدور با عبور از کنترل",
        message: found.filter((c) => c.level === "block").map((c) => `• ${c.message}`).join("\n")
          + "\n\nدلیل صدور را بنویسید؛ کنار سند ثبت می‌شود.",
        placeholder: "مثلاً: حراج پایان فصل با تأیید مدیرعامل",
      });
      if (!r || !r.trim()) return;
      reason = r.trim();
    } else {
      const ok = await confirm({
        title: `صدور ${KIND_LABEL[kind.value]}`,
        message: "پس از صدور، سند شماره می‌گیرد و دیگر ویرایش نمی‌شود. ادامه؟",
      });
      if (!ok) return;
    }
    fromDoc(await sales2Api.issue(saved.id, reason));
    toast.success(`${KIND_LABEL[kind.value]} ${doc.value?.number} صادر شد.`);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

async function removeDraft() {
  if (!doc.value) { router.push({ name: LIST_ROUTE[kind.value] }); return; }
  if (!(await confirm({ title: "حذف پیش‌نویس", message: "این پیش‌نویس حذف شود؟", danger: true }))) return;
  await sales2Api.removeDocument(doc.value.id);
  router.push({ name: LIST_ROUTE[kind.value] });
}

async function act(fn: () => Promise<SalesDoc>, okMsg: string, navigate = false) {
  error.value = "";
  try {
    const d = await fn();
    toast.success(okMsg);
    if (navigate) router.push({ name: "sales2-document", params: { id: d.id }, query: { kind: d.kind } });
    else fromDoc(d);
  } catch (e) {
    error.value = apiError(e);
  }
}

async function cancelDoc() {
  const reason = await prompt({ title: "ابطال سند", message: "دلیل ابطال را بنویسید.", placeholder: "دلیل…" });
  if (!reason?.trim() || !doc.value) return;
  await act(() => sales2Api.cancel(doc.value!.id, reason.trim()), "سند ابطال شد.");
}

const convert = () => act(() => sales2Api.convert(doc.value!.id), "پیش‌نویس فاکتور ساخته شد.", true);
const makeReturn = (type: "goods" | "undelivered") =>
  act(() => sales2Api.makeReturn(doc.value!.id, type),
    type === "goods" ? "پیش‌نویس مرجوعی کالا ساخته شد." : "پیش‌نویس کسر تحویل‌نشده ساخته شد.", true);

async function closeRemainder() {
  const reason = await prompt({ title: "بستن مانده‌ی پیش‌فاکتور", message: "مانده‌ی این پیش‌فاکتور دیگر فاکتور نمی‌شود. دلیل؟" });
  if (!reason?.trim() || !doc.value) return;
  await act(() => sales2Api.closeProforma(doc.value!.id, reason.trim()), "مانده‌ی پیش‌فاکتور بسته شد.");
}

const INVOICING_LABEL: Record<string, { label: string; cls: string }> = {
  open: { label: "فاکتور نشده", cls: "bg-slate-100 text-slate-600" },
  partial: { label: "بخشی فاکتورشده", cls: "bg-amber-100 text-amber-700" },
  full: { label: "کامل فاکتورشده", cls: "bg-sky-100 text-sky-700" },
  closed: { label: "مانده بسته شد", cls: "bg-slate-200 text-slate-600" },
};
/** Invoice lines: is there anything delivered to return, or undelivered to write off? */
const canReturnGoods = computed(() => doc.value?.lines.some((l) => Number(l.returnable_qty ?? 0) > 0));
const canReduce = computed(() => doc.value?.lines.some((l) => Number(l.deliverable_qty ?? 0) > 0));
const canConvert = computed(() => doc.value?.invoicing_state === "open" || doc.value?.invoicing_state === "partial");
const duplicate = () => act(() => sales2Api.duplicate(doc.value!.id), "کپی سند ساخته شد.", true);

function printDoc() {
  const url = router.resolve({ name: "sales2-print", params: { id: doc.value!.id } }).href;
  window.open(url, "_blank");
}

const levelClass: Record<string, string> = {
  error: "bg-red-50 text-red-700 border-red-200",
  block: "bg-amber-50 text-amber-800 border-amber-200",
  warn: "bg-slate-50 text-slate-600 border-slate-200",
};
const levelLabel: Record<string, string> = { error: "ایراد", block: "نیاز به دلیل", warn: "هشدار" };

const deliveryLabel: Record<string, string> = { none: "تحویل نشده", partial: "تحویل جزئی", full: "تحویل کامل" };
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-24 rounded-card" />
      <Skeleton class="h-64 rounded-card" />
    </div>

    <template v-else>
      <!-- Header strip: what this is and what can be done with it -->
      <div class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-center gap-3">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 flex-wrap">
            <h1 class="text-lg font-bold text-ink">
              {{ KIND_LABEL[kind] }}
              <span class="ltr-nums">{{ doc?.number || (doc ? `پیش‌نویس #${doc.id}` : "جدید") }}</span>
            </h1>
            <span v-if="doc" class="text-xs rounded-full px-2 py-0.5" :class="STATUS_CLASS[doc.status]">
              {{ doc.status_label }}
            </span>
            <span v-if="doc?.is_expired" class="text-xs rounded-full px-2 py-0.5 bg-amber-100 text-amber-700">منقضی</span>
            <span v-if="doc?.invoicing_state" class="text-xs rounded-full px-2 py-0.5" :class="INVOICING_LABEL[doc.invoicing_state].cls">
              {{ INVOICING_LABEL[doc.invoicing_state].label }}
            </span>
            <span v-if="doc?.kind === 'return'" class="text-xs rounded-full px-2 py-0.5 bg-slate-100 text-slate-600">
              {{ doc.return_type === "goods" ? "مرجوعی کالا" : "کسر تحویل‌نشده" }}
            </span>
            <span v-if="doc?.delivery_state" class="text-xs rounded-full px-2 py-0.5 bg-violet-100 text-violet-700">
              {{ deliveryLabel[doc.delivery_state] }}
            </span>
            <span
              v-if="doc?.settlement_state"
              class="text-xs rounded-full px-2 py-0.5"
              :class="doc.settlement_state.is_settled ? 'bg-emerald-100 text-emerald-700' : 'bg-orange-100 text-orange-700'"
            >
              {{ doc.settlement_state.is_settled ? "تسویه شده" : `مانده ${fa(doc.settlement_state.remaining_rial)} ریال` }}
            </span>
          </div>
          <p v-if="doc?.source_number" class="text-xs text-slate-400 mt-1">
            از سند
            <router-link
              class="text-sky-600 ltr-nums"
              :to="{ name: 'sales2-document', params: { id: doc.source }, query: { kind: kind === 'return' ? 'invoice' : 'proforma' } }"
            >{{ doc.source_number }}</router-link>
          </p>
        </div>

        <div class="flex flex-wrap gap-2">
          <template v-if="isDraft">
            <button class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-600" :disabled="saving" @click="save()">ذخیره پیش‌نویس</button>
            <button class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-600" :disabled="saving" @click="runCheck">بررسی</button>
            <button class="rounded-xl px-4 py-2 text-sm bg-panel text-white" :disabled="saving" @click="issue">صدور</button>
            <button class="rounded-xl px-3 py-2 text-sm text-red-500 hover:bg-red-50" @click="removeDraft">حذف</button>
          </template>
          <template v-else-if="doc">
            <button class="rounded-xl px-3 py-2 text-sm bg-panel text-white" @click="printDoc">چاپ</button>
            <template v-if="doc.kind === 'proforma' && canConvert">
              <button class="rounded-xl px-3 py-2 text-sm bg-sky-600 text-white" @click="convert">
                {{ doc.invoicing_state === "partial" ? "فاکتور مانده" : "تبدیل به فاکتور" }}
              </button>
              <button class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-600" @click="closeRemainder">بستن مانده</button>
            </template>
            <template v-if="doc.kind === 'invoice' && doc.status === 'issued'">
              <router-link
                :to="{ name: 'sales2-deliveries', query: { invoice: doc.id } }"
                class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-600"
              >حواله خروج</router-link>
              <router-link
                :to="{ name: 'sales2-receipts', query: { customer: doc.customer, new: 1 } }"
                class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-600"
              >ثبت دریافت</router-link>
              <button v-if="canReturnGoods" class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-600" @click="makeReturn('goods')">مرجوعی کالا</button>
              <button v-if="canReduce" class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-600" @click="makeReturn('undelivered')">کسر تحویل‌نشده</button>
            </template>
            <button v-if="doc.kind !== 'return'" class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-600" @click="duplicate">کپی</button>
            <button
              v-if="doc.status === 'issued' && !(doc.kind === 'proforma' && doc.invoicing_state !== 'open')"
              class="rounded-xl px-3 py-2 text-sm text-red-500 hover:bg-red-50" @click="cancelDoc"
            >ابطال</button>
          </template>
        </div>
      </div>

      <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line">{{ error }}</p>

      <div
        v-if="doc?.status === 'cancelled'"
        class="bg-red-50 text-red-700 text-sm rounded-xl px-3 py-2"
      >ابطال شده در {{ faDateTime(doc.cancelled_at) }} — {{ doc.cancel_reason }}</div>
      <div
        v-if="doc?.override_reason"
        class="bg-amber-50 text-amber-800 text-sm rounded-xl px-3 py-2"
      >صادر شده با عبور از کنترل — دلیل: {{ doc.override_reason }}</div>

      <!-- Checks -->
      <div v-if="checks && checks.length" class="bg-surface rounded-card shadow-soft p-4 space-y-2">
        <h2 class="text-sm font-bold text-ink">{{ isDraft ? "نتیجه‌ی بررسی" : "کنترل‌ها هنگام صدور" }}</h2>
        <p
          v-for="(c, i) in checks" :key="i"
          class="text-sm border rounded-xl px-3 py-2" :class="levelClass[c.level]"
        ><b class="text-xs ml-1">{{ levelLabel[c.level] }}</b> {{ c.message }}</p>
      </div>

      <div class="grid lg:grid-cols-3 gap-4">
        <!-- Document header -->
        <div class="bg-surface rounded-card shadow-soft p-4 lg:col-span-2 grid sm:grid-cols-2 gap-3">
          <div class="sm:col-span-2">
            <label class="text-xs text-slate-500 mb-1 block">مشتری *</label>
            <CustomerSearch
              v-model="form.customer" :label="form.customerLabel"
              :disabled="!isDraft || !!doc?.source"
              @picked="(c) => (form.customerLabel = c?.name_fa ?? '')"
            />
            <p v-if="doc && !isDraft" class="text-xs text-slate-400 mt-1 ltr-nums">
              {{ [doc.customer_national_id && `شناسه ملی ${doc.customer_national_id}`, doc.customer_economic_code && `کد اقتصادی ${doc.customer_economic_code}`, doc.customer_phone].filter(Boolean).join(" · ") }}
            </p>
          </div>
          <div>
            <label class="text-xs text-slate-500 mb-1 block">تاریخ سند</label>
            <JalaliDateField v-model="form.doc_date" :disabled="!isDraft" :clearable="false" />
          </div>
          <div v-if="kind === 'proforma'">
            <label class="text-xs text-slate-500 mb-1 block">اعتبار تا</label>
            <JalaliDateField v-model="form.valid_until" :disabled="!isDraft" placeholder="طبق تنظیمات" />
          </div>
          <div v-if="kind === 'invoice'">
            <label class="text-xs text-slate-500 mb-1 block">سررسید پرداخت</label>
            <JalaliDateField v-model="form.due_date" :disabled="!isDraft" placeholder="طبق اعتبار مشتری" />
          </div>
          <div>
            <label class="text-xs text-slate-500 mb-1 block">فروشنده</label>
            <select v-model="form.salesperson" :class="inp" :disabled="!isDraft">
              <option :value="null">—</option>
              <option v-for="s in options?.salespeople" :key="s.id" :value="s.id">{{ s.name }}</option>
            </select>
          </div>
          <div v-if="!isReturn">
            <label class="text-xs text-slate-500 mb-1 block">نوع تسویه</label>
            <select v-model="form.settlement" :class="inp" :disabled="!isDraft">
              <option v-for="s in options?.settlements" :key="s.value" :value="s.value">{{ s.label }}</option>
            </select>
          </div>
          <div>
            <label class="text-xs text-slate-500 mb-1 block">انبار</label>
            <select v-model="form.warehouse" :class="inp" :disabled="!isDraft">
              <option :value="null">—</option>
              <option v-for="w in options?.warehouses" :key="w.id" :value="w.id">{{ w.name_fa }}</option>
            </select>
          </div>
          <div class="flex items-end gap-3">
            <label class="flex items-center gap-2 text-sm text-ink pb-2">
              <input v-model="form.is_official" type="checkbox" class="rounded" :disabled="!isDraft || isReturn" />
              فاکتور رسمی (با ارزش افزوده)
            </label>
            <div v-if="form.is_official" class="w-20">
              <label class="text-xs text-slate-500 mb-1 block">٪ ارزش افزوده</label>
              <input v-model="form.vat_pct" :class="inp" inputmode="decimal" :disabled="!isDraft || isReturn" />
            </div>
          </div>
          <div class="sm:col-span-2">
            <label class="text-xs text-slate-500 mb-1 block">توضیحات</label>
            <textarea v-model="form.note" :class="inp" rows="2" :disabled="!isDraft" />
          </div>
        </div>

        <!-- Customer credit card -->
        <div class="bg-surface rounded-card shadow-soft p-4 space-y-2 text-sm">
          <h2 class="font-bold text-ink">وضعیت حساب مشتری</h2>
          <template v-if="balance">
            <p v-if="balance.on_hold" class="bg-red-50 text-red-600 rounded-xl px-3 py-2">فروش به این مشتری متوقف است.</p>
            <div class="flex justify-between"><span class="text-slate-500">مانده بدهی</span><b class="ltr-nums">{{ fa(balance.balance_rial) }}</b></div>
            <div class="flex justify-between"><span class="text-slate-500">چک‌های وصول‌نشده</span><span class="ltr-nums">{{ fa(balance.cheques_pending_rial) }}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">سقف اعتبار</span><span class="ltr-nums">{{ balance.credit_limit_rial === null ? "تعریف نشده" : fa(balance.credit_limit_rial) }}</span></div>
            <div v-if="balance.available_rial !== null" class="flex justify-between">
              <span class="text-slate-500">اعتبار باقی‌مانده</span>
              <b class="ltr-nums" :class="Number(balance.available_rial) < totals.total ? 'text-red-600' : 'text-emerald-600'">{{ fa(balance.available_rial) }}</b>
            </div>
            <router-link
              v-if="form.customer" :to="{ name: 'sales2-customer', params: { id: form.customer } }"
              class="text-xs text-sky-600 block pt-1"
            >پرونده و صورتحساب مشتری ←</router-link>
          </template>
          <p v-else class="text-slate-400 text-xs">پس از انتخاب مشتری نمایش داده می‌شود.</p>
          <div v-if="doc?.derived?.length" class="pt-2 border-t border-slate-100 space-y-1">
            <p class="text-xs text-slate-500">اسناد بعدی</p>
            <router-link
              v-for="d in doc.derived" :key="d.id"
              :to="{ name: 'sales2-document', params: { id: d.id }, query: { kind: d.kind } }"
              class="block text-xs text-sky-600 ltr-nums"
            >{{ d.kind_label }} {{ d.number || `#${d.id}` }} · {{ d.status_label }}</router-link>
          </div>
        </div>
      </div>

      <!-- Lines -->
      <div class="bg-surface rounded-card shadow-soft overflow-hidden">
        <div class="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
          <h2 class="text-sm font-bold text-ink">ردیف‌ها</h2>
          <span class="text-xs text-slate-400">مبالغ به ریال</span>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[980px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="px-3 py-2 w-8">#</th>
                <th class="text-right font-medium px-2 min-w-[240px]">کالا</th>
                <th class="text-right font-medium px-2 w-24">مقدار</th>
                <th class="text-right font-medium px-2 w-36">فی</th>
                <th class="text-right font-medium px-2 w-20">٪ تخفیف</th>
                <th class="text-right font-medium px-2">مبلغ خالص</th>
                <th class="text-right font-medium px-2">ارزش افزوده</th>
                <th class="text-right font-medium px-2">جمع</th>
                <th class="text-right font-medium px-2">سود ردیف</th>
                <th class="w-8"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(l, i) in lines" :key="l.key" class="border-t border-slate-100 align-top">
                <td class="px-3 py-2 text-slate-400 ltr-nums">{{ i + 1 }}</td>
                <td class="px-2 py-2">
                  <PickerField
                    v-if="isDraft && !isReturn"
                    :model-value="l.product" :options="productOptions"
                    placeholder="انتخاب کالا…" search-placeholder="نام یا کد کالا…"
                    @update:model-value="(v) => onProduct(l, v as number | null)"
                  />
                  <p v-else class="text-ink">{{ l.product_name }}</p>
                  <input
                    v-if="isDraft" v-model="l.description"
                    class="mt-1 w-full bg-transparent text-xs text-slate-500 outline-none border-b border-dashed border-slate-200"
                    placeholder="شرح (اختیاری)"
                  />
                  <p v-else-if="l.description" class="text-xs text-slate-400">{{ l.description }}</p>
                  <div v-if="l.isRoll" class="flex items-center gap-1 mt-1">
                    <template v-if="isDraft && !isReturn">
                      <button
                        v-for="g in [48, 55]" :key="g" type="button"
                        class="text-[11px] rounded-md px-2 py-0.5"
                        :class="l.grammage === g ? 'bg-panel text-white' : 'bg-slate-100 text-slate-500'"
                        @click="l.grammage = g; requote(l)"
                      >{{ g === 48 ? "۴۸" : "۵۵" }} گرم</button>
                    </template>
                    <span v-else-if="l.grammage" class="text-[11px] text-slate-500">{{ l.grammage === 48 ? "۴۸" : "۵۵" }} گرم</span>
                    <span v-if="l.priceSource && isDraft" class="text-[11px]" :class="l.grammage ? 'text-slate-400' : 'text-amber-600'">· {{ l.priceSource }}</span>
                  </div>
                  <p v-if="l.last_sale && isDraft" class="text-[11px] text-slate-400 mt-1">
                    آخرین فروش به این مشتری: {{ fa(l.last_sale.unit_price_rial) }} در {{ faDate(l.last_sale.doc_date) }}
                  </p>
                </td>
                <td class="px-2 py-2">
                  <input v-if="isDraft" v-model="l.quantity" :class="inp" inputmode="decimal" @input="onQuantity(l)" />
                  <span v-else class="ltr-nums">{{ fa(l.quantity) }}</span>
                  <span class="text-xs text-slate-400">{{ l.unit }}</span>
                  <p v-if="!isDraft && doc?.lines[i]?.remaining_qty !== undefined" class="text-[11px] text-slate-400">
                    فاکتورشده {{ fa(doc.lines[i].invoiced_qty) }} · مانده {{ fa(doc.lines[i].remaining_qty) }}
                  </p>
                  <p v-if="!isDraft && doc?.lines[i]?.deliverable_qty !== undefined" class="text-[11px] text-slate-400">
                    تحویل {{ fa(doc.lines[i].delivered_qty) }} · مرجوعی {{ fa(doc.lines[i].returned_qty) }}<template v-if="Number(doc.lines[i].reduced_qty)"> · کسر {{ fa(doc.lines[i].reduced_qty) }}</template>
                  </p>
                </td>
                <td class="px-2 py-2">
                  <MoneyInput v-if="isDraft && !isReturn" v-model="l.unit_price_rial" :class="inp" @input="l.priceTouched = true" />
                  <span v-else class="ltr-nums">{{ fa(l.unit_price_rial) }}</span>
                </td>
                <td class="px-2 py-2">
                  <input v-if="isDraft && !isReturn" v-model="l.discount_pct" :class="inp" inputmode="decimal" />
                  <span v-else class="ltr-nums">{{ fa(l.discount_pct) }}</span>
                </td>
                <td class="px-2 py-2 ltr-nums">{{ fa(calc(l).net) }}</td>
                <td class="px-2 py-2 ltr-nums text-slate-500">{{ fa(calc(l).vat) }}</td>
                <td class="px-2 py-2 ltr-nums font-medium text-ink">{{ fa(calc(l).total) }}</td>
                <td class="px-2 py-2 text-xs">
                  <template v-if="!isReturn">
                    <span v-if="calc(l).noCost" class="text-slate-400">بها نامعلوم</span>
                    <span v-else-if="calc(l).loss" class="text-red-600 font-medium">زیان {{ fa(calc(l).cost - calc(l).net) }}</span>
                    <span v-else class="text-emerald-600 ltr-nums">{{ fa(calc(l).net - calc(l).cost) }}</span>
                    <p v-if="calc(l).belowMin" class="text-amber-600">زیر حداقل قیمت</p>
                  </template>
                </td>
                <td class="px-2 py-2">
                  <button v-if="isDraft" class="text-slate-300 hover:text-red-500" title="حذف ردیف" @click="lines.splice(i, 1)">✕</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="p-3 border-t border-slate-100 flex flex-wrap items-start justify-between gap-4">
          <button
            v-if="isDraft && !isReturn"
            class="text-sm text-sky-600 px-2 py-1"
            @click="lines.push(blankLine())"
          >+ افزودن ردیف</button>
          <span v-else />
          <dl class="text-sm grid grid-cols-2 gap-x-6 gap-y-1 min-w-[280px]">
            <dt class="text-slate-500">جمع کل ردیف‌ها</dt><dd class="ltr-nums text-left">{{ fa(totals.gross) }}</dd>
            <dt class="text-slate-500">تخفیف</dt><dd class="ltr-nums text-left">{{ fa(totals.disc) }}</dd>
            <dt class="text-slate-500">مبلغ خالص</dt><dd class="ltr-nums text-left">{{ fa(totals.net) }}</dd>
            <dt class="text-slate-500">ارزش افزوده</dt><dd class="ltr-nums text-left">{{ fa(totals.vat) }}</dd>
            <dt class="text-ink font-bold">قابل پرداخت</dt><dd class="ltr-nums text-left font-bold text-ink">{{ fa(totals.total) }}</dd>
            <template v-if="!isReturn">
              <dt class="text-slate-500">بهای تمام‌شده</dt><dd class="ltr-nums text-left">{{ fa(totals.cost) }}</dd>
              <dt class="text-slate-500">سود ناخالص</dt>
              <dd class="ltr-nums text-left" :class="totals.net < totals.cost ? 'text-red-600' : 'text-emerald-600'">
                {{ fa(totals.net - totals.cost) }}<span v-if="profitPct !== null" class="text-xs"> ({{ FA.format(profitPct) }}٪)</span>
              </dd>
            </template>
          </dl>
        </div>
      </div>
    </template>
  </div>
</template>
