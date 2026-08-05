<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  commercialApi,
  type PurchaseOrder,
  type PurchaseRequest,
  type Quote,
} from "@/api/commercial";
import { useAuthStore } from "@/stores/auth";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { confirm } from "@/composables/useUi";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import QuoteForm from "@/components/commercial/QuoteForm.vue";
import AwardDialog from "@/components/commercial/AwardDialog.vue";
import OrderForm from "@/components/commercial/OrderForm.vue";
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
const loading = ref(true);
const error = ref("");

const canEdit = computed(
  () => auth.department === "commercial" || !!auth.me?.is_superuser,
);

const quotes = computed(() => request.value?.quotes ?? []);
const takenSupplierIds = computed(() => quotes.value.map((q) => q.supplier));
const cheapest = computed(() => {
  if (!quotes.value.length) return null;
  return quotes.value.reduce((a, b) =>
    Number(a.unit_price_rial) <= Number(b.unit_price_rial) ? a : b,
  );
});
const fastest = computed(() => {
  const withDays = quotes.value.filter((q) => q.delivery_days > 0);
  if (!withDays.length) return null;
  return withDays.reduce((a, b) => (a.delivery_days <= b.delivery_days ? a : b));
});
const winner = computed(() => quotes.value.find((q) => q.is_selected) ?? null);

async function load() {
  loading.value = true;
  try {
    const id = Number(route.params.id);
    [request.value, orders.value] = await Promise.all([
      commercialApi.request(id),
      commercialApi.orders({ request: id }),
    ]);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await loadMoneySettings(); await load(); });

const editingQuote = ref<Quote | null>(null);
const showQuote = ref(false);
const showAward = ref(false);
const showOrder = ref(false);

function openQuote(quote: Quote | null) {
  editingQuote.value = quote;
  showQuote.value = true;
}

function afterChange() {
  showQuote.value = false;
  showAward.value = false;
  showOrder.value = false;
  editingQuote.value = null;
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
  const low = Number(cheapest.value?.unit_price_rial ?? 0);
  if (!low) return null;
  const diff = (Number(quote.unit_price_rial) - low) / low * 100;
  return diff === 0 ? null : diff;
}

const FA = new Intl.NumberFormat("fa-IR");
</script>

<template>
  <div class="space-y-4">
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
              v-if="canEdit && request.status !== 'cancelled'"
              class="bg-slate-100 text-ink rounded-xl px-4 py-2 text-sm"
              @click="openQuote(null)"
            >+ استعلام</button>
            <button
              v-if="canEdit && quotes.length"
              class="bg-panel text-white rounded-xl px-4 py-2 text-sm"
              @click="showAward = true"
            >{{ winner ? "تغییر انتخاب" : "انتخاب تامین‌کننده" }}</button>
            <button
              v-if="canEdit && winner"
              class="bg-emerald-600 text-white rounded-xl px-4 py-2 text-sm"
              @click="showOrder = true"
            >ثبت سفارش خرید</button>
          </div>
        </div>
      </div>

      <p
        v-if="error"
        class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line"
      >{{ error }}</p>

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
                <th class="text-right font-medium px-3">اعتبار</th>
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
                    <span v-if="q.is_selected" class="text-emerald-600 text-xs">✔ خرید شد</span>
                  </p>
                  <p v-if="q.note" class="text-xs text-slate-400">{{ q.note }}</p>
                </td>
                <td class="px-3 ltr-nums text-ink">
                  {{ exact(q.unit_price_rial) }}
                  <span
                    v-if="cheapest && q.id === cheapest.id"
                    class="text-xs text-emerald-600"
                  >کمترین</span>
                </td>
                <td class="px-3 ltr-nums text-xs">
                  <span v-if="overCheapest(q) === null" class="text-slate-300">—</span>
                  <span v-else class="text-amber-600">
                    +{{ FA.format(Number(overCheapest(q)!.toFixed(1))) }}٪
                  </span>
                </td>
                <td class="px-3 ltr-nums text-slate-500">{{ exact(q.total_rial) }}</td>
                <td class="px-3 ltr-nums text-slate-500">
                  {{ num(q.delivery_days) }} روز
                  <span
                    v-if="fastest && q.id === fastest.id"
                    class="text-xs text-sky-600"
                  >سریع‌ترین</span>
                </td>
                <td class="px-3 ltr-nums text-slate-500">{{ num(q.validity_days) }} روز</td>
                <td class="px-3">
                  <span
                    v-if="q.reason_name"
                    class="text-xs rounded-full px-2 py-0.5"
                    :class="q.reason_kind === 'win'
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'bg-red-50 text-red-500'"
                  >{{ q.reason_name }}</span>
                  <span v-else class="text-xs text-slate-300">—</span>
                  <p v-if="q.decision_note" class="text-xs text-slate-400 mt-0.5">
                    {{ q.decision_note }}
                  </p>
                </td>
                <td class="px-4 text-left whitespace-nowrap">
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

      <!-- Orders raised from this request -->
      <div v-if="orders.length" class="bg-surface rounded-card shadow-soft overflow-hidden">
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          سفارش‌های خرید
        </h3>
        <table class="w-full text-sm">
          <tbody>
            <tr v-for="o in orders" :key="o.id" class="border-t border-slate-100">
              <td class="px-4 py-2.5 ltr-nums text-ink font-medium">{{ o.order_no }}</td>
              <td class="px-3 text-slate-500">{{ o.supplier_name }}</td>
              <td class="px-3 ltr-nums text-slate-500">
                {{ num(o.quantity) }} {{ o.material_unit }}
              </td>
              <td class="px-3 ltr-nums text-ink">{{ exact(o.total_rial, true) }}</td>
              <td class="px-4 text-xs text-slate-500">{{ o.status_label }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <QuoteForm
        v-if="showQuote"
        :request="request" :quote="editingQuote"
        :taken-supplier-ids="takenSupplierIds"
        @close="showQuote = false" @saved="afterChange"
      />
      <AwardDialog
        v-if="showAward"
        :request="request" :quotes="quotes"
        @close="showAward = false" @saved="afterChange"
      />
      <OrderForm
        v-if="showOrder"
        :request="request" :quote="winner"
        @close="showOrder = false" @saved="afterChange"
      />
    </template>

    <EmptyState v-else title="درخواست پیدا نشد" />
  </div>
</template>
