<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  commercialApi,
  type DeliveryPart,
  type OrderStatus,
  type PurchaseOrder,
  type PurchaseRequest,
  type Quote,
  type Sample,
} from "@/api/commercial";
import { useAuthStore } from "@/stores/auth";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { confirm } from "@/composables/useUi";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import QuoteForm from "@/components/commercial/QuoteForm.vue";
import RequestForm from "@/components/commercial/RequestForm.vue";
import AwardDialog from "@/components/commercial/AwardDialog.vue";
import OrderForm from "@/components/commercial/OrderForm.vue";
import SampleForm from "@/components/commercial/SampleForm.vue";
import SampleVerdictDialog from "@/components/commercial/SampleVerdictDialog.vue";
import OrderAdvanceDialog from "@/components/commercial/OrderAdvanceDialog.vue";
import PartDialog from "@/components/commercial/PartDialog.vue";
import QuickQuoteForm from "@/components/commercial/QuickQuoteForm.vue";
import { REQUEST_STATUS_CLASS } from "@/components/commercial/orderFlow";
import {
  ORDER_STATUS_CLASS, ORDER_STEPS, isLiveOrder, nextOrderStep, orderStepIndex,
} from "@/components/commercial/orderFlow";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * مقایسه استعلام‌ها و انتخاب تامین‌کننده — the page the department actually
 * works on. Every quote sits in one table so the comparison is a glance, and
 * the losers keep their reason instead of disappearing once a winner exists.
 */
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const { exact, unitLabel } = useMoney();

const request = ref<PurchaseRequest | null>(null);
const orders = ref<PurchaseOrder[]>([]);
const samples = ref<Sample[]>([]);
const loading = ref(true);
const error = ref("");

const canEdit = computed(
  () => auth.department === "commercial" || !!auth.me?.is_superuser,
);

const quotes = computed(() => request.value?.quotes ?? []);
const takenSupplierIds = computed(() => quotes.value.map((q) => q.supplier));
const cheapest = computed(() => {
  if (!quotes.value.length) return null;
  // Compared with VAT in: a رسمی price carries ارزش افزوده on top, so the
  // lowest number typed is not always the lowest cost.
  return quotes.value.reduce((a, b) =>
    Number(a.unit_price_with_vat_rial) <= Number(b.unit_price_with_vat_rial) ? a : b,
  );
});
const fastest = computed(() => {
  const withDays = quotes.value.filter((q) => q.delivery_days > 0);
  if (!withDays.length) return null;
  return withDays.reduce((a, b) => (a.delivery_days <= b.delivery_days ? a : b));
});
const winner = computed(() => quotes.value.find((q) => q.is_selected) ?? null);
const liveOrders = computed(() => orders.value.filter((o) => o.status !== "cancelled"));
const cancelled = computed(() => request.value?.status === "cancelled");
/** Once goods are ordered the winner is fixed — the server refuses a change. */
const locked = computed(() => cancelled.value || liveOrders.value.length > 0);

/**
 * The path a request walks. The current step comes from the server's status,
 * which is derived from the quotes and orders, so this bar cannot disagree
 * with what actually happened.
 */
const STEPS = [
  { status: "open", label: "ثبت درخواست" },
  { status: "quoting", label: "استعلام قیمت" },
  { status: "awarded", label: "انتخاب برنده" },
  { status: "ordered", label: "سفارش و پیگیری" },
  { status: "delivered", label: "تحویل" },
];
const stepIndex = computed(() => {
  const i = STEPS.findIndex((s) => s.status === request.value?.status);
  // Delivered is the end of the road: every step done, none still current.
  return request.value?.status === "delivered" ? STEPS.length : i;
});

async function load() {
  loading.value = true;
  try {
    const id = Number(route.params.id);
    [request.value, orders.value, samples.value] = await Promise.all([
      commercialApi.request(id),
      commercialApi.orders({ request: id }),
      commercialApi.samples({ request: id }),
    ]);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await loadMoneySettings(); await load(); });
// The item tabs of a پیش‌فاکتور stay on this page and only change the id.
watch(() => route.params.id, (id) => { if (id) { justSaved.value = null; load(); } });

/**
 * «کالای بعدی همین پیش‌فاکتور». After a new price is saved, the page asks
 * whether the same پیش‌فاکتور has more lines; the answer opens the quick
 * form on the same supplier, adding each line as an item of this group.
 */
const justSaved = ref<Quote | null>(null);
const nextItemFor = ref<number | null>(null);

function onQuoteSaved(quote: Quote) {
  const wasNew = !editingQuote.value;
  afterChange();
  if (wasNew) justSaved.value = quote;
}

