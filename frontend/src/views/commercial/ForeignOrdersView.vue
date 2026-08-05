<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  foreignApi,
  type Choice,
  type ForeignOrder,
} from "@/api/commercialForeign";
import { useAuthStore } from "@/stores/auth";
import { loadMoneySettings } from "@/composables/useMoney";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import ForeignOrderForm from "@/components/commercial/ForeignOrderForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/** پرونده‌های واردات. */
const auth = useAuthStore();
const router = useRouter();

const rows = ref<ForeignOrder[]>([]);
const statuses = ref<Choice[]>([]);
const loading = ref(true);
const search = ref("");
const status = ref("");

const FA = new Intl.NumberFormat("fa-IR");

const canEdit = computed(
  () => auth.department === "commercial" || !!auth.me?.is_superuser,
);

const STATUS_CLASS: Record<string, string> = {
  draft: "bg-slate-100 text-slate-500",
  registered: "bg-sky-100 text-sky-700",
  queued: "bg-amber-100 text-amber-700",
  allocated: "bg-violet-100 text-violet-700",
  remitted: "bg-violet-100 text-violet-700",
  purchased: "bg-indigo-100 text-indigo-700",
  shipping: "bg-cyan-100 text-cyan-700",
  customs: "bg-orange-100 text-orange-700",
  cleared: "bg-emerald-100 text-emerald-700",
  closed: "bg-slate-100 text-slate-500",
  cancelled: "bg-slate-100 text-slate-400",
};

const filtered = computed(() => {
  const q = search.value.trim();
  return rows.value.filter((o) => {
    if (status.value && o.status !== status.value) return false;
    if (
      q &&
      !`${o.file_no} ${o.pi_no} ${o.registration_no} ${o.goods_desc} ${o.brand} ${o.supplier_name}`.includes(q)
    ) return false;
    return true;
  });
});

/** Deadlines are the thing that quietly kills a file, so they get a colour. */
function deadlineTone(days: number | null): string {
  if (days === null) return "text-slate-300";
  if (days < 0) return "text-red-600 font-medium";
  if (days <= 21) return "text-amber-600";
  return "text-slate-500";
}

function deadlineText(days: number | null): string {
  if (days === null) return "—";
  if (days < 0) return `${FA.format(Math.abs(days))} روز گذشته`;
  return `${FA.format(days)} روز`;
}

async function load() {
  loading.value = true;
  try {
    rows.value = await foreignApi.orders();
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  await loadMoneySettings();
  statuses.value = (await foreignApi.options()).order_statuses;
  await load();
});

const showForm = ref(false);

function onSaved(saved: ForeignOrder) {
  showForm.value = false;
  router.push({ name: "foreign-order", params: { id: saved.id } });
}
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <input
        v-model="search" placeholder="جستجوی پروفرما، ثبت سفارش، کالا یا برند…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 flex-1 min-w-[220px]"
      />
      <select v-model="status" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
        <option value="">همه وضعیت‌ها</option>
        <option v-for="s in statuses" :key="s.value" :value="s.value">{{ s.label }}</option>
      </select>
      <span class="text-xs text-slate-400 px-2">{{ num(filtered.length) }} پرونده</span>
      <button
        v-if="canEdit"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm shrink-0"
        @click="showForm = true"
      >+ پرونده واردات</button>
    </div>

    <ForeignOrderForm v-if="showForm" @close="showForm = false" @saved="onSaved" />

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 8" :key="i" class="h-12 rounded-xl" />
    </div>

    <EmptyState
      v-else-if="!filtered.length"
      title="پرونده‌ای ثبت نشده"
      hint="یک پروفرما را ثبت کنید تا از همان‌جا صف تخصیص، محموله‌ها و گمرکش دنبال شود."
    />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[1040px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-3">پرونده</th>
              <th class="text-right font-medium px-3">کالا / برند</th>
              <th class="text-right font-medium px-3">فروشنده</th>
              <th class="text-right font-medium px-3">ارزش</th>
              <th class="text-right font-medium px-3">بانک</th>
              <th class="text-right font-medium px-3">صف تخصیص</th>
              <th class="text-right font-medium px-3">اعتبار ثبت</th>
              <th class="text-right font-medium px-3">بدون اقدام</th>
              <th class="text-right font-medium px-4">وضعیت</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="o in filtered" :key="o.id"
              class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
              @click="router.push({ name: 'foreign-order', params: { id: o.id } })"
            >
              <td class="px-4 py-2.5">
                <p class="text-ink font-medium ltr-nums">{{ o.pi_no }}</p>
                <p class="text-xs text-slate-400 ltr-nums">
                  {{ o.file_no }}
                  <span v-if="o.registration_no"> · {{ o.registration_no }}</span>
                </p>
              </td>
              <td class="px-3">
                <p class="text-ink">{{ o.goods_desc || "—" }}</p>
                <p v-if="o.brand" class="text-xs text-slate-400">{{ o.brand }}</p>
              </td>
              <td class="px-3 text-slate-500">
                {{ o.supplier_name || "—" }}
                <p v-if="o.country" class="text-xs text-slate-400">{{ o.country }}</p>
              </td>
              <td class="px-3 ltr-nums text-ink">
                {{ FA.format(Number(o.amount)) }}
                <span class="text-xs text-slate-400">{{ o.currency }}</span>
                <p v-if="Number(o.weight_ton)" class="text-xs text-slate-400">
                  {{ num(o.weight_ton) }} تن
                </p>
              </td>
              <td class="px-3 text-slate-500">{{ o.bank_name || "—" }}</td>
              <td class="px-3 ltr-nums">
                <span v-if="o.days_in_queue === null" class="text-slate-300">—</span>
                <span
                  v-else
                  :class="o.is_waiting_allocation ? 'text-amber-600' : 'text-slate-500'"
                >
                  {{ FA.format(o.days_in_queue) }} روز
                  <span v-if="!o.is_waiting_allocation" class="text-xs text-emerald-600">
                    ✔
                  </span>
                </span>
              </td>
              <td class="px-3 ltr-nums text-xs" :class="deadlineTone(o.days_to_expiry)">
                {{ deadlineText(o.days_to_expiry) }}
                <p v-if="o.valid_until" class="text-slate-400">
                  {{ faDate(o.valid_until) }}
                </p>
              </td>
              <td class="px-3 ltr-nums text-xs">
                <span v-if="o.idle_days === null" class="text-slate-300">—</span>
                <span
                  v-else
                  :class="o.idle_days >= 30
                    ? 'text-red-600 font-medium'
                    : o.idle_days >= 15 ? 'text-amber-600' : 'text-slate-500'"
                >{{ FA.format(o.idle_days) }} روز</span>
              </td>
              <td class="px-4">
                <span class="text-xs rounded-full px-2 py-0.5" :class="STATUS_CLASS[o.status]">
                  {{ o.status_label }}
                </span>
                <p v-if="o.shipment_count" class="text-xs text-slate-400 mt-0.5 ltr-nums">
                  {{ num(o.shipment_count) }} محموله
                </p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
