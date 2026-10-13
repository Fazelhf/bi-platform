<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  sales2Api, type LedgerBookFilter, type LedgerReport, type LedgerRow,
} from "@/api/sales2";
import JalaliDateField from "@/components/JalaliDateField.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import { apiError } from "@/components/crm/formError";
import { faDigits, isoToJalali, todayIso } from "@/utils/jalali";
import LedgerImportPanel from "./LedgerImportPanel.vue";
import LedgerAccountPanel from "./LedgerAccountPanel.vue";

/**
 * مطالبات طبق دفتر آرپا — «گزارش وصولی», computed instead of typed.
 *
 * Each customer's آرپا ledger is uploaded once (and again whenever it moves);
 * every دریافت settles the فاکتور its description names, and what is left
 * of each فاکتور is put in the column of its month. دفتر اصلی and دفتر دوم
 * (رول مارکت) are separate books with separate balances; «هر دو» adds them.
 * Every row says whether the computed balance agrees with آرپا's own «مانده».
 */
const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));
const blank = (v: string | null | undefined) => (Number(v ?? 0) ? fa(v) : "");
/** A balance as آرپا prints it: the amount, and «بد» (بدهکار) or «بس» (بستانکار). */
const bal = (v: number | string | null | undefined) => {
  const n = Math.round(Number(v ?? 0));
  return n ? `${FA.format(Math.abs(n))} ${n > 0 ? "بد" : "بس"}` : "۰";
};
const balBlank = (v: string | null | undefined) => (Number(v ?? 0) ? bal(v) : "");
const jd = (iso: string | null | undefined) => {
  const j = iso ? isoToJalali(iso) : null;
  return j ? faDigits(`${j.jy}/${String(j.jm).padStart(2, "0")}/${String(j.jd).padStart(2, "0")}`) : "—";
};

const BOOKS: { key: LedgerBookFilter; label: string }[] = [
  { key: "main", label: "دفتر اصلی" },
  { key: "second", label: "دفتر دوم (رول مارکت)" },
  { key: "all", label: "هر دو دفتر" },
];

const book = ref<LedgerBookFilter>("main");
const asOf = ref(todayIso());
const months = ref(11);
const q = ref("");
const onlyOpen = ref(true);
const data = ref<LedgerReport | null>(null);
const loading = ref(true);
const error = ref("");
const showImport = ref(false);
const selected = ref<LedgerRow | null>(null);
const exporting = ref(false);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    data.value = await sales2Api.ledgerReceivables({
      book: book.value, as_of: asOf.value, months: months.value, q: q.value.trim(), open: onlyOpen.value ? 1 : "",
    });
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

let timer: ReturnType<typeof setTimeout> | undefined;
watch(q, () => { clearTimeout(timer); timer = setTimeout(load, 300); });
watch([book, asOf, months, onlyOpen], () => { selected.value = null; load(); });
onMounted(load);

