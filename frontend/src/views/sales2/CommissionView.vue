<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import {
  sales2Api,
  type CommissionLine,
  type CommissionSheet,
  type CommissionTier,
} from "@/api/sales2";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormModal from "@/components/crm/FormModal.vue";
import { apiError } from "@/components/crm/formError";
import { confirm, prompt, toast } from "@/composables/useUi";
import { faDate } from "@/utils/adminFormat";
import { MONTH_NAMES, toJalali } from "@/utils/jalali";

/**
 * پورسانت — the month's sheet, the way finance's workbook lays it out: one
 * column per salesperson («کل»), then each person's lines with the margin
 * over فی حسابداری that set their rate.
 *
 * Two figures, as in the workbook: پورسانت (on what the customer has paid)
 * and پورسانت بازاریاب (on the net amount). While the month is open it is
 * live; approving freezes it.
 *
 * Mounted twice — in فروش ۲ and in مالی — so it reads its own route to know
 * which shell it sits in, and nothing else differs.
 */
const route = useRoute();
const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));
const inp = "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";

const now = toJalali(new Date());
const year = ref(now.jy);
const month = ref(now.jm);
const data = ref<CommissionSheet | null>(null);
const loading = ref(true);
const error = ref("");
const openPerson = ref<string | null>(null);
const showTiers = ref(false);
const tiers = ref<CommissionTier[]>([]);
const inFinance = computed(() => route.name === "finance-commission");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    data.value = await sales2Api.commission(year.value, month.value);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function shift(delta: number) {
  let m = month.value + delta;
  let y = year.value;
  if (m < 1) { m = 12; y -= 1; }
  if (m > 12) { m = 1; y += 1; }
  year.value = y;
  month.value = m;
  openPerson.value = null;
  load();
}

const approved = computed(() => data.value?.status === "approved");

const totals = computed(() => {
  const t = { sales: 0, profit: 0, paid: 0, net: 0, pending: 0, noCost: 0 };
  for (const p of data.value?.people ?? []) {
    t.sales += Number(p.sales_rial);
    t.profit += Number(p.profit_rial);
    t.paid += Number(p.commission_paid_rial);
    t.net += Number(p.commission_net_rial);
    t.pending += Number(p.commission_pending_rial);
    t.noCost += p.no_cost_lines;
  }
  return t;
});

function linesOf(name: string): CommissionLine[] {
  return (data.value?.rows ?? []).filter((r) => r.salesperson === name);
}

async function approve() {
  const ok = await confirm({
    title: `تأیید پورسانت ${MONTH_NAMES[month.value - 1]}`,
    message: "با تأیید، ارقام این ماه ثابت می‌شوند و دریافت یا تغییرات بعدی آن‌ها را عوض نمی‌کند. ادامه؟",
  });
  if (!ok) return;
  try {
    data.value = await sales2Api.approveCommission(year.value, month.value);
    toast.success("پورسانت ماه تأیید شد.");
  } catch (e) {
    error.value = apiError(e);
  }
}

async function reopen() {
  const ok = await confirm({ title: "باز کردن دوباره", message: "ارقام تأییدشده کنار گذاشته و دوباره از روی اسناد حساب می‌شوند. ادامه؟", danger: true });
  if (!ok) return;
  try {
    data.value = await sales2Api.approveCommission(year.value, month.value, true);
  } catch (e) {
    error.value = apiError(e);
  }
}