function addNextItem(supplierId: number) {
  justSaved.value = null;
  nextItemFor.value = supplierId;
}

/** The group's items, or this request alone once it is about to gain one. */
const groupItems = computed(() => request.value?.group_items ?? []);

const editingQuote = ref<Quote | null>(null);
const showQuote = ref(false);
const showEditRequest = ref(false);
const showAward = ref(false);
const showOrder = ref(false);
/** Which quote the award dialog should open on, when it was opened from a row. */
const preselect = ref<number | null>(null);

function openQuote(quote: Quote | null) {
  editingQuote.value = quote;
  showQuote.value = true;
}

/**
 * «برنده» on a row.
 *
 * It still goes through the award dialog rather than flipping the flag
 * directly, because the losers need their reasons — that file is the point of
 * the module. What the button removes is the step where the user opens a
 * dialog and hunts for the row they were already pointing at.
 */
function awardFrom(quote: Quote | null) {
  preselect.value = quote?.id ?? null;
  showAward.value = true;
}

const advancing = ref<{ order: PurchaseOrder; target: OrderStatus } | null>(null);
const editingOrder = ref<PurchaseOrder | null>(null);

function openOrder(order: PurchaseOrder | null) {
  editingOrder.value = order;
  showOrder.value = true;
}

async function cancelRequest() {
  const ok = await confirm({
    title: "لغو درخواست",
    message: `درخواست ${request.value?.request_no} لغو شود؟ استعلام‌ها و دلیل‌ها می‌مانند.`,
    danger: true,
  });
  if (!ok || !request.value) return;
  try {
    await commercialApi.cancelRequest(request.value.id);
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}

/** Only a cancelled request, and only by whoever raised it (the server agrees). */
const canDelete = computed(() =>
  cancelled.value
  && (request.value?.created_by === auth.me?.id || !!auth.me?.is_superuser),
);

async function deleteRequest() {
  const ok = await confirm({
    title: "حذف کامل درخواست",
    message: `درخواست ${request.value?.request_no} با همه‌ی استعلام‌هایش برای همیشه حذف شود؟`,
    danger: true,
  });
  if (!ok || !request.value) return;
  try {
    await commercialApi.removeRequest(request.value.id);
    router.push({ name: "commercial-requests" });
  } catch (e) {
    error.value = apiError(e);
  }
}

/** پارت ارسال being added (part null) or edited. */
const partDialog = ref<{ order: PurchaseOrder; part: DeliveryPart | null } | null>(null);

async function removePart(id: number) {
  const ok = await confirm({ title: "حذف پارت", message: "این پارت حذف شود؟", danger: true });
  if (!ok) return;
  try {
    await commercialApi.removePart(id);
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}

async function toggleSplit(order: PurchaseOrder) {
  try {
    await commercialApi.saveOrder({ split_delivery: !order.split_delivery }, order.id);
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}

/** The award dialog in «reasons only» mode — after an order the winner is fixed. */
const editingReasons = ref(false);

async function reopenRequest() {
  if (!request.value) return;
  try {
    await commercialApi.reopenRequest(request.value.id);
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}

const showSample = ref(false);
const sampleQuote = ref<Quote | null>(null);
const editingSample = ref<Sample | null>(null);
const decidingSample = ref<Sample | null>(null);

/** Ask this supplier for a sample. The کالا comes from the request. */
function askSample(quote: Quote | null) {
  sampleQuote.value = quote;
  editingSample.value = null;
  showSample.value = true;
}

function editSample(sample: Sample) {
  editingSample.value = sample;
  sampleQuote.value = null;
  showSample.value = true;
}

function afterChange() {
  showQuote.value = false;
  showAward.value = false;
  showOrder.value = false;
  showSample.value = false;
  editingQuote.value = null;
  editingSample.value = null;
  sampleQuote.value = null;
  decidingSample.value = null;
  preselect.value = null;
  advancing.value = null;
  editingOrder.value = null;
  partDialog.value = null;
  editingReasons.value = false;
  load();
}

async function removeQuote(quote: Quote) {
  const ok = await confirm({
    title: "حذف استعلام",
    message: `قیمت «${quote.supplier_name}» حذف شود؟`,
    danger: true,
  });
  if (!ok) return;
  try {
    await commercialApi.removeQuote(quote.id);
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}

/** Difference from the cheapest quote — the number that justifies a choice. */
function overCheapest(quote: Quote): number | null {
  const low = Number(cheapest.value?.unit_price_with_vat_rial ?? 0);
  if (!low) return null;
  const diff = (Number(quote.unit_price_with_vat_rial) - low) / low * 100;
  return diff === 0 ? null : diff;
}

const FA = new Intl.NumberFormat("fa-IR");
</script>

<template>
  <!-- A flex column rather than space-y, so a cancelled order can drop to the
       bottom (order-last) without a second copy of its card template. -->
  <div class="flex flex-col gap-4">
    <div v-if="loading" class="space-y-2">
      <Skeleton class="h-24 rounded-card" />
      <Skeleton class="h-64 rounded-card" />
    </div>

    <template v-else-if="request">
      <!-- Header: what was needed -->
      <div class="bg-surface rounded-card shadow-soft p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="text-xs text-slate-400 ltr-nums">{{ request.request_no }}</p>
            <h2 class="text-lg font-bold text-ink">
              {{ request.material_name }}
              <span class="text-slate-400 font-normal ltr-nums">
                × {{ num(request.quantity) }} {{ request.material_unit }}
              </span>
            </h2>
            <p class="text-xs text-slate-400 mt-1">
              <span v-if="request.requester_unit">{{ request.requester_unit }} · </span>
              درخواست {{ faDate(request.requested_on) }}
              <span v-if="request.needed_by"> · موعد {{ faDate(request.needed_by) }}</span>
            </p>
            <p v-if="request.note" class="text-sm text-slate-500 mt-2">{{ request.note }}</p>
          </div>
          <div class="flex flex-wrap gap-2 shrink-0">
            <button
              class="text-sm text-slate-500 hover:text-ink px-2 py-2"
              @click="router.push({ name: 'commercial-requests' })"
            >← بازگشت</button>
            <button
              v-if="canEdit"
              class="border border-slate-200 text-ink rounded-xl px-4 py-2 text-sm"
              @click="showEditRequest = true"
            >ویرایش درخواست</button>
            <button
              v-if="canEdit && !cancelled && !liveOrders.length"
              class="text-sm text-slate-400 hover:text-red-500 px-2 py-2"
              @click="cancelRequest"
            >لغو درخواست</button>
          </div>
        </div>

        <!-- Where the request stands, and the one thing left to do on it -->
        <div
          v-if="cancelled"
          class="mt-4 bg-slate-100 rounded-xl px-3 py-2.5 flex flex-wrap items-center justify-between gap-2"
        >
          <span class="text-sm text-slate-500">این درخواست لغو شده است.</span>
          <div class="flex flex-wrap gap-2">
            <button
              v-if="canEdit"
              class="border border-slate-200 bg-surface text-ink rounded-xl px-4 py-2 text-sm"
              @click="reopenRequest"
            >بازگشایی درخواست</button>
            <button
              v-if="canDelete"
              class="bg-red-50 text-red-600 hover:bg-red-100 rounded-xl px-4 py-2 text-sm"
              @click="deleteRequest"
            >حذف کامل</button>
          </div>
        </div>
        <template v-else>
          <!-- Phone: five chips do not fit, so the current step by name and a bar -->
          <div class="sm:hidden mt-4">
            <p class="text-xs text-slate-500">
              مرحله {{ FA.format(Math.min(stepIndex + 1, STEPS.length)) }} از {{ FA.format(STEPS.length) }}:
              <span class="text-ink font-medium">
                {{ STEPS[Math.min(stepIndex, STEPS.length - 1)]?.label }}
              </span>
            </p>
            <div class="mt-1.5 grid grid-cols-5 gap-1">
              <div
                v-for="(step, i) in STEPS" :key="step.status"
                class="h-1.5 rounded-full"
                :class="i < stepIndex ? 'bg-emerald-500' : i === stepIndex ? 'bg-panel' : 'bg-slate-200'"
              />
            </div>
          </div>
          <ol class="hidden sm:flex mt-4 items-center gap-1 overflow-x-auto pb-1">
            <li
              v-for="(step, i) in STEPS" :key="step.status"
              class="flex items-center gap-1 shrink-0"
            >
              <span
                class="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs"
                :class="i < stepIndex
                  ? 'bg-emerald-50 text-emerald-700'
                  : i === stepIndex
                    ? 'bg-panel text-white'
                    : 'bg-slate-50 text-slate-400'"
              >
                <span>{{ i < stepIndex ? "✔" : FA.format(i + 1) }}</span>
                {{ step.label }}
              </span>
              <span v-if="i < STEPS.length - 1" class="w-4 h-px bg-slate-200" />
            </li>
          </ol>
          <!-- The guidance and the button that acts on it, in one place -->
          <div
            v-if="request.next_step"
            class="mt-3 bg-slate-50 rounded-xl px-3 py-2.5 flex flex-wrap items-center justify-between gap-3"
          >
            <p class="text-sm">
              <span class="text-slate-400">قدم بعد:&nbsp;</span>
              <span class="text-ink font-medium">{{ request.next_step }}</span>
            </p>
            <!-- The primary action first, so on a phone it is the one on top -->
            <div v-if="canEdit && !locked" class="flex flex-wrap gap-2">
              <button
                v-if="winner"
                class="bg-emerald-600 text-white rounded-xl px-4 py-2 text-sm"
                @click="openOrder(null)"
              >ثبت سفارش خرید</button>
              <button
                v-if="quotes.length"
                class="rounded-xl px-4 py-2 text-sm"
                :class="winner ? 'border border-slate-200 bg-surface text-ink' : 'bg-panel text-white'"
                @click="awardFrom(null)"
              >{{ winner ? "تغییر برنده" : "انتخاب تامین‌کننده" }}</button>
              <button
                class="rounded-xl px-4 py-2 text-sm"
                :class="quotes.length ? 'border border-slate-200 bg-surface text-ink' : 'bg-panel text-white'"
                @click="openQuote(null)"
              >+ استعلام</button>
            </div>
          </div>
        </template>

        <!-- اقلام این پیش‌فاکتور: one tab per item, each with where it stands -->
        <div v-if="groupItems.length" class="mt-4 border-t border-slate-100 pt-3">
          <p class="text-xs text-slate-400 mb-2">
            اقلام این پیش‌فاکتور ({{ FA.format(groupItems.length) }} قلم)
          </p>
          <div class="flex gap-2 overflow-x-auto pb-1">
            <button
              v-for="(item, i) in groupItems" :key="item.id"
              class="shrink-0 text-right rounded-xl border px-3 py-2 transition-colors min-w-[9rem]"
              :class="item.id === request.id
                ? 'border-panel bg-panel/5'
                : 'border-slate-200 hover:bg-slate-50'"
              @click="item.id !== request.id && router.push({ name: 'commercial-request', params: { id: item.id } })"
            >
              <span class="block text-xs text-slate-400">قلم {{ FA.format(i + 1) }}</span>
              <span class="block text-sm text-ink font-medium truncate max-w-[12rem]">
                {{ item.material_name }}
              </span>
              <span class="flex items-center gap-1.5 mt-1">
                <span class="text-xs text-slate-500 ltr-nums">
                  {{ num(item.quantity) }} {{ item.material_unit }}
                </span>
                <span
                  class="text-[11px] rounded-full px-1.5 py-0.5"
                  :class="REQUEST_STATUS_CLASS[item.status]"
                >{{ item.status_label }}</span>
              </span>
            </button>
          </div>
        </div>
      </div>

      <!-- Just saved a price: does this پیش‌فاکتور have more lines? -->
      <div
        v-if="justSaved && canEdit"
        class="bg-emerald-50 border border-emerald-200 rounded-card p-4 flex flex-wrap items-center justify-between gap-3"
      >
        <div>
          <p class="text-sm font-medium text-emerald-800">
            ✓ قیمت «{{ justSaved.supplier_name }}» ثبت شد
          </p>
          <p class="text-xs text-emerald-700/80 mt-0.5">
            این پیش‌فاکتور کالای دیگری هم دارد؟ هر قلم جدا ثبت و مقایسه می‌شود.
          </p>
        </div>
        <div class="flex gap-2">
          <button
            class="bg-emerald-600 text-white rounded-xl px-4 py-2 text-sm"
            @click="addNextItem(justSaved.supplier)"
          >+ کالای بعدی همین پیش‌فاکتور</button>
          <button
            class="text-sm text-emerald-700 px-3 py-2"
            @click="justSaved = null"
          >نه، تمام شد</button>
        </div>
      </div>

      <p
        v-if="error"
        class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line"
      >{{ error }}</p>

      <!-- Orders come first once there are any: after the award, following
           the order is the work, and the quotes are only the record of why. -->
      <div
        v-for="o in orders" :key="o.id"
        class="bg-surface rounded-card shadow-soft p-4"
        :class="o.status === 'cancelled' ? 'opacity-60 order-last' : ''"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="text-xs text-slate-400">
              سفارش خرید <span class="ltr-nums">{{ o.order_no }}</span>
              · {{ faDate(o.ordered_on) }}
            </p>
            <p class="font-bold text-ink mt-0.5">
              {{ o.supplier_name }}
              <span class="font-normal text-slate-400 ltr-nums">
                · {{ num(o.quantity) }} {{ o.material_unit }}
              </span>
            </p>
            <p class="text-sm text-ink ltr-nums mt-0.5">
              {{ exact(o.grand_total_rial, true) }}
              <span v-if="o.is_official" class="text-xs text-slate-400">با ارزش افزوده</span>
            </p>
          </div>
          <span
            class="text-xs rounded-full px-2.5 py-1 shrink-0"
            :class="ORDER_STATUS_CLASS[o.status]"
          >{{ o.status_label }}</span>
        </div>

        <!-- Where the order is on its way -->
        <ol v-if="o.status !== 'cancelled'" class="mt-4 grid grid-cols-5 gap-1.5">
          <li v-for="(s, i) in ORDER_STEPS" :key="s.status">
            <div
              class="h-1.5 rounded-full"
              :class="i <= orderStepIndex(o.status) ? 'bg-emerald-500' : 'bg-slate-200'"
            />
            <!-- On a phone only the current step is named; five labels in
                 375px would each be cut to two letters. -->
            <p
              class="text-xs mt-1.5 truncate"
              :class="[
                i === orderStepIndex(o.status)
                  ? 'text-ink font-medium'
                  : i < orderStepIndex(o.status) ? 'text-emerald-700' : 'text-slate-400',
                i === orderStepIndex(o.status) ? '' : 'hidden sm:block',
              ]"
            >{{ s.label }}</p>
          </li>
        </ol>
        <p v-if="o.delivered_on" class="text-xs text-slate-500 mt-2">
          تحویل {{ faDate(o.delivered_on) }}
          <span v-if="o.delivery_days !== null">— {{ num(o.delivery_days) }} روز پس از سفارش</span>
        </p>
        <p v-if="o.delivery_terms || o.payment_method_label" class="text-xs text-slate-400 mt-1">
          {{ [o.delivery_terms, o.payment_term_name, o.payment_method_label].filter(Boolean).join(" · ") }}
        </p>

        <!-- حمل به دفعات: how much has come, what is on its way, what is left -->
        <div v-if="o.split_delivery && o.status !== 'cancelled'" class="mt-4 bg-slate-50 rounded-xl p-3">
          <div class="flex flex-wrap items-baseline justify-between gap-2">
            <p class="text-sm font-medium text-ink">حمل به دفعات</p>
            <p class="text-xs text-slate-500">
              <span class="text-emerald-700">{{ num(o.delivered_qty) }} تحویل</span>
              <template v-if="Number(o.shipped_qty) > Number(o.delivered_qty)">
                · <span class="text-violet-700">{{ num(Number(o.shipped_qty) - Number(o.delivered_qty)) }} در راه</span>
              </template>
              · <span class="text-ink font-medium">{{ num(o.remaining_qty) }} باقی‌مانده</span>
              از {{ num(o.quantity) }} {{ o.material_unit }}
            </p>
          </div>
          <!-- One bar, three shades: delivered, on its way, not yet sent -->
          <div class="mt-2 h-2 rounded-full bg-slate-200 overflow-hidden flex">
            <div
              class="bg-emerald-500 h-full"
              :style="{ width: `${Math.min(Number(o.delivered_qty) / Number(o.quantity || 1) * 100, 100)}%` }"
            />
            <div
              class="bg-violet-400 h-full"
              :style="{ width: `${Math.max(Number(o.shipped_qty) - Number(o.delivered_qty), 0) / Number(o.quantity || 1) * 100}%` }"
            />
          </div>

          <ul v-if="o.parts.length" class="mt-3 divide-y divide-slate-200/70">
            <li
              v-for="(p, i) in o.parts" :key="p.id"
              class="py-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm"
            >
              <span class="text-xs text-slate-400 w-12 shrink-0">پارت {{ num(i + 1) }}</span>
              <span class="text-ink font-medium ltr-nums">{{ num(p.quantity) }} {{ o.material_unit }}</span>
              <span class="text-xs text-slate-500">ارسال {{ faDate(p.shipped_on) }}</span>
              <span
                class="text-xs rounded-full px-2 py-0.5"
                :class="p.delivered_on ? 'bg-emerald-100 text-emerald-700' : 'bg-violet-100 text-violet-700'"
              >{{ p.delivered_on ? `تحویل ${faDate(p.delivered_on)}` : "در راه" }}</span>
              <span v-if="p.note" class="text-xs text-slate-400 truncate max-w-[12rem]">{{ p.note }}</span>
              <span class="flex-1" />
              <template v-if="canEdit">
                <button
                  v-if="!p.delivered_on"
                  class="text-xs bg-emerald-50 text-emerald-700 hover:bg-emerald-100 rounded-lg px-2 py-1"
                  @click="partDialog = { order: o, part: p }"
                >رسید</button>
                <button
                  class="text-xs text-slate-400 hover:text-ink px-1"
                  @click="partDialog = { order: o, part: p }"
                >ویرایش</button>
                <button
                  class="text-xs text-slate-400 hover:text-red-500 px-1"
                  @click="removePart(p.id)"
                >حذف</button>
              </template>
            </li>
          </ul>
          <p v-else class="text-xs text-slate-400 mt-2">هنوز پارتی ارسال نشده.</p>
        </div>

        <div v-if="canEdit" class="mt-4 flex flex-wrap items-center gap-2">
          <template v-if="isLiveOrder(o.status)">
            <!-- A split order ships through its parts, so from production on
                 the main button records the next part instead. -->
            <button
              v-if="o.split_delivery && ['producing', 'shipped'].includes(o.status) && Number(o.shipped_qty) < Number(o.quantity)"
              class="bg-emerald-600 text-white rounded-xl px-4 py-2 text-sm"
              @click="partDialog = { order: o, part: null }"
            >+ ثبت ارسال پارت {{ num(o.parts.length + 1) }}</button>
            <button
              v-else-if="nextOrderStep(o.status) && !(o.split_delivery && ['shipped', 'delivered'].includes(nextOrderStep(o.status)!.status))"
              class="bg-emerald-600 text-white rounded-xl px-4 py-2 text-sm"
              @click="advancing = { order: o, target: nextOrderStep(o.status)!.status }"
            >{{ nextOrderStep(o.status)!.action }}</button>
            <button
              v-if="!o.split_delivery && nextOrderStep(o.status)?.status !== 'delivered'"
              class="border border-slate-200 text-ink rounded-xl px-4 py-2 text-sm"
              title="بدون مرحله‌ی ارسال، مستقیم تحویل شد"
              @click="advancing = { order: o, target: 'delivered' }"
            >مستقیم تحویل شد</button>
            <button
              v-if="o.split_delivery && ['pending', 'buying'].includes(o.status)"
              class="border border-slate-200 text-ink rounded-xl px-4 py-2 text-sm"
              @click="partDialog = { order: o, part: null }"
            >+ ثبت پارت ارسال</button>
            <button
              v-if="!o.parts.length && ['pending', 'buying', 'producing'].includes(o.status)"
              class="text-xs text-slate-500 hover:text-ink px-2 py-1"
              @click="toggleSplit(o)"
            >{{ o.split_delivery ? "حمل یکجا" : "حمل به دفعات" }}</button>
          </template>
          <span class="flex-1" />
          <button
            class="text-xs text-slate-400 hover:text-ink px-2 py-1"
            @click="openOrder(o)"
          >ویرایش سفارش</button>
          <button
            v-if="isLiveOrder(o.status)"
            class="text-xs text-slate-400 hover:text-red-500 px-2 py-1"
            @click="advancing = { order: o, target: 'cancelled' }"
          >لغو سفارش</button>
        </div>
      </div>

      <!-- The comparison table -->
      <div class="bg-surface rounded-card shadow-soft overflow-hidden">
        <div class="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
          <h3 class="font-bold text-ink text-sm">
            استعلام قیمت
            <span class="text-slate-400 font-normal">({{ num(quotes.length) }} تامین‌کننده)</span>
          </h3>
          <span class="text-xs text-slate-400">مبالغ به {{ unitLabel }}</span>
        </div>

        <EmptyState
          v-if="!quotes.length"
          title="هنوز قیمتی ثبت نشده"
          hint="از چند تامین‌کننده قیمت بگیرید تا بشود مقایسه کرد."
        />

        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm min-w-[880px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">تامین‌کننده</th>
                <th class="text-right font-medium px-3">قیمت واحد</th>
                <th class="text-right font-medium px-3">اختلاف با کمترین</th>
                <th class="text-right font-medium px-3">مبلغ کل</th>
                <th class="text-right font-medium px-3">تحویل</th>
                <th class="text-right font-medium px-3">شرایط پرداخت</th>
                <th class="text-right font-medium px-3">نمونه</th>
                <th class="text-right font-medium px-3">نتیجه</th>
                <th class="px-4"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="q in quotes" :key="q.id"
                class="border-t border-slate-100"
                :class="q.is_selected ? 'bg-emerald-50/60' : 'hover:bg-slate-50'"
              >
                <td class="px-4 py-2.5">
                  <p class="text-ink font-medium">
                    {{ q.supplier_name }}
                    <span v-if="q.is_selected" class="text-emerald-600 text-xs">✔ برنده</span>
                  </p>
                  <p v-if="q.note" class="text-xs text-slate-400">{{ q.note }}</p>
                </td>
                <td class="px-3 ltr-nums text-ink">
                  {{ exact(q.unit_price_rial) }}
                  <span
                    v-if="cheapest && q.id === cheapest.id"
                    class="text-xs text-emerald-600"
                  >کمترین</span>
                  <p class="text-xs" :class="q.is_official ? 'text-sky-600' : 'text-slate-400'">
                    <template v-if="q.is_official">
                      رسمی · با ارزش افزوده {{ exact(q.unit_price_with_vat_rial) }}
                    </template>
                    <template v-else>غیررسمی</template>
                  </p>
                </td>
                <td class="px-3 ltr-nums text-xs">
                  <span v-if="overCheapest(q) === null" class="text-slate-300">—</span>
                  <span v-else class="text-amber-600">
                    +{{ FA.format(Number(overCheapest(q)!.toFixed(1))) }}٪
                  </span>
                </td>
                <td class="px-3 ltr-nums text-slate-500">
                  {{ exact(q.grand_total_rial) }}
                  <p v-if="q.is_official" class="text-xs text-slate-400">
                    شامل {{ exact(q.vat_rial) }} ارزش افزوده
                  </p>
                </td>
                <td class="px-3 ltr-nums text-slate-500">
                  {{ num(q.delivery_days) }} روز
                  <span
                    v-if="fastest && q.id === fastest.id"
                    class="text-xs text-sky-600"
                  >سریع‌ترین</span>
                  <p v-if="q.validity_days" class="text-xs text-slate-400">
                    اعتبار {{ num(q.validity_days) }} روز
                  </p>
                </td>
                <td class="px-3 text-xs">
                  <span :class="q.payment_term_name ? 'text-ink' : 'text-slate-300'">
                    {{ q.payment_term_name || "ثبت نشده" }}
                  </span>
                  <p v-if="q.payment_method_label" class="text-slate-400">
                    {{ q.payment_method_label }}
                  </p>
                  <p v-if="q.payment_note" class="text-slate-400">{{ q.payment_note }}</p>
                </td>
                <td class="px-3">
                  <button
                    v-if="q.sample_status"
                    class="text-xs rounded-full px-2 py-0.5"
                    :class="q.sample_status.is_approved
                      ? 'bg-emerald-100 text-emerald-700'
                      : q.sample_status.status === 'rejected'
                        ? 'bg-red-50 text-red-500'
                        : 'bg-amber-50 text-amber-700'"
                    :title="`${q.sample_status.sample_no} — برای دیدن پرونده نمونه‌ها`"
                    @click="router.push({ name: 'commercial-samples' })"
                  >{{ q.sample_status.status_label }}</button>
                  <button
                    v-else-if="canEdit"
                    class="text-xs text-slate-400 hover:text-ink"
                    @click="askSample(q)"
                  >+ نمونه بخواهید</button>
                  <span v-else class="text-xs text-slate-300">—</span>
                </td>
                <td class="px-3">
                  <div v-if="q.reason_names?.length" class="flex flex-wrap gap-1">
                    <span
                      v-for="name in q.reason_names" :key="name"
                      class="text-xs rounded-full px-2 py-0.5 whitespace-nowrap"
                      :class="q.reason_kind === 'win'
                        ? 'bg-emerald-100 text-emerald-700'
                        : 'bg-red-50 text-red-500'"
                    >{{ name }}</span>
                  </div>
                  <span v-else class="text-xs text-slate-300">—</span>
                  <button
                    v-if="canEdit && q.is_selected && locked && !cancelled"
                    class="block text-xs text-slate-400 hover:text-ink mt-1"
                    @click="editingReasons = true"
                  >{{ q.reason_names?.length ? "ویرایش دلیل‌ها" : "+ دلیل انتخاب" }}</button>
                  <p v-if="q.decision_note" class="text-xs text-slate-400 mt-0.5">
                    {{ q.decision_note }}
                  </p>
                </td>
                <td class="px-4 text-left whitespace-nowrap">
                  <button
                    v-if="canEdit && !q.is_selected && !locked"
                    class="text-xs bg-emerald-50 text-emerald-700 hover:bg-emerald-100 rounded-lg px-2 py-1 ml-1"
                    :title="`${q.supplier_name} برنده این استعلام شود`"
                    @click="awardFrom(q)"
                  >برنده</button>
                  <button
                    v-if="canEdit && !cancelled"
                    class="text-xs text-slate-400 hover:text-emerald-700 px-1.5"
                    :title="`کالای دیگری از پیش‌فاکتور ${q.supplier_name}`"
                    @click="addNextItem(q.supplier)"
                  >+ قلم بعدی</button>
                  <button
                    v-if="canEdit"
                    class="text-xs text-slate-400 hover:text-ink px-1.5"
                    @click="openQuote(q)"
                  >ویرایش</button>
                  <button
                    v-if="canEdit && !q.is_selected"
                    class="text-xs text-slate-400 hover:text-red-500 px-1.5"
                    @click="removeQuote(q)"
                  >حذف</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Samples: what arrived before anyone committed to buying -->
      <!-- Only while it can still matter: once goods are ordered an empty
           «نمونه‌ها» box is a screenful of nothing between the user and the page. -->
      <div
        v-if="samples.length || (canEdit && !locked)"
        class="bg-surface rounded-card shadow-soft overflow-hidden"
      >
        <div class="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
          <h3 class="font-bold text-ink text-sm">
            نمونه‌ها
            <span v-if="samples.length" class="text-slate-400 font-normal">
              ({{ num(samples.length) }})
            </span>
          </h3>
          <button
            v-if="canEdit"
            class="text-xs text-slate-500 hover:text-ink"
            @click="askSample(null)"
          >+ درخواست نمونه</button>
        </div>

        <p v-if="!samples.length" class="px-4 py-3 text-xs text-slate-400">
          نمونه‌ای ثبت نشده. پیش از خرید از تامین‌کننده‌ی بی‌سابقه، نمونه بخواهید.
        </p>

        <table v-else class="w-full text-sm">
          <tbody>
            <tr v-for="s in samples" :key="s.id" class="border-t border-slate-100">
              <td class="px-4 py-2.5 ltr-nums text-ink font-medium">{{ s.sample_no }}</td>
              <td class="px-3 text-slate-600">{{ s.supplier_name }}</td>
              <td class="px-3 text-xs text-slate-500">{{ s.spec || "—" }}</td>
              <td class="px-3 whitespace-nowrap">
                <span
                  class="text-xs rounded-full px-2 py-0.5"
                  :class="s.is_approved
                    ? 'bg-emerald-100 text-emerald-700'
                    : s.status === 'rejected'
                      ? 'bg-red-50 text-red-500'
                      : 'bg-amber-50 text-amber-700'"
                >{{ s.status_label }}</span>
                <span v-if="s.reason_name" class="text-xs text-red-500 mr-1">
                  {{ s.reason_name }}
                </span>
                <span
                  v-else-if="s.waiting_days !== null"
                  class="text-xs text-slate-400 mr-1"
                >{{ num(s.waiting_days) }} روز در انتظار</span>
              </td>
              <td class="px-4 text-left whitespace-nowrap">
                <button
                  v-if="canEdit"
                  class="text-xs rounded-lg px-2 py-1 ml-1"
                  :class="s.waiting_days !== null
                    ? 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                    : 'text-slate-400 hover:text-ink'"
                  @click="decidingSample = s"
                >{{ s.waiting_days !== null ? "ثبت نتیجه" : "تغییر نتیجه" }}</button>
                <button
                  v-if="canEdit"
                  class="text-xs text-slate-400 hover:text-ink px-1.5"
                  @click="editSample(s)"
                >ویرایش</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <RequestForm
        v-if="showEditRequest" :request="request"
        @close="showEditRequest = false" @saved="showEditRequest = false; load()"
      />
      <QuoteForm
        v-if="showQuote"
        :request="request" :quote="editingQuote"
        :taken-supplier-ids="takenSupplierIds"
        @close="showQuote = false" @saved="onQuoteSaved"
      />
      <QuickQuoteForm
        v-if="nextItemFor"
        :supplier-id="nextItemFor" :group="request.id"
        @close="nextItemFor = null; load()" @added="load()" @saved="nextItemFor = null; load()"
      />
      <AwardDialog
        v-if="showAward"
        :request="request" :quotes="quotes" :preselect="preselect"
        @close="showAward = false" @saved="afterChange"
      />
      <AwardDialog
        v-if="editingReasons"
        :request="request" :quotes="quotes" reasons-only
        @close="editingReasons = false" @saved="afterChange"
      />
      <PartDialog
        v-if="partDialog"
        :order="partDialog.order" :part="partDialog.part"
        @close="partDialog = null" @saved="afterChange"
      />
      <OrderForm
        v-if="showOrder"
        :order="editingOrder" :request="request" :quote="winner"
        @close="showOrder = false" @saved="afterChange"
      />
      <OrderAdvanceDialog
        v-if="advancing"
        :order="advancing.order" :target="advancing.target"
        @close="advancing = null" @saved="afterChange"
      />
      <SampleForm
        v-if="showSample"
        :request="request" :quote="sampleQuote" :sample="editingSample"
        @close="showSample = false" @saved="afterChange"
      />
      <SampleVerdictDialog
        v-if="decidingSample"
        :sample="decidingSample"
        @close="decidingSample = null" @saved="afterChange"
      />
    </template>

    <EmptyState v-else title="درخواست پیدا نشد" />
  </div>
</template>
