<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import api from "@/api/client";
import { salesApi } from "@/api/sales";
import PeriodCalendar from "@/components/PeriodCalendar.vue";
import { toast, confirm } from "@/composables/useUi";
import type { MonthCalendar } from "@/types";

/**
 * The CEO decides, month by month, whether data is recorded once for the
 * whole month or week by week.
 *
 * A switch is only offered when it is safe: a month that already holds
 * figures cannot be cut into weeks, and weeks that hold figures cannot be
 * collapsed back — in both directions the numbers would have to be invented.
 * The API says why, and this page shows that reason instead of a dead button.
 */
interface MonthRow {
  id: number;
  label: string;
  jalali_year: number;
  jalali_month: number;
  grain: "month" | "week";
  week_count: number;
  days: number;
  can_go_weekly: boolean;
  can_go_monthly: boolean;
  blocked_reason: string;
}

const rows = ref<MonthRow[]>([]);
const loading = ref(true);
const busy = ref<number | null>(null);
const openMonth = ref<number | null>(null);
const calendar = ref<MonthCalendar | null>(null);

const years = computed(() => [...new Set(rows.value.map((r) => r.jalali_year))]);
const weeklyCount = computed(() => rows.value.filter((r) => r.grain === "week").length);

async function load() {
  loading.value = true;
  try {
    const { data } = await api.get("/sales/periods/year-grain/");
    rows.value = data;
  } finally {
    loading.value = false;
  }
}

async function setGrain(row: MonthRow, grain: "month" | "week") {
  if (row.grain === grain) return;
  if (grain === "month") {
    const ok = await confirm({
      title: "بازگشت به ثبت ماهانه",
      message: `هفته‌های «${row.label}» حذف می‌شوند و اطلاعات یک‌جا برای کل ماه وارد خواهد شد. ادامه می‌دهید؟`,
    });
    if (!ok) return;
  }
  busy.value = row.id;
  try {
    await api.post(`/sales/periods/${row.id}/${grain === "week" ? "split" : "unsplit"}/`);
    toast.success(
      grain === "week"
        ? `«${row.label}» هفتگی شد.`
        : `«${row.label}» به ثبت ماهانه بازگشت.`,
    );
    await load();
    if (openMonth.value === row.id) await showCalendar(row);
  } catch (e: any) {
    toast.error(e?.response?.data?.detail ?? "تغییر انجام نشد.");
  } finally {
    busy.value = null;
  }
}

async function showCalendar(row: MonthRow) {
  if (openMonth.value === row.id) {
    openMonth.value = null;
    return;
  }
  openMonth.value = row.id;
  calendar.value = null;
  const progress = await salesApi.monthProgress(row.id);
  calendar.value = progress.calendar;
}

onMounted(load);

/** Everything from this month on becomes weekly — the usual way to switch. */
async function weeklyFromHere(row: MonthRow) {
  const later = rows.value.filter(
    (r) => r.jalali_year > row.jalali_year
      || (r.jalali_year === row.jalali_year && r.jalali_month >= row.jalali_month),
  );
  const doable = later.filter((r) => r.can_go_weekly);
  const ok = await confirm({
    title: "هفتگی‌کردن از این ماه به بعد",
    message: `${doable.length} ماه هفتگی می‌شوند. ماه‌هایی که داده دارند دست‌نخورده می‌مانند.`,
  });
  if (!ok) return;
  busy.value = row.id;
  try {
    for (const r of doable) {
      await api.post(`/sales/periods/${r.id}/split/`);
    }
    toast.success(`${doable.length} ماه هفتگی شد.`);
    await load();
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-baseline justify-between flex-wrap gap-2">
      <div>
        <h2 class="font-bold text-ink">دوره‌های ثبت اطلاعات</h2>
        <p class="text-xs text-slate-400 mt-1 leading-6">
          برای هر ماه تعیین کنید اطلاعات یک‌بار برای کل ماه ثبت شود یا هفته‌به‌هفته.
          تارگت‌ها در هر دو حالت ماهانه‌اند.
        </p>
      </div>
      <span class="text-xs text-slate-400 ltr-nums">
        {{ weeklyCount }} از {{ rows.length }} ماه هفتگی
      </span>
    </div>

    <div v-if="loading" class="text-slate-400 text-sm">در حال بارگذاری…</div>

    <div v-else v-for="y in years" :key="y" class="space-y-2">
      <h3 class="text-sm font-semibold text-slate-500 ltr-nums">سال {{ y }}</h3>

      <div
        v-for="row in rows.filter(r => r.jalali_year === y)"
        :key="row.id"
        class="bg-surface rounded-card shadow-soft p-3"
      >
        <div class="flex items-center gap-3 flex-wrap">
          <span class="font-medium text-ink w-28">{{ row.label }}</span>

          <!-- Grain switch -->
          <div class="flex bg-slate-100 rounded-xl p-0.5">
            <button
              v-for="opt in (['month', 'week'] as const)"
              :key="opt"
              class="px-3 py-1 rounded-lg text-xs transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              :class="row.grain === opt ? 'bg-surface shadow-soft text-ink font-medium' : 'text-slate-500 hover:text-ink'"
              :disabled="busy === row.id
                || (opt === 'week' && row.grain !== 'week' && !row.can_go_weekly)
                || (opt === 'month' && row.grain !== 'month' && !row.can_go_monthly)"
              @click="setGrain(row, opt)"
            >{{ opt === "month" ? "ماهانه" : "هفتگی" }}</button>
          </div>

          <span v-if="row.grain === 'week'" class="text-xs text-slate-400 ltr-nums">
            {{ row.week_count }} هفته · {{ row.days }} روز
          </span>
          <span v-else class="text-xs text-slate-400 ltr-nums">{{ row.days }} روز</span>

          <span v-if="row.blocked_reason" class="text-xs text-amber-600">
            {{ row.blocked_reason }}
          </span>

          <div class="mr-auto flex items-center gap-3">
            <button
              v-if="row.can_go_weekly"
              class="text-xs text-slate-500 hover:text-ink hover:underline"
              @click="weeklyFromHere(row)"
            >هفتگی از این ماه به بعد</button>
            <button
              v-if="row.grain === 'week'"
              class="text-xs text-brand-600 hover:underline"
              @click="showCalendar(row)"
            >{{ openMonth === row.id ? "بستن تقویم" : "تقویم" }}</button>
          </div>
        </div>

        <div v-if="openMonth === row.id" class="border-t border-slate-100 mt-3 pt-3">
          <PeriodCalendar :calendar="calendar" />
        </div>
      </div>
    </div>
  </div>
</template>