async function override(r: CommissionLine) {
  const rate = await prompt({
    title: `درصد پورسانت · ${r.number} · ${r.product}`,
    message: `سود این ردیف ${r.margin_pct === null ? "نامعلوم" : `${FA.format(Number(r.margin_pct))}٪`} است و طبق جدول ${FA.format(Number(r.rate_pct))}٪ می‌گیرد.\nدرصد جدید را بنویسید (خالی = برگشت به جدول):`,
    value: r.rate_source === "override" ? r.rate_pct : "",
    placeholder: "مثلاً 0 یا 1.25",
  });
  if (rate === null) return;
  let reason = "";
  if (rate.trim() !== "") {
    const why = await prompt({ title: "دلیل تغییر دستی", message: "دلیل کنار ردیف ثبت می‌شود.", value: r.override_reason });
    if (!why?.trim()) return;
    reason = why.trim();
  }
  try {
    data.value = await sales2Api.overrideCommission(r.line, rate.trim() === "" ? null : rate.trim(), reason);
    toast.success("درصد پورسانت ردیف به‌روز شد.");
  } catch (e) {
    error.value = apiError(e);
  }
}

function editTiers() {
  tiers.value = (data.value?.tiers ?? []).map((t) => ({ ...t }));
  showTiers.value = true;
}

