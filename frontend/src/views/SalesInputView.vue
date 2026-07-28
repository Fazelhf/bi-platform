<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { salesApi } from "@/api/sales";
import { salesInputApi, type SalesInput } from "@/api/salesInput";
import type { MonthProgress } from "@/types";
import { toast, confirm } from "@/composables/useUi";
import { num, pct, rial } from "@/utils/format";
import { selectIfZero } from "@/utils/inputs";
import MoneyInput from "@/components/MoneyInput.vue";
import ExportActions from "@/components/ExportActions.vue";
import PeriodCalendar from "@/components/PeriodCalendar.vue";

// Rial money fields get thousands-grouping while typing; counts stay plain.
const isMoney = (field: string) => field.endsWith("_rial");

// Targets belong to the CEO's «تارگت» section and are stored per month in
// their own table. This sheet never writes them — for anyone, CEO included —
// so they are shown read-only here rather than as an input that would look
// editable and then silently discard what was typed.
const isLocked = (field: string) =>
  (data.value?.readonly_fields ?? []).includes(field);

const props = withDefaults(defineProps<{ channel?: string; title?: string }>(), {
  channel: "team",
  title: "ورود اطلاعات فروش",
});

const periods = ref<{ id: number; label: string }[]>([]);
const selectedMonth = ref<number | null>(null);
const data = ref<SalesInput | null>(null);
const loading = ref(true);
const saving = ref("");

// When the month is split into weeks the sheet is filled in one week at a
// time; the month itself then holds no figures of its own.
const progress = ref<MonthProgress | null>(null);
const selectedWeek = ref<number | null>(null);
const weeks = computed(() => progress.value?.weeks ?? []);
const isWeekly = computed(() => weeks.value.length > 1);
// The period the sheet actually reads and writes.
const selectedPeriod = computed(() =>
  isWeekly.value ? selectedWeek.value : selectedMonth.value,
);

const showCalendar = ref(false);
const selectedWeekSeq = computed(
  () => weeks.value.find((w) => w.id === selectedWeek.value)?.seq ?? null,
);
/** Which days of the month the week being filled in covers. */
const currentWeek = computed(() =>
  progress.value?.calendar.weeks.find((w) => w.seq === selectedWeekSeq.value) ?? null,
);
function pickWeekBySeq(seq: number) {
  const match = weeks.value.find((w) => w.seq === seq);
  if (match) selectedWeek.value = match.id;
}

// ---- Add-salesperson picker (choose an existing person first, else new) ----
const allEmployees = ref<{ id: number; full_name_fa: string; team_name?: string }[]>([]);
const showAdd = ref(false);
const pickId = ref<number | "new" | "">("");
const newName = ref("");
// Names already used as columns in the current table — hide them from the list.
const usedNames = computed(() => new Set((data.value?.columns ?? []).map((c) => String(c.name).trim())));
const pickableEmployees = computed(() =>
  allEmployees.value.filter((e) => !usedNames.value.has(e.full_name_fa.trim())),
);

// Live جمع (sum) per metric row across all salesperson columns.
function rowTotal(field: string): number {
  return (data.value?.columns ?? []).reduce((s, c) => s + Number(c[field] || 0), 0);
}

async function loadMonth() {
  if (!selectedMonth.value) return;
  try {
    progress.value = await salesApi.monthProgress(selectedMonth.value);
  } catch {
    progress.value = null;
  }
  // Land on the first week that still needs filling in, else the last one.
  if (isWeekly.value) {
    const next = weeks.value.find((w) => w.state === "empty") ?? weeks.value[weeks.value.length - 1];
    selectedWeek.value = next?.id ?? null;
  } else {
    selectedWeek.value = null;
  }
}

async function load() {
  if (!selectedPeriod.value) return;
  loading.value = true;
  try {
    data.value = await salesInputApi.get(selectedPeriod.value, props.channel);
  } finally {
    loading.value = false;
  }
}

function openAddPicker() {
  pickId.value = "";
  newName.value = "";
  showAdd.value = true;
}

function addColumn(employeeId: number | null, name: string) {
  const blank: Record<string, any> = { employee_id: employeeId, name: name.trim(), status: "draft" };
  for (const m of data.value!.metric_rows) blank[m.field] = "0";
  data.value!.columns.push(blank);
}

