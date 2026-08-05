<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { foreignApi, type QueueReport } from "@/api/commercialForeign";
import { loadMoneySettings } from "@/composables/useMoney";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import StatTile from "@/components/commercial/StatTile.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * صف تخصیص ارز.
 *
 * The bank breakdown is by **file count**, which is what «۴۰٪ کارآفرین» means
 * when the department says it — four in ten files sit there. Value is shown
 * beside it rather than instead of it, because one large file would otherwise
 * swamp the share and hide where the backlog really is.
 */
const router = useRouter();

const data = ref<QueueReport | null>(null);
const loading = ref(true);
const bankFilter = ref<number | "">("");

const FA = new Intl.NumberFormat("fa-IR");

onMounted(async () => {
  await loadMoneySettings();
  try {
    data.value = await foreignApi.queue();
  } finally {
    loading.value = false;
  }
});

const rows = computed(() => {
  const all = data.value?.rows ?? [];
  if (bankFilter.value === "") return all;
  return all.filter((r) => r.bank_id === bankFilter.value);
});
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Skeleton v-for="i in 4" :key="i" class="h-24 rounded-card" />
      </div>
      <Skeleton class="h-64 rounded-card" />
    </div>

    <template v-else-if="data">
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile label="پرونده در صف" :value="num(data.totals.count)" />
        <StatTile
          label="میانگین انتظار"
          :value="`${FA.format(data.totals.avg_days)} روز`"
          :hint="`از ${FA.format(data.totals.min_days)} تا ${FA.format(data.totals.max_days)} روز`"
        />
        <StatTile
          label="بیشترین انتظار"
          :value="`${FA.format(data.totals.max_days)} روز`"
        />
        <StatTile
          label="فراتر از انتظار بانک"
          :value="num(data.totals.overdue_count)"
          hint="پرونده‌هایی که از مهلت اعلامی بانک گذشته‌اند"
        />
      </div>

      <EmptyState
        v-if="!data.rows.length"
        title="هیچ پرونده‌ای در صف تخصیص نیست"
        hint="پرونده‌ای که تاریخ ورود به صف داشته باشد و هنوز تخصیص نگرفته، اینجا می‌آید."
      />

      <template v-else>
        <!-- Share by bank -->
        <div class="bg-surface rounded-card shadow-soft p-4">
          <h3 class="font-bold text-ink text-sm mb-3">سهم بانک‌ها از صف</h3>

          <!-- One stacked bar reads faster than a pie for shares that are
               compared against each other rather than against the whole. -->
          <div class="flex w-full h-4 rounded-full overflow-hidden mb-3">
            <div
              v-for="b in data.by_bank" :key="b.id ?? 'none'"
              class="h-full"
              :style="{ width: `${b.share_pct}%`, background: b.color || '#94a3b8' }"
              :title="`${b.name} — ${b.share_pct}%`"
            />
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-sm min-w-[700px]">
              <thead>
                <tr class="text-xs text-slate-400">
                  <th class="text-right font-medium pb-2">بانک</th>
                  <th class="text-right font-medium pb-2">تعداد</th>
                  <th class="text-right font-medium pb-2">سهم</th>
                  <th class="text-right font-medium pb-2">کمترین</th>
                  <th class="text-right font-medium pb-2">میانگین</th>
                  <th class="text-right font-medium pb-2">بیشترین</th>
                  <th class="text-right font-medium pb-2">دیرکرد</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="b in data.by_bank" :key="b.id ?? 'none'"
                  class="border-t border-slate-100 cursor-pointer hover:bg-slate-50"
                  @click="bankFilter = bankFilter === b.id ? '' : (b.id ?? '')"
                >
                  <td class="py-2">
                    <span
                      class="inline-block w-2.5 h-2.5 rounded-full ml-2"
                      :style="{ background: b.color || '#94a3b8' }"
                    />
                    <span class="text-ink">{{ b.name }}</span>
                  </td>
                  <td class="ltr-nums text-slate-500">{{ num(b.count) }}</td>
                  <td class="ltr-nums text-ink font-medium">
                    {{ FA.format(b.share_pct) }}٪
                  </td>
                  <td class="ltr-nums text-slate-500">{{ FA.format(b.min_days) }} روز</td>
                  <td class="ltr-nums text-slate-500">{{ FA.format(b.avg_days) }} روز</td>
                  <td class="ltr-nums text-slate-500">{{ FA.format(b.max_days) }} روز</td>
                  <td class="ltr-nums">
                    <span v-if="b.overdue_count" class="text-amber-600">
                      {{ num(b.overdue_count) }}
                    </span>
                    <span v-else class="text-slate-300">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="bankFilter !== ''" class="text-xs text-slate-400 mt-2">
            فهرست زیر فقط این بانک را نشان می‌دهد — دوباره کلیک کنید تا برداشته شود.
          </p>
        </div>

        <!-- The queue itself -->
        <div class="bg-surface rounded-card shadow-soft overflow-hidden">
          <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
            پرونده‌های در صف
            <span class="text-slate-400 font-normal">— طولانی‌ترین انتظار بالا</span>
          </h3>
          <div class="overflow-x-auto">
            <table class="w-full text-sm min-w-[960px]">
              <thead>
                <tr class="text-xs text-slate-400 bg-slate-50">
                  <th class="text-right font-medium px-4 py-3">پرونده</th>
                  <th class="text-right font-medium px-3">کالا</th>
                  <th class="text-right font-medium px-3">ارزش</th>
                  <th class="text-right font-medium px-3">بانک</th>
                  <th class="text-right font-medium px-3">ورود به صف</th>
                  <th class="text-right font-medium px-3">انتظار</th>
                  <th class="text-right font-medium px-4">اعتبار ثبت</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="r in rows" :key="r.id"
                  class="border-t border-slate-100 cursor-pointer"
                  :class="r.is_overdue ? 'bg-amber-50/50' : 'hover:bg-slate-50'"
                  @click="router.push({ name: 'foreign-order', params: { id: r.id } })"
                >
                  <td class="px-4 py-2.5">
                    <p class="text-ink font-medium ltr-nums">{{ r.pi_no }}</p>
                    <p class="text-xs text-slate-400 ltr-nums">
                      {{ r.registration_no || r.file_no }}
                    </p>
                  </td>
                  <td class="px-3 text-slate-500">
                    {{ r.goods || "—" }}
                    <p v-if="Number(r.weight_ton)" class="text-xs text-slate-400 ltr-nums">
                      {{ num(r.weight_ton) }} تن
                    </p>
                  </td>
                  <td class="px-3 ltr-nums text-ink">
                    {{ FA.format(Number(r.amount)) }}
                    <span class="text-xs text-slate-400">{{ r.currency }}</span>
                  </td>
                  <td class="px-3 text-slate-500">{{ r.bank }}</td>
                  <td class="px-3 text-xs text-slate-500 ltr-nums">
                    {{ r.queued_on ? faDate(r.queued_on) : "—" }}
                  </td>
                  <td class="px-3 ltr-nums">
                    <span
                      :class="r.is_overdue ? 'text-amber-700 font-medium' : 'text-slate-600'"
                    >{{ FA.format(r.days_waiting) }} روز</span>
                    <p class="text-xs text-slate-400">
                      <span v-if="r.is_overdue">
                        {{ FA.format(r.over_by) }} روز فراتر از انتظار
                      </span>
                      <span v-else>انتظار: {{ FA.format(r.expected_days) }} روز</span>
                    </p>
                  </td>
                  <td class="px-4 text-xs ltr-nums">
                    <span v-if="r.days_to_expiry === null" class="text-slate-300">—</span>
                    <span
                      v-else
                      :class="r.days_to_expiry < 0
                        ? 'text-red-600 font-medium'
                        : r.days_to_expiry <= 21 ? 'text-amber-600' : 'text-slate-500'"
                    >
                      {{ r.days_to_expiry < 0
                        ? `${FA.format(Math.abs(r.days_to_expiry))} روز گذشته`
                        : `${FA.format(r.days_to_expiry)} روز` }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>
