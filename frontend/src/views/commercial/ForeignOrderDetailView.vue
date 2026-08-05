<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  foreignApi,
  type ForeignOrderDetail,
  type Shipment,
} from "@/api/commercialForeign";
import { useAuthStore } from "@/stores/auth";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { confirm } from "@/composables/useUi";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import ForeignOrderForm from "@/components/commercial/ForeignOrderForm.vue";
import ShipmentForm from "@/components/commercial/ShipmentForm.vue";
import OrderEventForm from "@/components/commercial/OrderEventForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * پرونده واردات — the page someone works a file from.
 *
 * Laid out as the pipeline actually runs: the gates it has passed across the
 * top, the containers underneath, and the timeline last, because the timeline
 * is what you add to rather than what you read first.
 */
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const { exact } = useMoney();

const order = ref<ForeignOrderDetail | null>(null);
const loading = ref(true);
const error = ref("");

const FA = new Intl.NumberFormat("fa-IR");

const canEdit = computed(
  () => auth.department === "commercial" || !!auth.me?.is_superuser,
);

/** The gates, in the order a file passes them. */
const gates = computed(() => {
  const o = order.value;
  if (!o) return [];
  return [
    { label: "ثبت سفارش", date: o.registered_on },
    { label: "ورود به صف تخصیص", date: o.queued_on },
    { label: "تخصیص ارز", date: o.allocated_on },
  ];
});

const shipStatusClass: Record<string, string> = {
  ready: "bg-slate-100 text-slate-500",
  departed: "bg-sky-100 text-sky-700",
  at_sea: "bg-cyan-100 text-cyan-700",
  at_port: "bg-amber-100 text-amber-700",
  customs: "bg-orange-100 text-orange-700",
  cleared: "bg-emerald-100 text-emerald-700",
  delivered: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-slate-100 text-slate-400",
};

async function load() {
  loading.value = true;
  try {
    order.value = await foreignApi.order(Number(route.params.id));
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await loadMoneySettings(); await load(); });

const showOrderForm = ref(false);
const showEventForm = ref(false);
const showShipmentForm = ref(false);
const editingShipment = ref<Shipment | null>(null);

function openShipment(s: Shipment | null) {
  editingShipment.value = s;
  showShipmentForm.value = true;
}

function afterChange() {
  showOrderForm.value = false;
  showEventForm.value = false;
  showShipmentForm.value = false;
  editingShipment.value = null;
  load();
}

