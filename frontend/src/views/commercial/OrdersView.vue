<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { commercialApi, type PurchaseOrder } from "@/api/commercial";
import { useAuthStore } from "@/stores/auth";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { confirm } from "@/composables/useUi";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import OrderForm from "@/components/commercial/OrderForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/** سفارش‌های خرید. */
const auth = useAuthStore();
const { exact, unitLabel } = useMoney();

const rows = ref<PurchaseOrder[]>([]);
const loading = ref(true);
const error = ref("");
const search = ref("");
const status = ref("");

const canEdit = computed(
  () => auth.department === "commercial" || !!auth.me?.is_superuser,
);

const STATUS_CLASS: Record<string, string> = {
  pending: "bg-sky-100 text-sky-700",
  buying: "bg-amber-100 text-amber-700",
  shipped: "bg-violet-100 text-violet-700",
  delivered: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-slate-100 text-slate-500",
};

const filtered = computed(() => {
  const q = search.value.trim();
  return rows.value.filter((o) => {
    if (status.value && o.status !== status.value) return false;
    if (q && !`${o.order_no} ${o.material_name} ${o.supplier_name} ${o.note}`.includes(q))
      return false;
    return true;
  });
});

/** Cancelled orders bought nothing, so the header total leaves them out. */
const total = computed(() =>
  filtered.value
    .filter((o) => o.status !== "cancelled")
    .reduce((sum, o) => sum + Number(o.total_rial), 0),
);

async function load() {
  loading.value = true;
  try {
    rows.value = await commercialApi.orders();
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await loadMoneySettings(); await load(); });

const editing = ref<PurchaseOrder | null>(null);
const showForm = ref(false);

function open(order: PurchaseOrder | null) {
  editing.value = order;
  showForm.value = true;
}

function onSaved() {
  showForm.value = false;
  editing.value = null;
  load();
}

async function remove(order: PurchaseOrder) {
  const ok = await confirm({
    title: "حذف سفارش",
    message: `سفارش ${order.order_no} حذف شود؟`,
    danger: true,
  });
  if (!ok) return;
  try {
    await commercialApi.removeOrder(order.id);
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <input
        v-model="search" placeholder="جستجوی شماره، کالا یا تامین‌کننده…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 flex-1 min-w-[200px]"
      />
      <select v-model="status" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
        <option value="">همه وضعیت‌ها</option>
        <option value="pending">در انتظار تایید</option>
        <option value="buying">در حال خرید</option>
        <option value="shipped">ارسال شده</option>
        <option value="delivered">تحویل شد</option>
        <option value="cancelled">لغو شد</option>
      </select>
      <span class="text-xs text-slate-400 px-2">
        {{ num(filtered.length) }} سفارش · جمع
        <span class="ltr-nums">{{ exact(total, true) }}</span>
      </span>
      <button
        v-if="canEdit"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm shrink-0"
        @click="open(null)"
      >+ سفارش خرید</button>
    </div>

    <p
      v-if="error"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line"
    >{{ error }}</p>

    <OrderForm
      v-if="showForm" :order="editing"
      @close="showForm = false" @saved="onSaved"
    />

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 8" :key="i" class="h-12 rounded-xl" />
    </div>

    <EmptyState
      v-else-if="!filtered.length"
      title="سفارشی ثبت نشده"
      hint="بعد از انتخاب تامین‌کننده، سفارش خرید را از صفحه همان درخواست ثبت کنید."
    />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <div class="px-4 py-2 text-xs text-slate-400 border-b border-slate-100">
        مبالغ به {{ unitLabel }}
      </div>
      <!-- A card per order on phones; a nine-column table cannot be narrowed
           to 375px, only dragged sideways. -->
      <ul class="md:hidden divide-y divide-slate-100">
        <li v-for="o in filtered" :key="`m-${o.id}`" class="p-4">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="text-ink font-medium truncate">{{ o.material_name }}</p>
              <p class="text-xs text-slate-400 ltr-nums truncate">
                {{ o.order_no }}<template v-if="o.request_no"> · {{ o.request_no }}</template>
              </p>
            </div>
            <span class="text-xs rounded-full px-2 py-0.5 shrink-0" :class="STATUS_CLASS[o.status]">
              {{ o.status_label }}
            </span>
          </div>

          <p class="text-xs text-slate-500 mt-2 truncate">{{ o.supplier_name }}</p>
          <div class="flex items-baseline gap-3 mt-1 flex-wrap ltr-nums">
            <span class="text-ink font-semibold">{{ exact(o.total_rial) }}</span>
            <span class="text-xs text-slate-400">
              {{ num(o.quantity) }} {{ o.material_unit }} × {{ exact(o.unit_price_rial) }}
            </span>
          </div>
          <div class="flex items-center justify-between gap-2 mt-1.5 text-xs text-slate-400">
            <span class="ltr-nums">{{ faDate(o.ordered_on) }}</span>
            <span v-if="o.delivery_days !== null">تحویل در {{ num(o.delivery_days) }} روز</span>
          </div>

          <div v-if="canEdit" class="flex gap-2 mt-3">
            <button class="text-xs px-3 py-2 rounded-lg bg-slate-100 text-slate-600" @click="open(o)">ویرایش</button>
            <button class="text-xs px-3 py-2 rounded-lg bg-red-50 text-red-500" @click="remove(o)">حذف</button>
          </div>
        </li>
      </ul>

      <div class="hidden md:block overflow-x-auto">
        <table class="w-full text-sm min-w-[900px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-3">شماره</th>
              <th class="text-right font-medium px-3">کالا</th>
              <th class="text-right font-medium px-3">تامین‌کننده</th>
              <th class="text-right font-medium px-3">تعداد</th>
              <th class="text-right font-medium px-3">قیمت واحد</th>
              <th class="text-right font-medium px-3">مبلغ کل</th>
              <th class="text-right font-medium px-3">تاریخ</th>
              <th class="text-right font-medium px-3">وضعیت</th>
              <th class="px-4"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in filtered" :key="o.id" class="border-t border-slate-100 hover:bg-slate-50">
              <td class="px-4 py-2.5 ltr-nums text-ink font-medium">
                {{ o.order_no }}
                <p v-if="o.request_no" class="text-xs text-slate-400">{{ o.request_no }}</p>
              </td>
              <td class="px-3 text-ink">{{ o.material_name }}</td>
              <td class="px-3 text-slate-500">{{ o.supplier_name }}</td>
              <td class="px-3 ltr-nums text-slate-500">
                {{ num(o.quantity) }} {{ o.material_unit }}
              </td>
              <td class="px-3 ltr-nums text-slate-500">{{ exact(o.unit_price_rial) }}</td>
              <td class="px-3 ltr-nums text-ink font-medium">{{ exact(o.total_rial) }}</td>
              <td class="px-3 text-xs text-slate-500 ltr-nums">
                {{ faDate(o.ordered_on) }}
                <p v-if="o.delivery_days !== null" class="text-slate-400">
                  تحویل در {{ num(o.delivery_days) }} روز
                </p>
              </td>
              <td class="px-3">
                <span class="text-xs rounded-full px-2 py-0.5" :class="STATUS_CLASS[o.status]">
                  {{ o.status_label }}
                </span>
              </td>
              <td class="px-4 text-left whitespace-nowrap">
                <button
                  v-if="canEdit"
                  class="text-xs text-slate-400 hover:text-ink px-1.5"
                  @click="open(o)"
                >ویرایش</button>
                <button
                  v-if="canEdit"
                  class="text-xs text-slate-400 hover:text-red-500 px-1.5"
                  @click="remove(o)"
                >حذف</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