async function exportXlsx() {
  exporting.value = true;
  try {
    const blob = await sales2Api.ledgerExport({ book: book.value, as_of: asOf.value, months: months.value });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const j = isoToJalali(asOf.value);
    a.download = `گزارش وصولی ${BOOKS.find((b) => b.key === book.value)?.label} ${j ? `${j.jy}${String(j.jm).padStart(2, "0")}${String(j.jd).padStart(2, "0")}` : ""}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    exporting.value = false;
  }
}

/** Accounts behind the selected row: one, or one per book under «هر دو». */
const panelAccounts = computed(() => selected.value?.accounts ?? []);

const tiles = computed(() => {
  const t = data.value?.totals;
  const c = data.value?.counts;
  if (!t || !c) return [];
  const cols = data.value!.columns;
  // Older than three months: «ماه‌های قبل» plus every column before the last three.
  const old = cols.slice(0, Math.max(0, cols.length - 3)).reduce((s, col) => s + Number(t.buckets[col.key] ?? 0), 0);
  return [
    { label: "مانده", value: bal(t.balance), cls: "text-ink" },
    { label: "بیش از سه ماه", value: fa(old), cls: "text-red-600" },
    { label: "پیش دریافت", value: fa(t.prepayment), cls: "text-emerald-600" },
    { label: "دفتر وارد شده", value: `${FA.format(c.with_ledger)} از ${FA.format(c.accounts)}`, cls: "text-sky-600" },
    { label: "ناهماهنگ با آرپا", value: FA.format(c.unreconciled), cls: c.unreconciled ? "text-red-600" : "text-slate-400" },
  ];
});

function diff(r: LedgerRow): number | null {
  if (r.manual_balance === null || !r.has_ledger) return null;
  return Number(r.balance) - Number(r.manual_balance);
}

function pick(r: LedgerRow) {
  selected.value = selected.value?.id === r.id ? null : r;
  if (selected.value) requestAnimationFrame(() => document.getElementById("ledger-panel")?.scrollIntoView({ behavior: "smooth", block: "start" }));
}

function imported() {
  load();
}
</script>

<template>
  <div class="space-y-4">
    <!-- Book · date · actions -->
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <div class="flex rounded-xl bg-slate-100 p-1">
        <button
          v-for="b in BOOKS" :key="b.key"
          class="rounded-lg px-3 py-1.5 text-sm transition"
          :class="book === b.key ? 'bg-white shadow-sm text-ink font-medium' : 'text-slate-500'"
          @click="book = b.key"
        >{{ b.label }}</button>
      </div>
      <div class="flex items-center gap-2 text-sm text-slate-500">
        منتهی به
        <JalaliDateField v-model="asOf" class="w-40" />
      </div>
      <label class="flex items-center gap-1 text-sm text-slate-500">
        ستون ماه
        <select v-model.number="months" class="bg-slate-100 rounded-lg px-2 py-1.5 text-sm text-ink">
          <option v-for="n in [6, 11, 12, 18, 24]" :key="n" :value="n">{{ FA.format(n) }}</option>
        </select>
      </label>
      <span class="flex-1" />
      <button class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-700" @click="showImport = !showImport">
        {{ showImport ? "بستن ورود فایل" : "ورود دفتر حساب / گزارش وصولی" }}
      </button>
      <button class="rounded-xl px-4 py-2 text-sm bg-panel text-white" :disabled="exporting" @click="exportXlsx">
        {{ exporting ? "در حال ساخت…" : "خروجی اکسل گزارش وصولی" }}
      </button>
    </div>

    <LedgerImportPanel v-if="showImport" :book="book === 'all' ? 'main' : book" @imported="imported" />

    <div class="grid grid-cols-2 lg:grid-cols-5 gap-3">
      <div v-for="t in tiles" :key="t.label" class="bg-surface rounded-card shadow-soft p-4">
        <p class="text-xs text-slate-500">{{ t.label }}</p>
        <p class="text-lg font-bold ltr-nums mt-1" :class="t.cls">{{ t.value }}</p>
      </div>
    </div>

    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-3">
      <input
        v-model="q" placeholder="نام مشتری یا کد تفصیل…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none flex-1 min-w-[180px]"
      />
      <label class="flex items-center gap-2 text-sm text-slate-600">
        <input v-model="onlyOpen" type="checkbox" /> فقط مانده‌دار
      </label>
      <span class="text-xs text-slate-400">
        {{ FA.format(data?.rows.length ?? 0) }} طرف حساب · مبالغ به ریال · هر دریافت به فاکتوری که در شرحش آمده، و باقی به قدیمی‌ترین فاکتور باز
      </span>
    </div>

    <LedgerAccountPanel
      v-if="selected" id="ledger-panel" :key="selected.id + book + asOf"
      :accounts="panelAccounts" :customer="selected.customer" :as-of="asOf"
      @close="selected = null" @changed="load"
    />

    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">{{ error }}</p>
    <div v-if="loading && !data" class="space-y-2"><Skeleton v-for="i in 6" :key="i" class="h-10 rounded-xl" /></div>
    <EmptyState
      v-else-if="data && !data.rows.length"
      title="هنوز دفتری وارد نشده"
      hint="خروجی «دفتر حساب» هر مشتری را از آرپا بگیرید و از «ورود دفتر حساب» بارگذاری کنید؛ گزارش وصولی دستی هم توضیحات و بازاریاب را می‌آورد."
    />

    <div v-else-if="data" class="bg-surface rounded-card shadow-soft overflow-x-auto" :class="loading ? 'opacity-60' : ''">
      <table class="w-full text-xs whitespace-nowrap">
        <thead>
          <tr class="text-slate-500 bg-slate-50">
            <th class="text-center font-medium px-2 py-3 sticky right-0 bg-slate-50 z-10">ردیف</th>
            <th class="text-center font-medium px-2">کد تفصیل</th>
            <th class="text-right font-medium px-2 sticky right-8 bg-slate-50 z-10 min-w-[180px]">نام طرف حساب</th>
            <th class="text-center font-medium px-2">تاریخ</th>
            <th v-for="c in data.columns" :key="c.key" class="text-center font-medium px-2">{{ c.label }}</th>
            <th class="text-center font-medium px-2">پیش دریافت</th>
            <th class="text-center font-medium px-2 text-ink">مانده (بد / بس)</th>
            <template v-if="book === 'all'">
              <th class="text-center font-medium px-2">اصلی</th>
              <th class="text-center font-medium px-2">دوم</th>
            </template>
            <th class="text-center font-medium px-2">آرپا</th>
            <th class="text-center font-medium px-2">گزارش دستی</th>
            <th class="text-right font-medium px-2">توضیحات</th>
            <th class="text-center font-medium px-2">بازاریاب</th>
            <th class="text-center font-medium px-2">آخرین ردیف</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(r, i) in data.rows" :key="r.id"
            class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
            :class="selected?.id === r.id ? 'bg-sky-50' : ''"
            @click="pick(r)"
          >
            <td class="px-2 py-2 text-slate-400 sticky right-0 bg-surface">{{ FA.format(i + 1) }}</td>
            <td class="px-2 text-center ltr-nums text-slate-500">{{ r.code ? faDigits(r.code) : "" }}</td>
            <td class="px-2 sticky right-8 bg-surface font-medium text-ink max-w-[240px] truncate" :title="r.name">{{ r.name }}</td>
            <td class="px-2 text-center ltr-nums text-slate-500">{{ r.oldest_open ? jd(r.oldest_open) : "" }}</td>
            <td v-for="c in data.columns" :key="c.key" class="px-2 text-center ltr-nums" :class="c.key === 'before' ? 'text-red-600' : 'text-slate-700'">
              {{ blank(r.buckets[c.key]) }}
            </td>
            <td class="px-2 text-center ltr-nums text-emerald-600">{{ blank(r.prepayment) }}</td>
            <td class="px-2 text-center ltr-nums font-bold" :class="Number(r.balance) > 0 ? 'text-ink' : 'text-emerald-600'">{{ bal(r.balance) }}</td>
            <template v-if="book === 'all'">
              <td class="px-2 text-center ltr-nums text-slate-600">{{ balBlank(r.by_book.main) }}</td>
              <td class="px-2 text-center ltr-nums text-slate-600">{{ balBlank(r.by_book.second) }}</td>
            </template>
            <td class="px-2">
              <span v-if="!r.has_ledger" class="text-amber-600">دفتر وارد نشده</span>
              <span v-else-if="r.reconciled" class="text-emerald-600" title="مانده‌ی محاسبه‌شده با مانده‌ی آرپا یکی است">✓ می‌خواند</span>
              <span v-else class="text-red-600" :title="r.issues.map((x) => x.message).join('\n')">✗ ناهماهنگ</span>
            </td>
            <td class="px-2 text-center ltr-nums">
              <template v-if="r.manual_balance !== null">
                <span class="text-slate-500">{{ bal(r.manual_balance) }}</span>
                <span v-if="diff(r)" class="block text-[11px]" :class="diff(r)! > 0 ? 'text-red-600' : 'text-emerald-600'">
                  اختلاف {{ fa(diff(r)) }}
                </span>
              </template>
            </td>
            <td class="px-2 text-slate-500 max-w-[200px] truncate" :title="r.note">{{ r.note }}</td>
            <td class="px-2 text-slate-500">{{ r.marketer }}</td>
            <td class="px-2 text-center ltr-nums text-slate-400">{{ r.last_date ? jd(r.last_date) : "" }}</td>
          </tr>
        </tbody>
        <tfoot>
          <tr class="border-t-2 border-slate-200 bg-slate-50 font-bold text-ink">
            <td class="px-2 py-2.5 sticky right-0 bg-slate-50" />
            <td />
            <td class="px-2 sticky right-8 bg-slate-50">مجموع</td>
            <td />
            <td v-for="c in data.columns" :key="c.key" class="px-2 text-center ltr-nums">{{ blank(data.totals.buckets[c.key]) }}</td>
            <td class="px-2 text-center ltr-nums text-emerald-600">{{ blank(data.totals.prepayment) }}</td>
            <td class="px-2 text-center ltr-nums">{{ bal(data.totals.balance) }}</td>
            <template v-if="book === 'all'">
              <td class="px-2 text-center ltr-nums">{{ balBlank(data.totals.by_book.main) }}</td>
              <td class="px-2 text-center ltr-nums">{{ balBlank(data.totals.by_book.second) }}</td>
            </template>
            <td />
            <td class="px-2 text-center ltr-nums text-slate-500">{{ blank(data.totals.manual_balance) }}</td>
            <td colspan="3" />
          </tr>
        </tfoot>
      </table>
    </div>
  </div>
</template>
