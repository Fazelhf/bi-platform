<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import api from "@/api/client";
import { toast, confirm } from "@/composables/useUi";

/**
 * «دوره‌ها» — the CEO decides, section by section and month by month, whether
 * figures are recorded once for the month, week by week, or day by day.
 *
 * Each section has its own grain: making فروش همکار weekly no longer makes
 * تولید or مالی weekly too. The calendar underneath is shared and simply goes
 * as deep as the finest section needs.
 *
 * A section that already has figures in a month keeps that month's grain —
 * changing it would mean inventing how a total splits, or folding numbers
 * nobody typed. Such a cell is locked and says why.
 */
type Grain = "month" | "week" | "day";

interface Section {
  department: string;
  label: string;
  grain: Grain;
  locked: boolean;
}
interface MonthRow {
  id: number;
  label: string;
  jalali_year: number;
  jalali_month: number;
  days: number;
  sections: Section[];
}

const GRAIN_LABEL: Record<Grain, string> = { month: "ماهانه", week: "هفتگی", day: "روزانه" };
const GRAINS: Grain[] = ["month", "week", "day"];

const months = ref<MonthRow[]>([]);
const departments = ref<{ key: string; label: string }[]>([]);
const defaults = ref<Record<string, Grain>>({});
const loading = ref(true);
const busy = ref("");
const year = ref<number | null>(null);

const years = computed(() => {
  const y = months.value[0]?.jalali_year ?? year.value ?? 1405;
  return [y - 1, y, y + 1];
});

async function load() {
  loading.value = true;
  try {
    const { data } = await api.get("/sales/periods/grains/", {
      params: year.value ? { year: year.value } : {},
    });
    months.value = data.months;
    departments.value = data.departments;
    defaults.value = data.defaults;
    if (!year.value && data.months.length) year.value = data.months[0].jalali_year;
  } finally {
    loading.value = false;
  }
}

async function setGrain(row: MonthRow, s: Section, grain: Grain) {
  if (s.grain === grain || s.locked) return;
  busy.value = `${row.id}:${s.department}`;
  try {
    await api.post(`/sales/periods/${row.id}/grain/`, { department: s.department, grain });
    s.grain = grain;
    toast.success(`${s.label} · ${row.label}: ${GRAIN_LABEL[grain]}`);
  } catch (e: any) {
    toast.error(e?.response?.data?.detail ?? "تغییر انجام نشد.");
    await load();
  } finally {
    busy.value = "";
  }
}

/** This month and every later one in view, for one section — the usual switch. */
async function fromHere(row: MonthRow, dept: string, grain: Grain) {
  const later = months.value.filter((m) => m.jalali_month >= row.jalali_month);
  const cells = later
    .map((m) => ({ m, s: m.sections.find((x) => x.department === dept)! }))
    .filter(({ s }) => s && !s.locked && s.grain !== grain);
  const label = departments.value.find((d) => d.key === dept)?.label ?? dept;
  if (!cells.length) {
    toast.success("همه‌ی ماه‌های بعد از قبل همین دانه‌بندی را دارند.");
    return;
  }
  const ok = await confirm({
    title: `${label}: ${GRAIN_LABEL[grain]} از ${row.label} به بعد`,
    message: `${cells.length} ماه ${GRAIN_LABEL[grain]} می‌شوند. ماه‌هایی که این بخش در آن‌ها داده دارد دست‌نخورده می‌مانند.`,
  });
  if (!ok) return;
  busy.value = `from:${dept}`;
  try {
    for (const { m, s } of cells) {
      await api.post(`/sales/periods/${m.id}/grain/`, { department: dept, grain });
      s.grain = grain;
    }
    toast.success(`${cells.length} ماه ${GRAIN_LABEL[grain]} شد.`);
  } catch (e: any) {
    toast.error(e?.response?.data?.detail ?? "بخشی از تغییر انجام نشد.");
    await load();
  } finally {
    busy.value = "";
  }
}

