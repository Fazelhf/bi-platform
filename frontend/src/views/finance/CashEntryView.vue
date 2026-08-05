<script setup lang="ts">
/**
 * ورود نقدینگی — the daily grid, laid out the way the finance colleague's own
 * sheet is: a row per day, a column per category, واریز above برداشت.
 *
 * A live «اختلاف» readout compares what has been typed against the running
 * balance, and the same submit → approve path as every other section keeps
 * the CEO's کارتابل one queue.
 */
import { computed, onMounted, ref, watch } from "vue";
import {
  financeApi,
  type BankAccount,
  type CashEntry,
  type CreditLine,
  type EntryRow,
} from "@/api/finance";
import { salesApi } from "@/api/sales";
import { toast } from "@/composables/useUi";
import { loadMoneySettings, useMoney } from "@/composables/useMoney";
import { num } from "@/utils/format";
import MoneyInput from "@/components/MoneyInput.vue";
import NavIcon from "@/components/NavIcon.vue";

const periods = ref<{ id: number; label: string }[]>([]);
const selected = ref<number | null>(null);
const data = ref<CashEntry | null>(null);
const lines = ref<CreditLine[]>([]);
const loading = ref(true);
const saving = ref("");
const error = ref("");

const n = (v: unknown) => Number(v ?? 0);

const { money, unitLabel } = useMoney();
const rial = (v: number | string | null | undefined) => money(v, false);
const accounts = ref<BankAccount[]>([]);

/** A blank row for a cell, defaulting to the first account so the common
 *  case is one click instead of two. */
function blankRow(): EntryRow {
  return {
    amount_rial: "0",
    account: accounts.value[0]?.id ?? null,
    credit_line: null,
    note: "",
  };
}

function addRow(day: CashEntry["days"][number], side: "in" | "out", categoryId: number) {
  const key = String(categoryId);
  day[side][key] = [...(day[side][key] ?? []), blankRow()];
}

function removeRow(
  day: CashEntry["days"][number], side: "in" | "out", categoryId: number, index: number,
) {
  const key = String(categoryId);
  day[side][key] = (day[side][key] ?? []).filter((_, i) => i !== index);
}

/** Rows still missing an account — saving is blocked until none are left. */
const missingAccount = computed(() => {
  let count = 0;
  for (const day of data.value?.days ?? []) {
    for (const side of ["in", "out"] as const) {
      for (const rows of Object.values(day[side])) {
        for (const row of rows) {
          if (n(row.amount_rial) && !row.account) count += 1;
        }
      }
    }
  }
  return count;
});

async function load() {
  if (!selected.value) return;
  loading.value = true;
  error.value = "";
  try {
    const [entry, creditLines] = await Promise.all([
      financeApi.entry(selected.value),
      financeApi.creditLines(),
    ]);
    data.value = entry;
    lines.value = creditLines;
    accounts.value = entry.accounts;
  } catch (e: any) {
    data.value = null;
    error.value = e?.response?.status === 403
      ? "فقط واحد مالی به این صفحه دسترسی دارد."
      : "بارگذاری ناموفق بود.";
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  try {
    await loadMoneySettings();
    periods.value = await salesApi.periods();
    selected.value = periods.value[periods.value.length - 1]?.id ?? null;
    await load();
  } catch {
    error.value = "بارگذاری دوره‌ها ناموفق بود.";
    loading.value = false;
  }
});
watch(selected, load);

// ---- totals ---------------------------------------------------------------
function dayTotal(day: CashEntry["days"][number], side: "in" | "out"): number {
  return Object.values(day[side]).reduce(
    (sum, rows) => sum + rows.reduce((s, row) => s + n(row.amount_rial), 0),
    0,
  );
}

const totals = computed(() => {
  const days = data.value?.days ?? [];
  const inSum = days.reduce((s, d) => s + dayTotal(d, "in"), 0);
  const outSum = days.reduce((s, d) => s + dayTotal(d, "out"), 0);
  return { in: inSum, out: outSum, net: inSum - outSum };
});

