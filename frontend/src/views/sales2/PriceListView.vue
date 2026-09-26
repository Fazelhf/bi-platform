<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { sales2Api, type PriceSheet } from "@/api/sales2";
import ExcelImport from "@/components/ExcelImport.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import { apiError } from "@/components/crm/formError";
import { toast } from "@/composables/useUi";
import { MONTH_NAMES, toJalali } from "@/utils/jalali";

/**
 * لیست قیمت — one list per Jalali month, the company workbook's four sheets
 * and its formula:
 *
 *   قیمت هر رول = عرض × متراژ × فی ۰۲ × ضریب ÷ ۱۰۰۰ + اجرت برش
 *
 * A document is priced from the list of the month it is dated in. A month
 * without its own list uses the latest earlier one; to change prices for the
 * month, copy that list into it (or import the month's workbook) and edit.
 * Export writes the same workbook back, formulas included.
 */
const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));
const cell = "w-full bg-slate-100 rounded-lg px-2 py-1 text-xs text-ink outline-none focus:ring-2 focus:ring-slate-300";

const now = toJalali(new Date());
const year = ref(now.jy);
const month = ref(now.jm);
const monthLabel = (y: number, m: number) => `${MONTH_NAMES[m - 1]} ${FA.format(y).replace(/٬/g, "")}`;

const sheets = ref<PriceSheet[]>([]);
const active = ref<number | null>(null);
const loading = ref(true);
const busy = ref(false);
const error = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    sheets.value = (await sales2Api.priceMonth(year.value, month.value)).sheets;
    if (!sheets.value.some((s) => s.id === active.value)) active.value = sheets.value[0]?.id ?? null;
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}
watch([year, month], load);
onMounted(load);

const sheet = computed(() => sheets.value.find((s) => s.id === active.value) ?? null);
const ownMonth = computed(() => sheets.value.length > 0 && sheets.value.every((s) => s.is_own_month));

function price(width: number, length: number, cut: string, waste: string | null, pct: number): number {
  const s = sheet.value!;
  const w = Number(waste ?? s.waste_pct) / 100;
  return Math.round(((width * length * Number(s.base_fi_rial) * w) / 1000 + Number(cut || 0)) * (100 + pct) / 100);
}

async function copyHere() {
  busy.value = true;
  try {
    const kind = sheet.value ? [sheet.value.grammage, sheet.value.is_official] : null;
    sheets.value = (await sales2Api.copyPriceMonth(year.value, month.value)).sheets;
    active.value = sheets.value.find((s) => kind && s.grammage === kind[0] && s.is_official === kind[1])?.id
      ?? sheets.value[0]?.id ?? null;
    toast.success(`لیست قیمت ${monthLabel(year.value, month.value)} ساخته شد؛ حالا ویرایش کنید.`);
  } catch (e) { error.value = apiError(e); }
  finally { busy.value = false; }
}

async function save() {
  if (!sheet.value) return;
  busy.value = true;
  try {
    const s = sheet.value;
    const saved = await sales2Api.savePriceSheet(s.id, {
      base_fi_rial: s.base_fi_rial, waste_pct: s.waste_pct, qty_tiers: s.qty_tiers,
      rows: s.rows.map((r) => ({ ...r, waste_pct: r.waste_pct === "" ? null : r.waste_pct })),
    });
    Object.assign(s, saved, { is_own_month: true });
    toast.success(`«${s.name}» ${monthLabel(year.value, month.value)} ذخیره شد.`);
  } catch (e) { error.value = apiError(e); }
  finally { busy.value = false; }
}

