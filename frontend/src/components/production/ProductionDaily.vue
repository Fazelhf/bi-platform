<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { productionApi, type ProductionDaily } from "@/api/production";
import { num } from "@/utils/format";
import CrmChart from "@/components/crm/CrmChart.vue";

/**
 * تولید روزانه — the month day by day.
 *
 * A holiday or a weekly day off is shaded and named; a working day with no
 * figures is flagged «ثبت نشده», so a gap is told apart from a day the factory
 * did not work (the admin's work calendar decides which is which). A click on
 * a day lists its lines and shifts, with what the form's notes said.
 */
const props = defineProps<{ period: number | null }>();
const data = ref<ProductionDaily | null>(null);
const loading = ref(false);
const picked = ref<number | null>(null);

async function load() {
  if (!props.period) return;
  loading.value = true;
  try {
    data.value = await productionApi.daily(props.period, picked.value ?? undefined);
  } finally {
    loading.value = false;
  }
}
watch(() => props.period, () => { picked.value = null; load(); }, { immediate: true });

function pick(period: number | null) {
  if (!period) return;
  picked.value = picked.value === period ? null : period;
  load();
}

const cats = computed(() => data.value?.days.map((d) => `${num(d.day)}${d.workday ? "" : " ·"}`) ?? []);
const series = computed(() => [
  { name: "شیفت روز", stack: "s", color: "#f59e0b", values: data.value?.days.map((d) => d.day_shift) ?? [] },
  { name: "شیفت شب", stack: "s", color: "#6366f1", values: data.value?.days.map((d) => d.night_shift) ?? [] },
]);
const pickedDay = computed(() => data.value?.days.find((d) => d.period === picked.value) ?? null);
const s = computed(() => data.value?.summary);
</script>