/** Only show days worth looking at, unless the person asks for all of them. */
const showAllDays = ref(false);
const visibleDays = computed(() => {
  const days = data.value?.days ?? [];
  if (showAllDays.value) return days;
  const touched = days.filter((d) => dayTotal(d, "in") || dayTotal(d, "out"));
  return touched.length ? touched : days;
});

/** Categories that expect a facility/loan to be named alongside the figure. */
function needsLine(side: "in" | "out", categoryId: number): boolean {
  const cats = side === "in" ? data.value?.categories.in : data.value?.categories.out;
  return !!cats?.find((c) => c.id === categoryId)?.expects_credit_line;
}

async function save(submit: boolean) {
  if (!data.value || !selected.value) return;
  if (missingAccount.value) {
    toast.error("برای هر مبلغ باید حساب انتخاب شود.");
    return;
  }
  saving.value = submit ? "در حال ارسال…" : "در حال ذخیره…";
  try {
    const result = await financeApi.saveEntry({
      period: selected.value,
      submit,
      days: data.value.days,
    });
    toast.success(
      submit
        ? "برای تایید مدیرعامل ارسال شد."
        : `${num(result.movements)} حرکت ذخیره شد.`,
    );
    await load();
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || "ذخیره نشد.");
  } finally {
    saving.value = "";
  }
}
</script>

