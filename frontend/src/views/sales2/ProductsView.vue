<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { sales2Api, type ProductRow } from "@/api/sales2";
import ExcelImport from "@/components/ExcelImport.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import Skeleton from "@/components/Skeleton.vue";
import { apiError } from "@/components/crm/formError";
import { toast } from "@/composables/useUi";
import { MONTH_NAMES, toJalali } from "@/utils/jalali";

/**
 * کالاها — one row per product for the chosen Jalali month: whether it is on
 * sale (off = gone from every dropdown), a roll's size, the list price in
 * force and the فی حسابداری in force.
 *
 * Roll prices are read from that month's price list and edited there; a
 * non-roll's fixed price is edited here. Costs are edited here per cell (the
 * month's cost) or imported from accounting's Excel with a preview. A value
 * carried from an earlier month says which month it came from.
 */
const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));
const cell = "w-full bg-slate-100 rounded-lg px-2 py-1 text-xs text-ink outline-none focus:ring-2 focus:ring-slate-300";

const now = toJalali(new Date());
const year = ref(now.jy);
const month = ref(now.jm);
const monthKey = computed(() => year.value * 100 + month.value);
const monthLabel = (m: number | null) => (m ? `${MONTH_NAMES[(m % 100) - 1]} ${FA.format(Math.floor(m / 100)).replace(/٬/g, "")}` : "");

const rows = ref<ProductRow[]>([]);
const loading = ref(true);
const error = ref("");
const q = ref("");
const filter = ref<"" | "sellable" | "off" | "cost" | "price">("sellable");
const draft = ref<Record<string, string>>({});
const k = (p: number, what: string) => `${p}:${what}`;