function confirmAdd() {
  if (pickId.value === "new") {
    if (!newName.value.trim()) return;
    addColumn(null, newName.value);
  } else if (typeof pickId.value === "number") {
    const emp = allEmployees.value.find((e) => e.id === pickId.value);
    if (!emp) return;
    addColumn(emp.id, emp.full_name_fa);
  } else {
    return; // nothing chosen
  }
  showAdd.value = false;
}

async function removeSalesperson(i: number) {
  const c = data.value!.columns[i];
  if (await confirm({ title: "حذف فروشنده", message: `ستون «${c.name}» از این دوره حذف شود؟`, danger: true })) {
    data.value!.columns.splice(i, 1);
  }
}

// ---- Province block -------------------------------------------------------
// All 31 provinces are always listed, because any of them may get its first
// sale this month. The previous layout repeated the "فروش (ریال)" and
// "تارگت ماهانه" captions once per province — 62 labels and a 2,200px wall to
// scroll past. They are column headers, so they are written once, and the
// list is split across two aligned tables to halve the height.
const provinceSearch = ref("");
const onlyWithSales = ref(false);

const visibleProvinces = computed(() => {
  const q = provinceSearch.value.trim();
  let all = data.value?.provinces ?? [];
  if (q) all = all.filter((p) => p.name.includes(q));
  if (onlyWithSales.value) all = all.filter((p) => Number(p.sales_rial || 0) > 0);
  return all;
});

/** Two balanced columns, so the section is half as tall on a wide screen. */
const provinceColumns = computed(() => {
  const list = visibleProvinces.value;
  const half = Math.ceil(list.length / 2);
  return [list.slice(0, half), list.slice(half)].filter((c) => c.length);
});

const provinceTotals = computed(() => {
  const all = data.value?.provinces ?? [];
  const sales = all.reduce((s, p) => s + Number(p.sales_rial || 0), 0);
  const target = all.reduce((s, p) => s + Number(p.target_rial || 0), 0);
  return {
    sales,
    target,
    filled: all.filter((p) => Number(p.sales_rial || 0) > 0).length,
    achievement: target ? (sales / target) * 100 : 0,
  };
});

function provinceAchievement(p: { sales_rial: any; target_rial: any }): number | null {
  const t = Number(p.target_rial || 0);
  return t ? (Number(p.sales_rial || 0) / t) * 100 : null;
}

async function save(submit: boolean) {
  saving.value = submit ? "در حال ارسال…" : "در حال ذخیره…";
  try {
    await salesInputApi.save({
      period: selectedPeriod.value,
      channel: props.channel,
      submit,
      columns: data.value!.columns,
      provinces: data.value!.provinces,
    });
    saving.value = "";
    toast.success(submit ? "برای تایید مدیرعامل ارسال شد." : "پیش‌نویس ذخیره شد.");
    // Refresh the strip so this week's dot changes colour.
    await loadMonth();
    if (submit) await load();
  } catch (e: any) {
    saving.value = "";
    toast.error(e?.response?.status === 403 ? "دسترسی ندارید." : "ذخیره نشد.");
  }
}

onMounted(async () => {
  periods.value = await salesApi.periods();
  selectedMonth.value = periods.value[0]?.id ?? null;
  await loadMonth();
  await load();
  try {
    allEmployees.value = await salesApi.employees();
  } catch {
    allEmployees.value = [];
  }
});
watch([selectedMonth, () => props.channel], async () => {
  await loadMonth();
  await load();
});
watch(selectedWeek, load);
</script>