async function exportFile() {
  try {
    const blob = await sales2Api.exportPrices(year.value, month.value);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `لیست-قیمت-${MONTH_NAMES[month.value - 1]}-${year.value}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) { error.value = apiError(e); }
}

function addRow() {
  sheet.value?.rows.push({ width_mm: 57, length_m: 10, cut_fee_rial: "0", print_fee_rial: "0", waste_pct: null, note: "" });
}
const years = computed(() => [now.jy - 1, now.jy, now.jy + 1]);
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <select v-model.number="month" class="bg-slate-100 rounded-xl px-3 py-2 text-sm outline-none">
        <option v-for="(m, i) in MONTH_NAMES" :key="i" :value="i + 1">{{ m }}</option>
      </select>
      <select v-model.number="year" class="bg-slate-100 rounded-xl px-3 py-2 text-sm outline-none">
        <option v-for="y in years" :key="y" :value="y">{{ FA.format(y).replace(/٬/g, "") }}</option>
      </select>
      <div class="flex-1" />
      <ExcelImport import-key="sales2-price-list" label="ورود اکسل لیست قیمت" :year="year" :month="month" @done="load" />
      <button class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-700" :disabled="!sheets.length" @click="exportFile">خروجی اکسل</button>
    </div>

    <div v-if="loading"><Skeleton class="h-64 rounded-card" /></div>
    <EmptyState v-else-if="!sheets.length" title="برای این ماه یا قبل از آن لیست قیمتی نیست" hint="اکسل لیست قیمت را برای این ماه وارد کنید." />
    <template v-else>
      <div v-if="!ownMonth" class="bg-amber-50 text-amber-800 text-sm rounded-xl px-4 py-3 flex flex-wrap items-center gap-3">
        <span>
          {{ monthLabel(year, month) }} لیست قیمت خودش را ندارد؛ لیست
          {{ monthLabel(sheets[0].jalali_year, sheets[0].jalali_month) }} در این ماه اعمال می‌شود.
        </span>
        <button class="rounded-xl px-3 py-1.5 text-sm bg-amber-600 text-white" :disabled="busy" @click="copyHere">
          ساخت لیست {{ monthLabel(year, month) }} از روی آن
        </button>
      </div>

      <div class="flex flex-wrap gap-2">
        <button
          v-for="s in sheets" :key="s.id"
          class="rounded-xl px-4 py-2 text-sm"
          :class="s.id === active ? 'bg-panel text-white' : 'bg-surface shadow-soft text-slate-600'"
          @click="active = s.id"
        >{{ s.name }}</button>
      </div>

      <div v-if="sheet" class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-end gap-4">
        <div>
          <label class="text-xs text-slate-500 mb-1 block">فی ۰۲ (ریال)</label>
          <MoneyInput v-model="sheet.base_fi_rial" :disabled="!sheet.is_own_month" class="bg-slate-100 rounded-xl px-3 py-2 text-lg font-bold text-ink outline-none w-40" />
        </div>
        <div>
          <label class="text-xs text-slate-500 mb-1 block">ضریب ضایعات ٪</label>
          <input v-model="sheet.waste_pct" :disabled="!sheet.is_own_month" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none w-24" inputmode="decimal" />
        </div>
        <div v-for="(t, i) in sheet.qty_tiers" :key="i">
          <label class="text-xs text-slate-500 mb-1 block">{{ t.min_qty ? `از ${FA.format(t.min_qty)} رول` : "کمتر" }} +٪</label>
          <input v-model.number="t.pct" :disabled="!sheet.is_own_month" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none w-20" inputmode="decimal" />
        </div>
        <p class="text-xs text-slate-400 flex-1">لیست {{ monthLabel(sheet.jalali_year, sheet.jalali_month) }}</p>
        <button v-if="sheet.is_own_month" class="bg-panel text-white rounded-xl px-4 py-2 text-sm" :disabled="busy" @click="save">ذخیره</button>
      </div>

      <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">{{ error }}</p>

      <div v-if="sheet" class="bg-surface rounded-card shadow-soft overflow-x-auto">
        <table class="w-full text-sm min-w-[860px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-3 py-2 w-10">ردیف</th>
              <th class="text-right font-medium px-2 w-20">سایز</th>
              <th class="text-right font-medium px-2 w-20">متراژ</th>
              <th class="text-right font-medium px-2 w-28">اجرت برش</th>
              <th class="text-right font-medium px-2 w-28">اجرت چاپ</th>
              <th v-for="t in sheet.qty_tiers" :key="t.min_qty" class="text-right font-medium px-2">{{ t.min_qty ? FA.format(t.min_qty) : "کمتر" }}</th>
              <th class="text-right font-medium px-2">توضیح</th>
              <th class="w-6"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in sheet.rows" :key="i" class="border-t border-slate-100">
              <td class="px-3 py-1 text-xs text-slate-400 ltr-nums">{{ FA.format(i + 1) }}</td>
              <td class="px-2"><input v-model.number="r.width_mm" :class="cell" :disabled="!sheet.is_own_month" inputmode="numeric" /></td>
              <td class="px-2"><input v-model.number="r.length_m" :class="cell" :disabled="!sheet.is_own_month" inputmode="numeric" /></td>
              <td class="px-2"><MoneyInput v-model="r.cut_fee_rial" :class="cell" :disabled="!sheet.is_own_month" /></td>
              <td class="px-2"><MoneyInput v-model="r.print_fee_rial" :class="cell" :disabled="!sheet.is_own_month" /></td>
              <td v-for="t in sheet.qty_tiers" :key="t.min_qty" class="px-2 ltr-nums font-medium text-ink">
                {{ fa(price(r.width_mm, r.length_m, r.cut_fee_rial, r.waste_pct, Number(t.pct))) }}
              </td>
              <td class="px-2"><input v-model="r.note" :class="cell" :disabled="!sheet.is_own_month" /></td>
              <td class="px-2"><button v-if="sheet.is_own_month" class="text-slate-300 hover:text-red-500" @click="sheet.rows.splice(i, 1)">✕</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="sheet.is_own_month" class="p-3 border-t border-slate-100 flex justify-between text-xs text-slate-500">
          <button class="text-sky-600 text-sm" @click="addRow">+ سایز</button>
          <span>برای رول چاپی، اجرت چاپ به قیمت اضافه می‌شود.</span>
        </div>
      </div>
    </template>
  </div>
</template>
