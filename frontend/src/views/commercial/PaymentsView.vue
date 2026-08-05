<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { foreignApi, type PaymentsReport } from "@/api/commercialForeign";
import { loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * پرداخت‌ها — what is still owed the seller, and what lateness has cost.
 *
 * The interest column is the reason this page exists. It sits in the workbook
 * beside each بارنامه and is never totalled anywhere, so nobody sees that it
 * has become a six-figure number growing on its own — the same shape of
 * problem as دموراژ, and just as invisible.
 */
const router = useRouter();

const data = ref<PaymentsReport | null>(null);
const loading = ref(true);
const error = ref("");
const outstandingOnly = ref(true);

const FA = new Intl.NumberFormat("fa-IR");

const LEVEL_ROW: Record<string, string> = {
  danger: "bg-red-50/50",
  warn: "bg-amber-50/40",
  ok: "",
};

async function load() {
  loading.value = true;
  try {
    data.value = await foreignApi.payments(outstandingOnly.value);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await loadMoneySettings(); await load(); });
watch(outstandingOnly, load);

const totals = computed(() => data.value?.totals);
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-28 rounded-card" />
      <Skeleton v-for="i in 6" :key="i" class="h-12 rounded-xl" />
    </div>

    <p v-else-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">
      {{ error }}
    </p>

    <template v-else-if="data && totals">
      <!-- The number the workbook never totals -->
      <div class="grid md:grid-cols-3 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-xs text-slate-400">باقی‌مانده به فروشنده</p>
          <p class="text-2xl font-bold text-ink ltr-nums mt-1">
            {{ FA.format(Number(totals.outstanding)) }}
            <span class="text-sm text-slate-400">USD</span>
          </p>
          <p class="text-xs text-slate-400 ltr-nums mt-1">
            از {{ FA.format(Number(totals.value)) }} کل ·
            {{ FA.format(totals.paid_pct) }}٪ پرداخت شده
          </p>
        </div>

        <div class="bg-red-50 border border-red-100 rounded-card p-4">
          <p class="text-xs text-red-700">سود دیرکرد</p>
          <p class="text-2xl font-bold text-red-700 ltr-nums mt-1">
            {{ FA.format(Number(totals.interest)) }}
            <span class="text-sm">USD</span>
          </p>
          <p class="text-xs text-red-600 ltr-nums mt-1">
            {{ num(totals.overdue_count) }} فاکتور از سررسید گذشته
          </p>
        </div>

        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-xs text-slate-400">جمع قابل پرداخت</p>
          <p class="text-2xl font-bold text-ink ltr-nums mt-1">
            {{ FA.format(Number(totals.payable)) }}
            <span class="text-sm text-slate-400">USD</span>
          </p>
          <p class="text-xs text-slate-400 mt-1">باقی‌مانده به‌علاوه سود دیرکرد</p>
        </div>
      </div>

      <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-3">
        <label class="flex items-center gap-2 text-sm text-slate-600">
          <input v-model="outstandingOnly" type="checkbox" class="rounded" />
          فقط فاکتورهایی که هنوز بدهی دارند
        </label>
        <span class="text-xs text-slate-400 ltr-nums">
          {{ num(totals.unpaid_count) }} از {{ num(totals.shipment_count) }} محموله
        </span>
        <span class="text-xs text-slate-400">
          سود دیرکرد همان عددی است که فروشنده اعلام کرده، نه محاسبه‌ی ما.
        </span>
      </div>

      <EmptyState
        v-if="!data.rows.length"
        icon="✅"
        title="بدهی معوقی نیست"
      />

      <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[1000px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">محموله</th>
                <th class="text-right font-medium px-3">کالا</th>
                <th class="text-right font-medium px-3">ارزش</th>
                <th class="text-right font-medium px-3">پرداخت‌شده</th>
                <th class="text-right font-medium px-3">باقی‌مانده</th>
                <th class="text-right font-medium px-3">سررسید</th>
                <th class="text-right font-medium px-4">سود دیرکرد</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in data.rows" :key="r.id"
                class="border-t border-slate-100 cursor-pointer hover:bg-slate-50"
                :class="LEVEL_ROW[r.level]"
                @click="router.push({ name: 'foreign-order', params: { id: r.order_id } })"
              >
                <td class="px-4 py-2.5">
                  <p class="text-ink font-medium ltr-nums">{{ r.pi_no }}</p>
                  <p class="text-xs text-slate-400 ltr-nums">
                    {{ r.bl_no || r.container_no || r.file_no }}
                  </p>
                </td>
                <td class="px-3 text-slate-500 text-xs">
                  {{ r.goods || "—" }}
                  <p class="text-slate-400 ltr-nums">{{ num(r.weight_ton) }} تن</p>
                </td>
                <td class="px-3 ltr-nums text-slate-500">
                  {{ FA.format(Number(r.value_amount)) }}
                </td>
                <td class="px-3 ltr-nums text-slate-500">
                  {{ FA.format(Number(r.paid_amount)) }}
                  <p v-if="r.paid_pct !== null" class="text-xs text-slate-400">
                    {{ FA.format(r.paid_pct) }}٪
                  </p>
                </td>
                <td class="px-3 ltr-nums font-medium"
                    :class="Number(r.outstanding) ? 'text-ink' : 'text-emerald-600'">
                  {{ Number(r.outstanding)
                    ? FA.format(Number(r.outstanding)) : "تسویه شد" }}
                </td>
                <td class="px-3 text-xs ltr-nums">
                  <span v-if="!r.due_on" class="text-slate-300">—</span>
                  <template v-else>
                    <span class="text-slate-500">{{ faDate(r.due_on) }}</span>
                    <p
                      v-if="r.overdue_days"
                      class="font-medium"
                      :class="r.level === 'danger' ? 'text-red-600' : 'text-amber-600'"
                    >{{ FA.format(r.overdue_days) }} روز گذشته</p>
                  </template>
                </td>
                <td class="px-4 ltr-nums">
                  <span v-if="Number(r.interest_amount)" class="text-red-600 font-medium">
                    {{ FA.format(Number(r.interest_amount)) }}
                  </span>
                  <span v-else class="text-slate-300">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