async function load() {
  loading.value = true;
  try {
    const data = await sales2Api.products({
      q: q.value.trim(), year: year.value, month: month.value,
      missing: filter.value === "cost" || filter.value === "price" ? filter.value : "",
    });
    let list = data.rows;
    if (filter.value === "sellable") list = list.filter((r) => r.is_sellable);
    if (filter.value === "off") list = list.filter((r) => !r.is_sellable);
    rows.value = list;
    const d: Record<string, string> = {};
    for (const r of list) {
      for (const [g, c] of Object.entries(r.costs)) d[k(r.id, `c${g}`)] = c.cost_rial ?? "";
      if (!r.is_roll) {
        d[k(r.id, "po")] = r.prices["0"]?.official ?? "";
        d[k(r.id, "pu")] = r.prices["0"]?.unofficial ?? "";
      }
    }
    draft.value = d;
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}
let timer: ReturnType<typeof setTimeout> | undefined;
watch(q, () => { clearTimeout(timer); timer = setTimeout(load, 300); });
watch([filter, year, month], load);
onMounted(load);

async function toggle(r: ProductRow) {
  try {
    await sales2Api.saveProfile(r.id, { is_sellable: !r.is_sellable });
    r.is_sellable = !r.is_sellable;
  } catch (e) { error.value = apiError(e); }
}

async function saveCost(r: ProductRow, g: string) {
  const v = draft.value[k(r.id, `c${g}`)];
  if ((r.costs[g].cost_rial ?? "") === (v ?? "")) return;
  try {
    await sales2Api.saveCost(r.id, Number(g), v || "0", year.value, month.value);
    r.costs[g] = { cost_rial: v || "0", month: monthKey.value };
    toast.success(`فی ${r.name_fa} برای ${monthLabel(monthKey.value)} ذخیره شد.`);
  } catch (e) { error.value = apiError(e); }
}

async function savePrice(r: ProductRow, official: boolean) {
  const v = draft.value[k(r.id, official ? "po" : "pu")];
  const cur = official ? r.prices["0"]?.official : r.prices["0"]?.unofficial;
  if ((cur ?? "") === (v ?? "")) return;
  try {
    await sales2Api.savePriceItem(r.id, official, v || "0", year.value, month.value);
    r.prices["0"] = { ...r.prices["0"], [official ? "official" : "unofficial"]: v || "0" };
    toast.success(`قیمت ${r.name_fa} برای ${monthLabel(monthKey.value)} ذخیره شد.`);
  } catch (e) { error.value = apiError(e); }
}

const years = computed(() => [now.jy - 1, now.jy, now.jy + 1]);
const carried = (m: number | null) => m && m !== monthKey.value;
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
      <input v-model="q" placeholder="نام یا کد کالا…" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none flex-1 min-w-[160px]" />
      <select v-model="filter" class="bg-slate-100 rounded-xl px-3 py-2 text-sm outline-none">
        <option value="sellable">کالاهای فعال</option>
        <option value="off">غیرفعال‌ها</option>
        <option value="">همه</option>
        <option value="cost">بدون فی حسابداری</option>
        <option value="price">بدون قیمت</option>
      </select>
      <ExcelImport import-key="sales2-costs" label="اکسل فی حسابداری" :year="year" :month="month" @done="load" />
      <ExcelImport import-key="sales2-fixed-prices" label="اکسل قیمت غیررول" :year="year" :month="month" @done="load" />
      <span class="text-xs text-slate-400">{{ FA.format(rows.length) }} کالا</span>
    </div>

    <p class="text-xs text-slate-500 px-1">
      قیمت رول‌ها از لیست قیمت {{ monthLabel(monthKey) }} (پله‌ی ۲۰۰ رول) خوانده می‌شود و در صفحه‌ی «لیست قیمت» عوض می‌شود؛ قیمت کالاهای غیررول همین‌جا.
      کالای غیرفعال در فاکتور و پیش‌فاکتور دیده نمی‌شود.
    </p>

    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line">{{ error }}</p>
    <div v-if="loading"><Skeleton class="h-64 rounded-card" /></div>
    <div v-else class="bg-surface rounded-card shadow-soft overflow-x-auto">
      <table class="w-full text-sm min-w-[980px]">
        <thead>
          <tr class="text-xs text-slate-400 bg-slate-50">
            <th class="text-right font-medium px-3 py-2 w-14">فعال</th>
            <th class="text-right font-medium px-2">کالا</th>
            <th class="text-right font-medium px-2">گرماژ</th>
            <th class="text-right font-medium px-2">قیمت رسمی</th>
            <th class="text-right font-medium px-2">قیمت غیررسمی</th>
            <th class="text-right font-medium px-2 w-40">فی حسابداری</th>
            <th class="text-right font-medium px-2">سود رسمی</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="r in rows" :key="r.id">
            <tr v-for="(g, gi) in Object.keys(r.costs)" :key="`${r.id}:${g}`" class="border-t border-slate-100" :class="!r.is_sellable ? 'opacity-50' : ''">
              <td v-if="gi === 0" :rowspan="Object.keys(r.costs).length" class="px-3 align-top pt-2">
                <input type="checkbox" :checked="r.is_sellable" @change="toggle(r)" />
              </td>
              <td v-if="gi === 0" :rowspan="Object.keys(r.costs).length" class="px-2 align-top pt-1.5">
                <p class="text-ink">{{ r.name_fa }}</p>
                <p class="text-[11px] text-slate-400">
                  <template v-if="r.is_roll">رول {{ r.width_mm }}×{{ r.length_m }}{{ r.is_printed ? " · چاپی" : "" }}</template>
                  <template v-else>{{ r.unit_label }}{{ r.category ? ` · ${r.category}` : "" }}</template>
                </p>
              </td>
              <td class="px-2 text-xs text-slate-500">{{ g === "0" ? "—" : `${FA.format(Number(g))} گرم` }}</td>
              <template v-if="r.is_roll">
                <td class="px-2 ltr-nums">{{ r.prices[g]?.official ? fa(r.prices[g].official) : "—" }}</td>
                <td class="px-2 ltr-nums">{{ r.prices[g]?.unofficial ? fa(r.prices[g].unofficial) : "—" }}</td>
              </template>
              <template v-else>
                <td class="px-2 py-1"><MoneyInput v-model="draft[k(r.id, 'po')]" :class="cell" @focusout="savePrice(r, true)" /></td>
                <td class="px-2 py-1"><MoneyInput v-model="draft[k(r.id, 'pu')]" :class="cell" @focusout="savePrice(r, false)" /></td>
              </template>
              <td class="px-2 py-1">
                <MoneyInput v-model="draft[k(r.id, `c${g}`)]" :class="[cell, !r.costs[g].cost_rial ? 'ring-1 ring-amber-300' : '']" @focusout="saveCost(r, g)" />
                <span v-if="carried(r.costs[g].month)" class="text-[10px] text-slate-400">از {{ monthLabel(r.costs[g].month) }}</span>
              </td>
              <td class="px-2 text-xs ltr-nums">
                <template v-if="r.prices[g]?.official && r.costs[g].cost_rial">
                  <span :class="Number(r.prices[g].official) < Number(r.costs[g].cost_rial) ? 'text-red-600' : 'text-emerald-600'">
                    {{ FA.format(Math.round(((Number(r.prices[g].official) / Number(r.costs[g].cost_rial)) - 1) * 1000) / 10) }}٪
                  </span>
                </template>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