<template>
  <div class="space-y-4">
    <section class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="font-bold text-ink">ورود اطلاعات نقدینگی</h1>
        <p class="text-xs text-slate-400 mt-0.5">
          هر روز یک ردیف است. ستون‌ها همان دسته‌های گزارش خودتان‌اند.
          مبالغ به <span class="font-medium">{{ unitLabel }}</span>.
        </p>
      </div>
      <div class="flex items-end gap-3">
        <label class="flex items-center gap-1.5 text-xs text-slate-500">
          <input v-model="showAllDays" type="checkbox" class="rounded" />
          نمایش همه روزها
        </label>
        <label class="block">
          <span class="text-[11px] text-slate-400">ماه</span>
          <select
            v-model.number="selected"
            class="mt-1 border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface"
          >
            <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
          </select>
        </label>
      </div>
    </section>

    <p v-if="error" class="bg-red-50 text-red-600 rounded-card p-4 text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-center text-slate-400 py-16 text-sm">در حال بارگذاری…</p>

    <template v-else-if="data">
      <div class="grid grid-cols-3 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">جمع واریز</p>
          <p class="text-lg font-bold text-green-600 ltr-nums">{{ rial(totals.in) }}</p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">جمع برداشت</p>
          <p class="text-lg font-bold text-red-500 ltr-nums">{{ rial(totals.out) }}</p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">خالص</p>
          <p
            class="text-lg font-bold ltr-nums"
            :class="totals.net < 0 ? 'text-red-500' : 'text-green-600'"
          >{{ rial(totals.net) }}</p>
        </div>
      </div>

      <section
        v-for="side in (['in', 'out'] as const)"
        :key="side"
        class="bg-surface rounded-card shadow-soft overflow-hidden"
      >
        <h2
          class="font-semibold p-4 pb-2"
          :class="side === 'in' ? 'text-green-600' : 'text-red-500'"
        >{{ side === "in" ? "واریز" : "برداشت" }}</h2>

        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="bg-slate-50/60 text-[11px] text-slate-400">
              <tr>
                <th class="text-right font-medium px-3 py-2 whitespace-nowrap w-32">تاریخ</th>
                <th
                  v-for="c in data.categories[side]" :key="c.id"
                  class="text-left font-medium px-3 py-2 whitespace-nowrap min-w-[150px]"
                >{{ c.name_fa }}</th>
                <th class="text-left font-medium px-3 py-2 w-32">مجموع روز</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="day in visibleDays" :key="day.period_id"
                class="border-t border-slate-50"
              >
                <td class="px-3 py-1.5 text-ink whitespace-nowrap">{{ day.label }}</td>
                <!-- A cell holds one row per account: the same category can
                     hit two banks on the same day, and folding them into one
                     figure would lose which bank the money is in. -->
                <td v-for="c in data.categories[side]" :key="c.id" class="px-2 py-1.5 align-top">
                  <div
                    v-for="(row, i) in day[side][String(c.id)] ?? []" :key="i"
                    class="mb-1.5 last:mb-0"
                  >
                    <div class="flex items-center gap-1">
                      <MoneyInput
                        v-model="row.amount_rial"
                        :disabled="!data.can_edit"
                        class="flex-1"
                      />
                      <button
                        v-if="data.can_edit && (day[side][String(c.id)] ?? []).length > 1"
                        class="text-slate-300 hover:text-red-500 shrink-0"
                        title="حذف این ردیف"
                        @click="removeRow(day, side, c.id, i)"
                      ><NavIcon name="close" :size="13" /></button>
                    </div>

                    <select
                      v-if="n(row.amount_rial)"
                      v-model.number="row.account"
                      :disabled="!data.can_edit"
                      class="mt-1 w-full border rounded-lg px-2 py-1 text-[11px] bg-surface"
                      :class="row.account ? 'border-slate-200' : 'border-amber-300 bg-amber-50'"
                    >
                      <option :value="null">— حساب را انتخاب کنید</option>
                      <option v-for="a in accounts" :key="a.id" :value="a.id">
                        {{ a.label }}
                      </option>
                    </select>

                    <!-- Facility and loan money must say which one, or the
                         balance it belongs to cannot be worked out. جاری شرکا
                         no longer asks — the account carries what matters. -->
                    <select
                      v-if="needsLine(side, c.id) && n(row.amount_rial)"
                      v-model.number="row.credit_line"
                      :disabled="!data.can_edit"
                      class="mt-1 w-full border rounded-lg px-2 py-1 text-[11px] bg-surface"
                      :class="row.credit_line ? 'border-slate-200' : 'border-amber-300 bg-amber-50'"
                    >
                      <option :value="null">— طرف حساب را انتخاب کنید</option>
                      <option v-for="l in lines" :key="l.id" :value="l.id">
                        {{ l.kind_label }} · {{ l.counterparty }} — {{ l.title }}
                      </option>
                    </select>
                  </div>

                  <button
                    v-if="data.can_edit && accounts.length > 1"
                    class="text-[11px] text-brand-600 hover:underline"
                    @click="addRow(day, side, c.id)"
                  >+ حساب دیگر</button>
                </td>
                <td class="px-3 py-1.5 text-left ltr-nums font-medium">
                  {{ rial(dayTotal(day, side)) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div
        v-if="data.can_edit"
        class="sticky bottom-4 z-30 bg-panel text-white rounded-card shadow-pop p-3 flex flex-wrap items-center justify-between gap-2"
      >
        <span class="text-sm px-2" :class="missingAccount ? 'text-amber-300' : 'text-white/70'">
          {{ saving
            || (missingAccount
              ? `${num(missingAccount)} مبلغ هنوز حساب ندارد.`
              : "پس از تکمیل، برای تایید مدیرعامل ارسال کنید.") }}
        </span>
        <div class="flex gap-2">
          <button
            class="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/20 text-sm transition"
            :disabled="!!saving"
            @click="save(false)"
          >ذخیره پیش‌نویس</button>
          <button
            class="px-5 py-2 rounded-xl bg-accent-500 hover:bg-accent-600 text-sm font-medium transition"
            :disabled="!!saving"
            @click="save(true)"
          >ذخیره و ارسال برای تایید</button>
        </div>
      </div>
      <p v-else class="text-xs text-slate-400 text-center">
        شما فقط می‌توانید این صفحه را ببینید؛ ثبت با واحد مالی است.
      </p>
    </template>
  </div>
</template>
