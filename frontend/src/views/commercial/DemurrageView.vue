<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { foreignApi, type DemurrageReport } from "@/api/commercialForeign";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import StatTile from "@/components/commercial/StatTile.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * دموراژ و انبارداری.
 *
 * The department asked for this to be bold, and the reason is arithmetic:
 * these are the only costs in the module that grow on their own. The headline
 * is deliberately «هر روز تأخیر چقدر آب می‌خورد» rather than the accumulated
 * total — the total is history, the daily burn is the thing someone can still
 * do something about.
 */
const router = useRouter();
const { exact } = useMoney();

const data = ref<DemurrageReport | null>(null);
const loading = ref(true);
const accruingOnly = ref(true);

const FA = new Intl.NumberFormat("fa-IR");

const LEVEL_ROW: Record<string, string> = {
  danger: "bg-red-50/60",
  warn: "bg-amber-50/50",
  ok: "",
  none: "",
};

async function load() {
  loading.value = true;
  try {
    data.value = await foreignApi.demurrage(accruingOnly.value);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await loadMoneySettings(); await load(); });
watch(accruingOnly, load);

const totals = computed(() => data.value?.totals);
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Skeleton v-for="i in 4" :key="i" class="h-24 rounded-card" />
      </div>
      <Skeleton class="h-64 rounded-card" />
    </div>

    <template v-else-if="data && totals">
      <!-- The number that makes someone pick up the phone -->
      <div class="bg-red-50 border border-red-100 rounded-card p-4">
        <p class="text-sm text-red-700">هزینه هر روز تأخیر، از همین امروز</p>
        <p class="text-3xl font-bold text-red-700 ltr-nums mt-1">
          {{ exact(totals.daily_burn_rial, true) }}
        </p>
        <p class="text-xs text-red-600 mt-1 ltr-nums">
          {{ num(totals.accruing_count) }} کانتینر هنوز در حال هزینه‌سازی است
          <span v-if="totals.over_free_days">
            · {{ num(totals.over_free_days) }} کانتینر از Free Days گذشته
          </span>
          <span v-if="totals.expiring_soon">
            · {{ num(totals.expiring_soon) }} کانتینر نزدیک به پایان Free Days
          </span>
        </p>
      </div>

      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile label="جمع دموراژ" :value="exact(totals.demurrage_rial, true)" />
        <StatTile label="جمع انبارداری" :value="exact(totals.storage_rial, true)" />
        <StatTile
          label="جمع کل"
          :value="exact(totals.total_rial, true)"
          :hint="`${num(totals.container_count)} کانتینر`"
        />
        <StatTile
          label="در حال هزینه‌سازی"
          :value="num(totals.accruing_count)"
          hint="کانتینرهایی که هنوز ترخیص نشده‌اند"
        />
      </div>

      <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-3">
        <label class="flex items-center gap-2 text-sm text-slate-600">
          <input v-model="accruingOnly" type="checkbox" class="rounded" />
          فقط کانتینرهایی که هنوز هزینه می‌سازند
        </label>
        <span class="text-xs text-slate-400">
          انبارداری از روز رسیدن حساب می‌شود؛ دموراژ فقط پس از پایان Free Days.
        </span>
      </div>

      <EmptyState
        v-if="!data.rows.length"
        title="کانتینری در بندر نیست"
        hint="کانتینری که تاریخ رسیدن نداشته باشد، هیچ روزی برایش شمرده نمی‌شود."
      />

      <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[1060px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">کانتینر</th>
                <th class="text-right font-medium px-3">پرونده</th>
                <th class="text-right font-medium px-3">رسیدن</th>
                <th class="text-right font-medium px-3">در بندر</th>
                <th class="text-right font-medium px-3">Free Days</th>
                <th class="text-right font-medium px-3">دموراژ</th>
                <th class="text-right font-medium px-3">انبارداری</th>
                <th class="text-right font-medium px-3">جمع</th>
                <th class="text-right font-medium px-4">روزانه</th>
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
                  <p class="text-ink font-medium ltr-nums">{{ r.container_no || "—" }}</p>
                  <p class="text-xs text-slate-400 ltr-nums">
                    {{ r.bl_no }}<span v-if="r.carrier"> · {{ r.carrier }}</span>
                  </p>
                </td>
                <td class="px-3 text-xs text-slate-500 ltr-nums">
                  {{ r.pi_no }}
                  <p class="text-slate-400">{{ r.goods }}</p>
                </td>
                <td class="px-3 text-xs text-slate-500 ltr-nums">
                  {{ r.arrived_on ? faDate(r.arrived_on) : "—" }}
                  <p v-if="r.cleared_on" class="text-emerald-600">
                    ترخیص {{ faDate(r.cleared_on) }}
                  </p>
                </td>
                <td class="px-3 ltr-nums text-slate-600">
                  {{ FA.format(r.days_at_port ?? 0) }} روز
                </td>
                <td class="px-3 ltr-nums text-xs">
                  <span v-if="r.free_days_left === null" class="text-slate-300">—</span>
                  <span v-else-if="r.free_days_left === 0" class="text-red-600 font-medium">
                    تمام شد
                  </span>
                  <span
                    v-else
                    :class="r.free_days_left <= 3 ? 'text-amber-600' : 'text-slate-500'"
                  >{{ FA.format(r.free_days_left) }} روز مانده</span>
                  <p class="text-slate-400">
                    {{ FA.format(r.free_days_used ?? 0) }} از {{ FA.format(r.free_days) }}
                  </p>
                </td>
                <td class="px-3 ltr-nums">
                  <span v-if="r.demurrage_days" class="text-red-600 font-medium">
                    {{ exact(r.demurrage_rial) }}
                  </span>
                  <span v-else class="text-slate-300">—</span>
                  <p v-if="r.demurrage_days" class="text-xs text-slate-400">
                    {{ FA.format(r.demurrage_days) }} روز
                  </p>
                </td>
                <td class="px-3 ltr-nums text-slate-500">
                  {{ Number(r.storage_rial) ? exact(r.storage_rial) : "—" }}
                </td>
                <td class="px-3 ltr-nums text-ink font-medium">
                  {{ Number(r.total_rial) ? exact(r.total_rial) : "—" }}
                </td>
                <td class="px-4 ltr-nums text-xs">
                  <span v-if="r.is_accruing" class="text-red-600">
                    {{ exact(r.daily_rial) }}
                  </span>
                  <span v-else class="text-slate-300">متوقف</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