<template>
  <div class="space-y-4">
    <p v-if="loading && !data" class="text-sm text-slate-400">در حال بارگذاری…</p>
    <template v-else-if="data">
      <div v-if="!data.daily" class="bg-amber-50 text-amber-800 rounded-card p-4 text-sm">
        این ماه روزانه ثبت نشده (دانه‌ی ثبت تولید برای این ماه روزانه نیست)؛ نمای روزانه برای ماه‌های روزانه پر می‌شود.
      </div>

      <div class="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <div class="text-xs text-slate-400">تولید ماه</div>
          <div class="text-xl font-bold ltr-nums text-ink">{{ num(s?.output ?? 0) }}</div>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <div class="text-xs text-slate-400">روز کاری ثبت‌شده</div>
          <div class="text-xl font-bold text-ink">{{ num(s?.entered_workdays ?? 0) }} <span class="text-sm text-slate-400">از {{ num(s?.workdays ?? 0) }}</span></div>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <div class="text-xs text-slate-400">میانگین هر روز کاری</div>
          <div class="text-xl font-bold ltr-nums text-ink">{{ num(s?.per_workday ?? 0) }}</div>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <div class="text-xs text-slate-400">تولید هر شیفت فعال</div>
          <div class="text-xl font-bold ltr-nums" :class="s && s.ideal_per_shift && s.per_shift < s.ideal_per_shift ? 'text-amber-600' : 'text-emerald-600'">
            {{ num(s?.per_shift ?? 0) }}
          </div>
          <div v-if="s?.ideal_per_shift" class="text-[11px] text-slate-400">ایده‌آل {{ num(s.ideal_per_shift) }}</div>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <div class="text-xs text-slate-400">روز کاری بدون ثبت</div>
          <div class="text-xl font-bold" :class="s?.missing ? 'text-red-500' : 'text-emerald-600'">{{ num(s?.missing ?? 0) }}</div>
        </div>
      </div>

      <div class="bg-surface rounded-card shadow-soft p-4">
        <h3 class="text-sm font-semibold text-ink mb-2">تولید روزانه · روز و شب <span class="text-[11px] text-slate-400 font-normal">(«·» یعنی تعطیل)</span></h3>
        <CrmChart :categories="cats" :series="series" format="count" :height="280"
                  @pick="(i) => pick(data!.days[i]?.period ?? null)" />
      </div>

      <div class="bg-surface rounded-card shadow-soft overflow-x-auto">
        <table class="w-full text-sm min-w-[720px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-2">روز</th>
              <th class="text-left font-medium px-3">تولید</th>
              <th class="text-left font-medium px-3">روز</th>
              <th class="text-left font-medium px-3">شب</th>
              <th class="text-left font-medium px-3">ژورنال</th>
              <th class="text-left font-medium px-3">پوز</th>
              <th class="text-left font-medium px-3">رسید</th>
              <th class="text-left font-medium px-3">ضایعات</th>
              <th class="text-left font-medium px-3">توقف (شیفت)</th>
              <th class="text-right font-medium px-4">وضعیت</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in data.days" :key="d.date"
                class="border-t border-slate-100" :class="[d.workday ? '' : 'bg-rose-50/60', d.period ? 'cursor-pointer hover:bg-slate-50' : '', d.period === picked ? 'bg-sky-50' : '']"
                @click="pick(d.period)">
              <td class="px-4 py-2 whitespace-nowrap ltr-nums">{{ d.label }}</td>
              <td class="px-3 text-left ltr-nums text-ink">{{ d.output ? num(d.output) : "—" }}</td>
              <td class="px-3 text-left ltr-nums text-slate-500">{{ d.day_shift ? num(d.day_shift) : "—" }}</td>
              <td class="px-3 text-left ltr-nums text-slate-500">{{ d.night_shift ? num(d.night_shift) : "—" }}</td>
              <td class="px-3 text-left ltr-nums text-slate-500">{{ d.journal ? num(d.journal) : "—" }}</td>
              <td class="px-3 text-left ltr-nums text-slate-500">{{ d.pos ? num(d.pos) : "—" }}</td>
              <td class="px-3 text-left ltr-nums text-slate-500">{{ d.receipt ? num(d.receipt) : "—" }}</td>
              <td class="px-3 text-left ltr-nums text-slate-500">{{ d.entered ? `${num(d.waste_pct)}٪` : "—" }}</td>
              <td class="px-3 text-left ltr-nums text-slate-500">{{ d.downtime ? num(d.downtime) : "—" }}</td>
              <td class="px-4 text-xs whitespace-nowrap">
                <span v-if="!d.workday" class="text-rose-600">{{ d.off }}<template v-if="d.entered"> · با تولید</template></span>
                <span v-else-if="d.missing" class="text-red-500 font-medium">ثبت نشده</span>
                <span v-else-if="d.entered" class="text-emerald-600">ثبت شده</span>
                <span v-else class="text-slate-300">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="pickedDay && data.detail" class="bg-surface rounded-card shadow-soft overflow-x-auto">
        <h3 class="text-sm font-semibold text-ink px-4 pt-4 pb-2">{{ pickedDay.label }} · خط به خط</h3>
        <table class="w-full text-xs min-w-[760px]">
          <thead>
            <tr class="text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-2">خط</th>
              <th class="text-right font-medium px-2">شیفت</th>
              <th class="text-left font-medium px-2">تولید</th>
              <th class="text-left font-medium px-2">شیفت فعال</th>
              <th class="text-left font-medium px-2">ضایعات</th>
              <th class="text-left font-medium px-2">خرابی / تعویض سایز / بی‌کاری</th>
              <th class="text-right font-medium px-4">توضیحات · طرح چاپ</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in data.detail" :key="i" class="border-t border-slate-100">
              <td class="px-4 py-2 text-ink">{{ r.machine }}</td>
              <td class="px-2 text-slate-500">{{ r.shift_label }}</td>
              <td class="px-2 text-left ltr-nums">{{ num(r.output) }}</td>
              <td class="px-2 text-left ltr-nums">{{ num(r.active_shifts) }}</td>
              <td class="px-2 text-left ltr-nums">{{ num(r.waste_pct) }}٪</td>
              <td class="px-2 text-left ltr-nums text-slate-500">{{ num(r.downtime_breakdown) }} / {{ num(r.downtime_sizechange) }} / {{ num(r.downtime_nowork) }}</td>
              <td class="px-4 text-slate-500">{{ [r.description, r.print_design].filter(Boolean).join(" · ") || "—" }}</td>
            </tr>
            <tr v-if="!data.detail.length"><td colspan="7" class="px-4 py-3 text-slate-400">برای این روز چیزی ثبت نشده.</td></tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>