async function setDefault(dept: string, grain: Grain) {
  try {
    await api.post("/sales/periods/grain-defaults/", { department: dept, grain });
    defaults.value[dept] = grain;
    toast.success("پیش‌فرض ماه‌های جدید ذخیره شد.");
  } catch (e: any) {
    toast.error(e?.response?.data?.detail ?? "ذخیره نشد.");
  }
}

async function pickYear(y: number) {
  year.value = y;
  await load();
}

onMounted(load);
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-baseline justify-between flex-wrap gap-2">
      <div>
        <h2 class="font-bold text-ink">دوره‌های ثبت اطلاعات</h2>
        <p class="text-xs text-slate-400 mt-1 leading-6">
          برای هر بخش جداگانه تعیین کنید اطلاعات ماهانه، هفتگی یا روزانه ثبت شود.
          تغییر یک بخش روی بخش‌های دیگر اثری ندارد. تارگت‌ها همیشه ماهانه‌اند.
        </p>
      </div>
      <div class="flex bg-slate-100 rounded-xl p-0.5">
        <button
          v-for="y in years" :key="y"
          class="px-3 py-1 rounded-lg text-xs ltr-nums"
          :class="year === y ? 'bg-surface shadow-soft text-ink font-medium' : 'text-slate-500 hover:text-ink'"
          @click="pickYear(y)"
        >{{ y }}</button>
      </div>
    </div>

    <!-- Defaults for months not set yet -->
    <div class="bg-surface rounded-card shadow-soft p-3">
      <p class="text-xs font-semibold text-slate-500 mb-2">پیش‌فرض ماه‌های جدید</p>
      <div class="flex flex-wrap gap-3">
        <label v-for="d in departments" :key="d.key" class="flex items-center gap-2 text-xs text-slate-600">
          {{ d.label }}
          <select
            class="border border-slate-200 rounded-lg px-2 py-1 bg-surface text-xs"
            :value="defaults[d.key]"
            @change="setDefault(d.key, ($event.target as HTMLSelectElement).value as Grain)"
          >
            <option v-for="g in GRAINS" :key="g" :value="g">{{ GRAIN_LABEL[g] }}</option>
          </select>
        </label>
      </div>
    </div>

    <div v-if="loading" class="text-slate-400 text-sm">در حال بارگذاری…</div>

    <div v-else-if="!months.length" class="text-slate-400 text-sm">برای این سال ماهی تعریف نشده است.</div>

    <div v-else class="bg-surface rounded-card shadow-soft overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-slate-400 border-b border-slate-100 text-xs">
            <th class="text-right font-medium p-3">ماه</th>
            <th v-for="d in departments" :key="d.key" class="text-center font-medium p-3 whitespace-nowrap">
              {{ d.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in months" :key="row.id" class="border-b border-slate-50">
            <td class="p-3 font-medium text-ink whitespace-nowrap">{{ row.label }}</td>
            <td v-for="s in row.sections" :key="s.department" class="p-2 text-center">
              <div
                class="inline-flex bg-slate-100 rounded-xl p-0.5"
                :title="s.locked ? 'این بخش در این ماه داده دارد؛ دانه‌بندی قابل تغییر نیست.' : ''"
              >
                <button
                  v-for="g in GRAINS" :key="g"
                  class="px-2 py-1 rounded-lg text-[11px] transition-colors disabled:cursor-not-allowed"
                  :class="[
                    s.grain === g ? 'bg-surface shadow-soft text-ink font-medium' : 'text-slate-500 hover:text-ink',
                    s.locked && s.grain !== g ? 'opacity-30' : '',
                  ]"
                  :disabled="s.locked || busy === `${row.id}:${s.department}` || busy.startsWith('from:')"
                  @click="setGrain(row, s, g)"
                >{{ GRAIN_LABEL[g] }}</button>
              </div>
              <div class="mt-1 flex justify-center gap-2 text-[10px]">
                <span v-if="s.locked" class="text-amber-600">دارای داده 🔒</span>
                <button
                  v-else
                  class="text-slate-400 hover:text-brand-600 hover:underline"
                  :disabled="busy.startsWith('from:')"
                  @click="fromHere(row, s.department, s.grain)"
                >همین از این ماه به بعد</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