<template>
  <div class="space-y-4 pb-8">
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-lg font-bold text-ink">{{ title }}</h2>
        <p class="text-xs text-slate-400 mt-0.5">
          هر فروشنده یک ستون است. می‌توانید فروشنده اضافه یا حذف کنید؛ ستون «جمع» خودکار محاسبه می‌شود.
        </p>
      </div>
      <div class="flex items-center gap-3">
        <span class="text-sm" :class="saving.startsWith('خطا') ? 'text-red-500' : 'text-accent-600'">{{ saving }}</span>
        <ExportActions :excel="false" />
        <select v-model.number="selectedMonth" class="bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm">
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <!-- Week picker + calendar: only when this month is recorded weekly -->
    <div v-if="isWeekly" class="bg-surface rounded-card shadow-soft p-3 space-y-3">
     <div class="flex items-center gap-2 flex-wrap">
      <span class="text-xs text-slate-500 px-1">هفته:</span>
      <button
        v-for="w in weeks"
        :key="w.id"
        class="px-3 py-1.5 rounded-xl text-sm transition-colors flex items-center gap-1.5"
        :class="selectedWeek === w.id
          ? 'bg-panel text-white'
          : 'bg-slate-50 hover:bg-slate-100 text-slate-600'"
        :title="`${w.days} روز`"
        @click="selectedWeek = w.id"
      >
        <span
          class="w-2 h-2 rounded-full"
          :class="{
            'bg-accent-500': w.state === 'approved',
            'bg-amber-400': w.state === 'submitted',
            'bg-brand-500': w.state === 'draft',
            'bg-slate-300': w.state === 'empty',
          }"
        ></span>
        هفته {{ w.seq }}
      </button>
      <span v-if="progress" class="text-xs text-slate-400 mr-auto">
        {{ progress.entered }} از {{ progress.total }} هفته ثبت شده
      </span>
      <button
        class="text-xs text-brand-600 hover:underline"
        @click="showCalendar = !showCalendar"
      >{{ showCalendar ? "بستن تقویم" : "نمایش تقویم" }}</button>
     </div>

     <!-- Which days does the selected week actually cover? -->
     <div v-if="showCalendar" class="border-t border-slate-100 pt-3">
       <PeriodCalendar
         :calendar="progress?.calendar ?? null"
         :selected-week="selectedWeekSeq"
         @pick="pickWeekBySeq"
       />
     </div>

     <p v-else-if="currentWeek" class="text-xs text-slate-500 px-1">
       در حال ثبت
       <span class="font-medium text-ink">هفته {{ currentWeek.seq }}</span>
       — روزهای
       <span class="ltr-nums font-medium text-ink">
         {{ currentWeek.first_day }} تا {{ currentWeek.last_day }}
       </span>
       {{ periods.find(p => p.id === selectedMonth)?.label }}
       ({{ currentWeek.days }} روز)
     </p>
    </div>

    <div v-if="loading || !data" class="text-slate-400">در حال بارگذاری…</div>

    <template v-else>
      <!-- Main table: metrics as rows, salespeople as columns -->
      <section class="bg-surface rounded-card shadow-soft p-5">
        <div class="flex items-center justify-between mb-2">
          <h3 class="font-bold text-ink">جدول عملکرد فروشندگان</h3>
          <button class="text-sm bg-accent-500 hover:bg-accent-600 text-white rounded-xl px-3 py-1.5 transition-colors" @click="openAddPicker">
            + افزودن فروشنده
          </button>
        </div>
        <p class="text-xs text-slate-400 mb-4 leading-6">
          ردیف «تارگت فروش» ماهانه است و در بخش «تارگت» تعیین می‌شود؛
          {{ isWeekly ? "در همه‌ی هفته‌های این ماه یکسان دیده می‌شود" : "اینجا فقط برای مقایسه نمایش داده می‌شود" }}.
          بقیه‌ی ردیف‌ها را شما پر می‌کنید.
        </p>
        <div class="overflow-x-auto">
          <table class="text-sm border-separate" style="border-spacing: 0">
            <thead>
              <tr>
                <th class="text-right font-medium text-slate-500 py-2 px-3 sticky right-0 bg-surface z-10 min-w-[150px]">شاخص</th>
                <th v-for="(c, i) in data.columns" :key="i" class="font-medium py-2 px-2 min-w-[130px]">
                  <div class="flex items-center justify-center gap-1">
                    <input
                      v-model="c.name"
                      class="w-24 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1 text-center text-xs outline-none"
                    />
                    <button class="text-red-400 hover:text-red-600 text-xs" title="حذف ستون" @click="removeSalesperson(i)">✕</button>
                  </div>
                </th>
                <th class="font-medium py-2 px-3 text-accent-600 min-w-[130px] sticky left-0 bg-surface z-20 border-r border-slate-100">جمع</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in data.metric_rows" :key="m.field" class="border-t border-slate-50">
                <td class="py-1.5 px-3 font-medium whitespace-nowrap sticky right-0 bg-surface z-10">
                  {{ m.label }}
                  <span
                    v-if="isLocked(m.field)"
                    class="text-[10px] text-slate-400 font-normal"
                  >(ماهانه — توسط مدیرعامل)</span>
                </td>
                <td v-for="(c, i) in data.columns" :key="i" class="py-1 px-1">
                  <div
                    v-if="isLocked(m.field)"
                    class="w-full px-2 py-1.5 text-center ltr-nums text-slate-500 bg-slate-100/60 rounded-lg cursor-not-allowed"
                    title="تارگت توسط مدیرعامل تعیین می‌شود"
                  >{{ num(Number(c[m.field] || 0)) }}</div>
                  <MoneyInput
                    v-else-if="isMoney(m.field)"
                    v-model="c[m.field]"
                    class="w-full bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                  />
                  <input
                    v-else
                    v-model="c[m.field]" type="number" step="any"
                    class="w-full bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                  @focus="selectIfZero"
                    />
                </td>
                <td class="sum-cell py-1.5 px-3 text-center font-bold ltr-nums sticky left-0 z-20 border-r border-slate-100">
                  {{ num(rowTotal(m.field)) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!data.columns.length" class="text-sm text-slate-400 text-center py-6">
          هنوز فروشنده‌ای اضافه نشده. با دکمه «افزودن فروشنده» شروع کنید.
        </p>
      </section>

      <!-- Province block -->
      <section class="bg-surface rounded-card shadow-soft p-5">
        <div class="flex items-start justify-between gap-3 flex-wrap mb-3">
          <div>
            <h3 class="font-bold text-ink">فروش به تفکیک استان</h3>
            <p class="text-xs text-slate-400 mt-1 max-w-xl leading-5">
              فقط برای استان‌هایی که فروش داشته‌اید مبلغ وارد کنید؛ بقیه صفر بماند.
              این ارقام فقط مربوط به «{{ title.replace("ورود اطلاعات ", "") }}» است و از
              سایر کانال‌های فروش جداست. تارگت ماهانه است و در بخش «تارگت» تعیین می‌شود.
            </p>
          </div>
          <div class="flex items-center gap-2">
            <button
              class="text-xs rounded-xl px-3 py-1.5 border transition-colors"
              :class="onlyWithSales
                ? 'bg-panel text-white border-panel'
                : 'bg-surface text-slate-500 border-slate-200 hover:bg-slate-50'"
              @click="onlyWithSales = !onlyWithSales"
            >فقط دارای فروش</button>
            <input
              v-model="provinceSearch"
              placeholder="جستجوی استان…"
              class="bg-slate-50 border border-slate-200 rounded-xl px-3 py-1.5 text-sm w-40 focus:outline-none focus:ring-2 focus:ring-accent-500/30 transition"
            />
          </div>
        </div>

        <!-- Running totals: what has been entered, against the CEO's plan -->
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <div class="bg-slate-50 rounded-xl px-3 py-2">
            <p class="text-[11px] text-slate-400">مجموع فروش واردشده</p>
            <p class="text-sm font-bold text-ink ltr-nums">{{ rial(provinceTotals.sales) }}</p>
          </div>
          <div class="bg-slate-50 rounded-xl px-3 py-2">
            <p class="text-[11px] text-slate-400">مجموع تارگت</p>
            <p class="text-sm font-bold text-slate-500 ltr-nums">{{ rial(provinceTotals.target) }}</p>
          </div>
          <div class="bg-slate-50 rounded-xl px-3 py-2">
            <p class="text-[11px] text-slate-400">تحقق</p>
            <p
              class="text-sm font-bold ltr-nums"
              :class="provinceTotals.achievement >= 100 ? 'text-green-600'
                : provinceTotals.achievement >= 70 ? 'text-amber-600' : 'text-red-500'"
            >{{ pct(provinceTotals.achievement) }}</p>
          </div>
          <div class="bg-slate-50 rounded-xl px-3 py-2">
            <p class="text-[11px] text-slate-400">استان‌های پرشده</p>
            <p class="text-sm font-bold text-ink ltr-nums">{{ num(provinceTotals.filled) }} از {{ num(data.provinces.length) }}</p>
          </div>
        </div>

        <!-- Two aligned tables: the captions are column headers, written once.
             lg, not xl: the sidebar eats 256px, so on a 1440px laptop the
             content is ~1150px and an xl breakpoint would never fire. -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-x-8 gap-y-2">
          <table v-for="(col, ci) in provinceColumns" :key="ci" class="w-full text-sm">
            <thead>
              <tr class="text-[11px] text-slate-400 border-b border-slate-100">
                <th class="text-right font-medium pb-2">استان</th>
                <th class="text-left font-medium pb-2 w-36">فروش (ریال)</th>
                <th class="text-left font-medium pb-2 w-32">تارگت ماهانه</th>
                <th class="text-left font-medium pb-2 w-16">تحقق</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="p in col" :key="p.province_id"
                class="border-b border-slate-50 last:border-0"
                :class="Number(p.sales_rial || 0) > 0 ? 'bg-accent-500/5' : ''"
              >
                <td class="py-1 text-slate-600 whitespace-nowrap">{{ p.name }}</td>
                <td class="py-1">
                  <MoneyInput
                    v-model="p.sales_rial" placeholder="۰"
                    class="w-full bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1.5 text-left ltr-nums outline-none"
                  />
                </td>
                <td class="py-1 text-left ltr-nums text-slate-400 px-2" title="در بخش «تارگت» تعیین می‌شود">
                  {{ num(Number(p.target_rial || 0)) }}
                </td>
                <td class="py-1 text-left ltr-nums px-1">
                  <span
                    v-if="provinceAchievement(p) !== null"
                    :class="provinceAchievement(p)! >= 100 ? 'text-green-600'
                      : provinceAchievement(p)! >= 70 ? 'text-amber-600' : 'text-red-500'"
                  >{{ pct(provinceAchievement(p)!) }}</span>
                  <span v-else class="text-slate-300">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!visibleProvinces.length" class="text-sm text-slate-400 py-3">
          {{ onlyWithSales ? "هنوز برای هیچ استانی فروش وارد نشده است." : "استانی با این نام پیدا نشد." }}
        </p>
      </section>

      <!-- Sticky action bar -->
      <div class="sticky bottom-4 bg-panel text-white rounded-card shadow-pop p-3 flex items-center justify-between">
        <span class="text-sm text-white/70 px-2">پس از تکمیل، برای تایید مدیرعامل ارسال کنید.</span>
        <div class="flex gap-2">
          <button class="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/20 text-sm transition-colors" @click="save(false)">ذخیره پیش‌نویس</button>
          <button class="px-5 py-2 rounded-xl bg-accent-500 hover:bg-accent-600 text-sm font-medium transition-colors" @click="save(true)">ذخیره و ارسال برای تایید</button>
        </div>
      </div>
    </template>

    <!-- Add-salesperson picker: choose an existing person first, else add new -->
    <div
      v-if="showAdd"
      class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4"
      @click.self="showAdd = false"
    >
      <div class="bg-surface rounded-card shadow-pop w-full max-w-sm p-6 animate-pop">
        <h3 class="font-bold text-ink mb-4">افزودن فروشنده</h3>

        <label class="block text-xs text-slate-500 mb-1">انتخاب از فروشندگان موجود</label>
        <select
          v-model="pickId"
          class="w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface focus:outline-none focus:ring-2 focus:ring-accent-500/30 transition mb-3"
        >
          <option value="">— یک فروشنده را انتخاب کنید —</option>
          <option v-for="e in pickableEmployees" :key="e.id" :value="e.id">
            {{ e.full_name_fa }}{{ e.team_name ? ` — ${e.team_name}` : "" }}
          </option>
          <option value="new">➕ فروشنده جدید…</option>
        </select>

        <div v-if="pickId === 'new'" class="mb-1">
          <label class="block text-xs text-slate-500 mb-1">نام فروشنده جدید</label>
          <input
            v-model="newName"
            placeholder="نام و نام خانوادگی"
            class="w-full border border-slate-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500/30 transition"
            @keyup.enter="confirmAdd"
          />
        </div>
        <p v-else-if="!pickableEmployees.length" class="text-xs text-slate-400">
          همه‌ی فروشندگان موجود قبلاً در جدول هستند. برای افزودن، «فروشنده جدید» را انتخاب کنید.
        </p>

        <div class="flex justify-end gap-2 pt-5">
          <button class="px-4 py-2 text-sm rounded-lg hover:bg-slate-100 transition-colors" @click="showAdd = false">انصراف</button>
          <button
            class="px-4 py-2 text-sm rounded-lg bg-accent-500 text-white hover:bg-accent-600 disabled:opacity-50 transition-colors"
            :disabled="pickId === '' || (pickId === 'new' && !newName.trim())"
            @click="confirmAdd"
          >افزودن</button>
        </div>
      </div>
    </div>
  </div>
</template>