async function saveTiers() {
  try {
    await sales2Api.saveTiers(tiers.value);
    showTiers.value = false;
    toast.success("جدول پورسانت ذخیره شد.");
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}

async function exportXlsx() {
  try {
    const blob = await sales2Api.exportCommission(year.value, month.value);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `پورسانت-${MONTH_NAMES[month.value - 1]}-${year.value}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    error.value = apiError(e);
  }
}

const SOURCE_LABEL: Record<string, string> = { tier: "جدول", override: "دستی", no_cost: "بدون فی حسابداری" };
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <button class="rounded-lg px-2 py-1.5 text-slate-500 hover:bg-slate-100" title="ماه بعد" @click="shift(1)">›</button>
      <h1 class="font-bold text-ink min-w-[110px] text-center">{{ MONTH_NAMES[month - 1] }} {{ FA.format(year).replace(/٬/g, "") }}</h1>
      <button class="rounded-lg px-2 py-1.5 text-slate-500 hover:bg-slate-100" title="ماه قبل" @click="shift(-1)">‹</button>
      <span
        v-if="data"
        class="text-xs rounded-full px-2 py-0.5"
        :class="approved ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'"
      >{{ approved ? `تأیید شده${data.approved_by ? ` · ${data.approved_by}` : ""}` : "باز — ارقام زنده" }}</span>
      <div class="flex-1" />
      <button class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-600" @click="editTiers">جدول درصدها</button>
      <button class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-600" @click="exportXlsx">خروجی اکسل</button>
      <button v-if="!approved" class="rounded-xl px-4 py-2 text-sm bg-panel text-white" @click="approve">تأیید ماه</button>
      <button v-else class="rounded-xl px-3 py-2 text-sm text-red-500 hover:bg-red-50" @click="reopen">باز کردن</button>
    </div>

    <p v-if="inFinance" class="text-xs text-slate-500 px-1">
      این برگه از فاکتورهای «فروش ۲» ساخته می‌شود؛ فعلاً فقط برای مدیر سامانه نمایش داده می‌شود.
    </p>
    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line">{{ error }}</p>

    <div v-if="loading" class="space-y-2"><Skeleton v-for="i in 5" :key="i" class="h-16 rounded-xl" /></div>

    <EmptyState
      v-else-if="data && !data.people.length"
      title="در این ماه فاکتوری صادر نشده"
      hint="پورسانت از فاکتورهای صادرشده‌ی فروش ۲ در همین ماه حساب می‌شود."
    />

    <template v-else-if="data">
      <div class="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-500">فروش ریالی</p><p class="text-lg font-bold ltr-nums mt-1">{{ fa(totals.sales) }}</p></div>
        <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-500">سود فروش</p><p class="text-lg font-bold ltr-nums mt-1 text-emerald-600">{{ fa(totals.profit) }}</p></div>
        <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-500">پورسانت (پرداختی)</p><p class="text-lg font-bold ltr-nums mt-1 text-ink">{{ fa(totals.paid) }}</p></div>
        <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-500">پورسانت بازاریاب</p><p class="text-lg font-bold ltr-nums mt-1 text-ink">{{ fa(totals.net) }}</p></div>
        <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-500">در انتظار تسویه</p><p class="text-lg font-bold ltr-nums mt-1 text-amber-600">{{ fa(totals.pending) }}</p></div>
      </div>
      <p v-if="totals.noCost" class="bg-amber-50 text-amber-800 text-sm rounded-xl px-3 py-2">
        {{ FA.format(totals.noCost) }} ردیف فی حسابداری ندارد و پورسانتش صفر حساب شده؛ از صفحه‌ی «فی حسابداری» تکمیل کنید یا درصد را دستی بزنید.
      </p>

      <!-- «کل»: one row per salesperson; opening one lists its lines. -->
      <div class="bg-surface rounded-card shadow-soft overflow-x-auto">
        <table class="w-full text-sm min-w-[1000px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-3">فروشنده</th>
              <th class="text-right font-medium px-3">فروش ریالی</th>
              <th class="text-right font-medium px-3">تارگت</th>
              <th class="text-right font-medium px-3">فاکتور</th>
              <th class="text-right font-medium px-3">مشتری فعال / جدید</th>
              <th class="text-right font-medium px-3">سود فروش</th>
              <th class="text-right font-medium px-3">پورسانت (پرداختی)</th>
              <th class="text-right font-medium px-3">پورسانت بازاریاب</th>
              <th class="text-right font-medium px-3">در انتظار تسویه</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="p in data.people" :key="p.salesperson">
              <tr
                class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                @click="openPerson = openPerson === p.salesperson ? null : p.salesperson"
              >
                <td class="px-4 py-2.5 text-ink font-medium">
                  <span class="text-slate-300 ml-1">{{ openPerson === p.salesperson ? "▾" : "◂" }}</span>{{ p.salesperson }}
                  <span v-if="p.override_lines" class="text-[11px] text-amber-600 mr-1">{{ FA.format(p.override_lines) }} دستی</span>
                </td>
                <td class="px-3 ltr-nums">{{ fa(p.sales_rial) }}</td>
                <td class="px-3 ltr-nums text-xs text-slate-500">
                  <template v-if="p.target_rial">{{ fa(p.target_rial) }} <span class="text-sky-600">({{ FA.format(Number(p.target_pct)) }}٪)</span></template>
                  <template v-else>—</template>
                </td>
                <td class="px-3 ltr-nums">{{ FA.format(p.invoice_count) }}</td>
                <td class="px-3 ltr-nums">{{ FA.format(p.active_customers) }} / {{ FA.format(p.new_customers) }}</td>
                <td class="px-3 ltr-nums text-emerald-600">{{ fa(p.profit_rial) }}</td>
                <td class="px-3 ltr-nums font-bold text-ink">{{ fa(p.commission_paid_rial) }}</td>
                <td class="px-3 ltr-nums font-bold text-ink">{{ fa(p.commission_net_rial) }}</td>
                <td class="px-3 ltr-nums text-amber-600">{{ fa(p.commission_pending_rial) }}</td>
              </tr>
              <tr v-if="openPerson === p.salesperson">
                <td colspan="9" class="bg-slate-50 px-3 py-2">
                  <table class="w-full text-xs">
                    <thead>
                      <tr class="text-slate-400">
                        <th class="text-right font-medium py-1.5 px-2">سند</th>
                        <th class="text-right font-medium px-2">مشتری</th>
                        <th class="text-right font-medium px-2">کالا</th>
                        <th class="text-right font-medium px-2">تعداد</th>
                        <th class="text-right font-medium px-2">فی</th>
                        <th class="text-right font-medium px-2">فی حسابداری</th>
                        <th class="text-right font-medium px-2">سود</th>
                        <th class="text-right font-medium px-2">درصد</th>
                        <th class="text-right font-medium px-2">پرداخت‌شده</th>
                        <th class="text-right font-medium px-2">پورسانت</th>
                        <th class="text-right font-medium px-2">بازاریاب</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="r in linesOf(p.salesperson)" :key="r.line" class="border-t border-slate-200" :class="r.kind === 'return' ? 'text-red-600' : ''">
                        <td class="py-1.5 px-2 ltr-nums">
                          <router-link :to="{ name: 'sales2-document', params: { id: r.doc_id }, query: { kind: r.kind } }" class="text-sky-600">{{ r.number }}</router-link>
                          <span class="text-slate-400 block">{{ faDate(r.doc_date) }}</span>
                        </td>
                        <td class="px-2">{{ r.customer }}</td>
                        <td class="px-2">{{ r.product }}<span v-if="r.grammage" class="text-slate-400"> · {{ FA.format(r.grammage) }}گ</span></td>
                        <td class="px-2 ltr-nums">{{ FA.format(Number(r.quantity)) }}</td>
                        <td class="px-2 ltr-nums">{{ fa(r.unit_price_rial) }}</td>
                        <td class="px-2 ltr-nums text-slate-500">{{ Number(r.cost_unit_rial) ? fa(r.cost_unit_rial) : "—" }}</td>
                        <td class="px-2 ltr-nums" :class="Number(r.margin_pct) < 0 ? 'text-red-600' : ''">
                          {{ r.margin_pct === null ? "—" : `${FA.format(Number(r.margin_pct))}٪` }}
                        </td>
                        <td class="px-2">
                          <button
                            class="rounded-md px-1.5 py-0.5 ltr-nums"
                            :class="{
                              'bg-amber-100 text-amber-700': r.rate_source === 'override',
                              'bg-slate-200 text-slate-500': r.rate_source === 'no_cost',
                              'bg-white text-ink': r.rate_source === 'tier',
                            }"
                            :title="r.override_reason || SOURCE_LABEL[r.rate_source]"
                            :disabled="approved || r.kind === 'return'"
                            @click="override(r)"
                          >{{ FA.format(Number(r.rate_pct)) }}٪</button>
                        </td>
                        <td class="px-2 ltr-nums text-slate-500">{{ FA.format(Number(r.paid_share_pct)) }}٪</td>
                        <td class="px-2 ltr-nums font-medium">{{ fa(r.commission_paid_rial) }}</td>
                        <td class="px-2 ltr-nums font-medium">{{ fa(r.commission_net_rial) }}</td>
                      </tr>
                    </tbody>
                  </table>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <p class="text-xs text-slate-500 px-1">
        «پورسانت» = درصد × مبلغی که مشتری از همان فاکتور پرداخت کرده؛ «پورسانت بازاریاب» = درصد × مبلغ خالص فاکتور.
        درصد هر ردیف از جدول و بر اساس سود نسبت به فی حسابداری است؛ برای تغییر دستی روی درصد کلیک کنید.
      </p>
    </template>

    <FormModal v-if="showTiers" title="جدول درصد پورسانت" @close="showTiers = false" @save="saveTiers">
      <p class="text-xs text-slate-500">ردیفی که حداقل این‌قدر بالای فی حسابداری فروخته شده باشد، این درصد را می‌گیرد. زیر اولین پله، پورسانت صفر است.</p>
      <div v-for="(t, i) in tiers" :key="i" class="flex items-center gap-2">
        <span class="text-xs text-slate-500 w-20">سود از</span>
        <input v-model="t.min_margin_pct" :class="inp" inputmode="decimal" />
        <span class="text-xs text-slate-500">٪ ←</span>
        <input v-model="t.rate_pct" :class="inp" inputmode="decimal" />
        <span class="text-xs text-slate-500">٪</span>
        <button class="text-slate-300 hover:text-red-500" @click="tiers.splice(i, 1)">✕</button>
      </div>
      <button class="text-sm text-sky-600" @click="tiers.push({ min_margin_pct: '', rate_pct: '' })">+ پله</button>
    </FormModal>
  </div>
</template>