async function removeShipment(s: Shipment) {
  const ok = await confirm({
    title: "حذف محموله",
    message: `کانتینر ${s.container_no || s.bl_no || ""} حذف شود؟`,
    danger: true,
  });
  if (!ok) return;
  try {
    await foreignApi.removeShipment(s.id);
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}

function deadlineTone(days: number | null): string {
  if (days === null) return "text-slate-400";
  if (days < 0) return "text-red-600";
  if (days <= 21) return "text-amber-600";
  return "text-slate-500";
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-28 rounded-card" />
      <Skeleton class="h-64 rounded-card" />
    </div>

    <p
      v-else-if="error"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line"
    >{{ error }}</p>

    <template v-else-if="order">
      <!-- Header -->
      <div class="bg-surface rounded-card shadow-soft p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="text-xs text-slate-400 ltr-nums">{{ order.file_no }}</p>
            <h2 class="text-lg font-bold text-ink ltr-nums">{{ order.pi_no }}</h2>
            <p class="text-sm text-slate-500 mt-1">
              {{ order.goods_desc || "—" }}
              <span v-if="order.brand" class="text-slate-400"> · {{ order.brand }}</span>
              <span v-if="Number(order.weight_ton)" class="text-slate-400 ltr-nums">
                · {{ num(order.weight_ton) }} تن
              </span>
            </p>
            <p class="text-xs text-slate-400 mt-1">
              <span v-if="order.supplier_name">{{ order.supplier_name }}</span>
              <span v-if="order.country"> · {{ order.country }}</span>
              <span v-if="order.registration_no" class="ltr-nums">
                · ثبت سفارش {{ order.registration_no }}
              </span>
            </p>
          </div>
          <div class="flex flex-wrap gap-2 shrink-0">
            <button
              class="text-sm text-slate-500 hover:text-ink px-2 py-2"
              @click="router.push({ name: 'foreign-orders' })"
            >← بازگشت</button>
            <button
              v-if="canEdit"
              class="bg-slate-100 text-ink rounded-xl px-4 py-2 text-sm"
              @click="showEventForm = true"
            >+ ثبت اقدام</button>
            <button
              v-if="canEdit"
              class="bg-slate-100 text-ink rounded-xl px-4 py-2 text-sm"
              @click="openShipment(null)"
            >+ محموله</button>
            <button
              v-if="canEdit"
              class="bg-panel text-white rounded-xl px-4 py-2 text-sm"
              @click="showOrderForm = true"
            >ویرایش پرونده</button>
          </div>
        </div>

        <!-- Value, status, gates -->
        <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-4 pt-4 border-t border-slate-100">
          <div>
            <p class="text-xs text-slate-400">ارزش ارزی</p>
            <p class="text-lg font-bold text-ink ltr-nums">
              {{ FA.format(Number(order.amount)) }}
              <span class="text-sm text-slate-400">{{ order.currency }}</span>
            </p>
            <p v-if="order.amount_rial_centre" class="text-xs text-slate-400 ltr-nums">
              ≈ {{ exact(order.amount_rial_centre, true) }} — نرخ مرکز مبادله
            </p>
          </div>
          <div>
            <p class="text-xs text-slate-400">وضعیت</p>
            <p class="text-lg font-bold text-ink">{{ order.status_label }}</p>
            <p class="text-xs text-slate-400">
              {{ order.bank_name || "بانک ثبت نشده" }}
            </p>
          </div>
          <div>
            <p class="text-xs text-slate-400">صف تخصیص ارز</p>
            <p class="text-lg font-bold ltr-nums"
               :class="order.is_waiting_allocation ? 'text-amber-600' : 'text-ink'">
              <span v-if="order.days_in_queue === null">—</span>
              <span v-else>{{ FA.format(order.days_in_queue) }} روز</span>
            </p>
            <p class="text-xs text-slate-400 ltr-nums">
              <span v-if="order.is_waiting_allocation">
                انتظار اعلامی: {{ FA.format(order.expected_queue_days) }} روز
              </span>
              <span v-else-if="order.allocated_on" class="text-emerald-600">
                تخصیص گرفت — {{ faDate(order.allocated_on) }}
              </span>
            </p>
          </div>
          <div>
            <p class="text-xs text-slate-400">بدون اقدام</p>
            <p class="text-lg font-bold ltr-nums"
               :class="(order.idle_days ?? 0) >= 30
                 ? 'text-red-600'
                 : (order.idle_days ?? 0) >= 15 ? 'text-amber-600' : 'text-ink'">
              <span v-if="order.idle_days === null">—</span>
              <span v-else>{{ FA.format(order.idle_days) }} روز</span>
            </p>
            <p v-if="order.last_action_on" class="text-xs text-slate-400">
              آخرین اقدام {{ faDate(order.last_action_on) }}
            </p>
          </div>
        </div>

        <!-- Deadlines: the things that void a file if they pass -->
        <div class="flex flex-wrap gap-x-6 gap-y-2 mt-3 pt-3 border-t border-slate-100 text-xs">
          <span v-for="g in gates" :key="g.label" class="text-slate-500">
            {{ g.label }}:
            <span class="ltr-nums" :class="g.date ? 'text-ink' : 'text-slate-300'">
              {{ g.date ? faDate(g.date) : "—" }}
            </span>
          </span>
          <span :class="deadlineTone(order.days_to_expiry)">
            اعتبار ثبت سفارش:
            <span class="ltr-nums">
              {{ order.valid_until ? faDate(order.valid_until) : "—" }}
              <template v-if="order.days_to_expiry !== null">
                ({{ order.days_to_expiry < 0
                  ? `${FA.format(Math.abs(order.days_to_expiry))} روز گذشته`
                  : `${FA.format(order.days_to_expiry)} روز مانده` }})
              </template>
            </span>
          </span>
          <span :class="deadlineTone(order.days_to_purchase_deadline)">
            مهلت خرید ارز:
            <span class="ltr-nums">
              {{ order.purchase_deadline ? faDate(order.purchase_deadline) : "—" }}
            </span>
          </span>
        </div>

        <p v-if="order.note" class="text-sm text-slate-500 mt-3">{{ order.note }}</p>
      </div>

      <!-- Shipments -->
      <div class="bg-surface rounded-card shadow-soft overflow-hidden">
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          محموله‌ها
          <span class="text-slate-400 font-normal">
            ({{ num(order.shipments.length) }} کانتینر)
          </span>
        </h3>

        <EmptyState
          v-if="!order.shipments.length"
          title="هنوز محموله‌ای ثبت نشده"
          hint="هر کانتینر بارنامه و تاریخ رسیدن خودش را دارد، پس جداگانه ثبت می‌شود."
        />

        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm min-w-[1000px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">کانتینر / بارنامه</th>
                <th class="text-right font-medium px-3">وزن</th>
                <th class="text-right font-medium px-3">ETD → ETA</th>
                <th class="text-right font-medium px-3">در بندر</th>
                <th class="text-right font-medium px-3">Free Days</th>
                <th class="text-right font-medium px-3">دموراژ + انبارداری</th>
                <th class="text-right font-medium px-3">وضعیت</th>
                <th class="px-4"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="s in order.shipments" :key="s.id"
                class="border-t border-slate-100"
                :class="s.demurrage_days > 0 ? 'bg-red-50/40' : 'hover:bg-slate-50'"
              >
                <td class="px-4 py-2.5">
                  <p class="text-ink font-medium ltr-nums">{{ s.container_no || "—" }}</p>
                  <p class="text-xs text-slate-400 ltr-nums">
                    {{ s.bl_no }}<span v-if="s.carrier"> · {{ s.carrier }}</span>
                  </p>
                </td>
                <td class="px-3 ltr-nums text-slate-500">{{ num(s.weight_ton) }} تن</td>
                <td class="px-3 text-xs text-slate-500 ltr-nums">
                  {{ s.etd ? faDate(s.etd) : "—" }} → {{ s.eta ? faDate(s.eta) : "—" }}
                  <p v-if="s.transit_days !== null" class="text-slate-400">
                    {{ FA.format(s.transit_days) }} روز مسیر
                  </p>
                </td>
                <td class="px-3 ltr-nums text-slate-500">
                  <span v-if="s.days_at_port === null" class="text-slate-300">نرسیده</span>
                  <span v-else>{{ FA.format(s.days_at_port) }} روز</span>
                  <p v-if="s.arrived_on" class="text-xs text-slate-400">
                    {{ faDate(s.arrived_on) }}
                  </p>
                </td>
                <td class="px-3 ltr-nums text-xs">
                  <span v-if="s.free_days_left === null" class="text-slate-300">—</span>
                  <span
                    v-else-if="s.free_days_left === 0"
                    class="text-red-600 font-medium"
                  >تمام شد</span>
                  <span
                    v-else
                    :class="s.free_days_left <= 3 ? 'text-amber-600' : 'text-slate-500'"
                  >{{ FA.format(s.free_days_left) }} روز مانده</span>
                  <p class="text-slate-400">از {{ FA.format(s.free_days) }} روز</p>
                </td>
                <td class="px-3 ltr-nums">
                  <span
                    v-if="Number(s.accruing_rial)"
                    :class="s.is_accruing ? 'text-red-600 font-medium' : 'text-slate-500'"
                  >{{ exact(s.accruing_rial) }}</span>
                  <span v-else class="text-slate-300">—</span>
                  <p v-if="s.demurrage_days" class="text-xs text-slate-400">
                    {{ FA.format(s.demurrage_days) }} روز دموراژ
                  </p>
                </td>
                <td class="px-3">
                  <span class="text-xs rounded-full px-2 py-0.5" :class="shipStatusClass[s.status]">
                    {{ s.status_label }}
                  </span>
                  <p v-if="s.cleared_on" class="text-xs text-slate-400 mt-0.5">
                    ترخیص {{ faDate(s.cleared_on) }}
                  </p>
                </td>
                <td class="px-4 text-left whitespace-nowrap">
                  <button
                    v-if="canEdit"
                    class="text-xs text-slate-400 hover:text-ink px-1.5"
                    @click="openShipment(s)"
                  >ویرایش</button>
                  <button
                    v-if="canEdit"
                    class="text-xs text-slate-400 hover:text-red-500 px-1.5"
                    @click="removeShipment(s)"
                  >حذف</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Timeline -->
      <div class="bg-surface rounded-card shadow-soft overflow-hidden">
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          تاریخچه اقدامات
        </h3>
        <EmptyState
          v-if="!order.events.length"
          title="هنوز اقدامی ثبت نشده"
          hint="هر اقدامی که ثبت شود، شمارش «روز بدون اقدام» را از نو شروع می‌کند."
        />
        <ul v-else class="divide-y divide-slate-100">
          <li v-for="e in order.events" :key="e.id" class="px-4 py-3 flex gap-3">
            <span
              class="w-2 h-2 rounded-full mt-1.5 shrink-0"
              :class="e.blocked_reason ? 'bg-red-400' : 'bg-emerald-400'"
            />
            <div class="min-w-0 flex-1">
              <p class="text-sm text-ink">{{ e.title }}</p>
              <p v-if="e.blocked_reason" class="text-xs text-red-500 mt-0.5">
                علت توقف: {{ e.blocked_reason }}
              </p>
              <p v-if="e.note" class="text-xs text-slate-500 mt-0.5">{{ e.note }}</p>
              <p class="text-xs text-slate-400 mt-0.5 ltr-nums">
                {{ faDate(e.at) }}
                <span v-if="e.created_by_name"> · {{ e.created_by_name }}</span>
              </p>
            </div>
          </li>
        </ul>
      </div>

      <ForeignOrderForm
        v-if="showOrderForm" :order="order"
        @close="showOrderForm = false" @saved="afterChange"
      />
      <OrderEventForm
        v-if="showEventForm" :order="order"
        @close="showEventForm = false" @saved="afterChange"
      />
      <ShipmentForm
        v-if="showShipmentForm" :order="order" :shipment="editingShipment"
        @close="showShipmentForm = false" @saved="afterChange"
      />
    </template>

    <EmptyState v-else title="پرونده پیدا نشد" />
  </div>
</template>
