<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { sales2Api, type LedgerDetail } from "@/api/sales2";
import { apiError } from "@/components/crm/formError";
import { confirm, toast } from "@/composables/useUi";
import { faDigits, isoToJalali } from "@/utils/jalali";

/**
 * One customer's account, settled: every فاکتور with what paid it and when,
 * every دریافت with the فاکتورها it went to, the ledger itself with آرپا's
 * «مانده» beside the computed one, and every place they disagree.
 */
const props = defineProps<{ accounts: number[]; customer: number; asOf: string }>();
const emit = defineEmits<{ (e: "close"): void; (e: "changed"): void }>();

const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));
const blank = (v: string | null | undefined) => (Number(v ?? 0) ? fa(v) : "—");
/** A balance as آرپا prints it: the amount, and «بد» (بدهکار) or «بس» (بستانکار). */
const bal = (v: number | string | null | undefined) => {
  const n = Math.round(Number(v ?? 0));
  return n ? `${FA.format(Math.abs(n))} ${n > 0 ? "بد" : "بس"}` : "۰";
};
const jd = (iso: string | null | undefined) => {
  const j = iso ? isoToJalali(iso) : null;
  return j ? faDigits(`${j.jy}/${String(j.jm).padStart(2, "0")}/${String(j.jd).padStart(2, "0")}`) : "—";
};
const METHOD: Record<string, string> = { cash: "نقد", cheque: "چک", transfer: "واریز", return: "برگشت از فروش", opening: "مانده قبل" };
const HOW: Record<string, string> = { named: "", fifo: "قدیمی‌ترین", opening: "از مانده قبل" };

const details = ref<LedgerDetail[]>([]);
const active = ref(0);
const tab = ref<"items" | "credits" | "rows" | "issues">("items");
const loading = ref(true);
const error = ref("");
const note = ref("");
const marketer = ref("");
const onlyOpen = ref(false);

const d = computed(() => details.value[active.value]);

async function load() {
  loading.value = true;
  try {
    details.value = await Promise.all(props.accounts.map((id) => sales2Api.ledgerAccount(id, props.asOf)));
    pickAccount(Math.min(active.value, details.value.length - 1));
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function pickAccount(i: number) {
  active.value = i;
  note.value = details.value[i]?.account.note ?? "";
  marketer.value = details.value[i]?.account.marketer ?? "";
}

const items = computed(() => (d.value?.items ?? []).filter((x) => !onlyOpen.value || Number(x.remaining) > 0));

async function saveMeta() {
  if (!d.value) return;
  try {
    await sales2Api.saveLedgerAccount(d.value.account.id, { note: note.value, marketer: marketer.value });
    d.value.account.note = note.value;
    d.value.account.marketer = marketer.value;
    toast.success("ذخیره شد.");
    emit("changed");
  } catch (e) {
    error.value = apiError(e);
  }
}

async function remove() {
  if (!d.value) return;
  const ok = await confirm({
    title: "حذف دفتر",
    message: `دفتر «${d.value.account.book_label}» ${d.value.account.name} و توضیحاتش از مطالبات برداشته شود؟ با ورود دوباره‌ی فایل برمی‌گردد.`,
    danger: true,
  });
  if (!ok) return;
  await sales2Api.removeLedgerAccount(d.value.account.id);
  emit("changed");
  emit("close");
}

async function exportCustomer() {
  try {
    const blob = await sales2Api.ledgerCustomerExport(props.customer, props.asOf);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `صورت مطالبات ${d.value?.account.name ?? ""}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    error.value = apiError(e);
  }
}

function status(x: LedgerDetail["items"][number]): { label: string; cls: string } {
  if (Number(x.remaining) <= 0) return { label: "تسویه", cls: "bg-emerald-50 text-emerald-700" };
  if (Number(x.paid) > 0) return { label: "جزئی", cls: "bg-amber-50 text-amber-700" };
  return { label: "باز", cls: "bg-red-50 text-red-600" };
}
const paidPct = (x: LedgerDetail["items"][number]) =>
  `${Math.max(0, Math.min(100, (Number(x.paid) / Math.max(1, Number(x.amount))) * 100))}%`;
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4 space-y-3 border border-sky-100">
    <div v-if="loading" class="text-sm text-slate-400">در حال بارگذاری…</div>
    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">{{ error }}</p>

    <template v-if="d">
      <div class="flex flex-wrap items-start gap-3">
        <div class="flex-1 min-w-[220px]">
          <h2 class="font-bold text-ink">{{ d.account.name }}</h2>
          <p class="text-xs text-slate-500 mt-0.5">
            {{ d.account.book_label }}
            <template v-if="d.account.party_code"> · کد تفصیل {{ faDigits(d.account.party_code) }}</template>
            <template v-if="d.account.imported_at"> · {{ d.account.source_file }} · {{ jd(d.account.first_date) }} تا {{ jd(d.account.last_date) }}</template>
            <template v-else> · دفتر حساب هنوز وارد نشده</template>
          </p>
        </div>
        <div v-if="details.length > 1" class="flex rounded-xl bg-slate-100 p-1">
          <button
            v-for="(x, i) in details" :key="x.account.id"
            class="rounded-lg px-3 py-1 text-sm" :class="active === i ? 'bg-white shadow-sm text-ink' : 'text-slate-500'"
            @click="pickAccount(i)"
          >{{ x.account.book_label }}</button>
        </div>
        <button class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-700" @click="exportCustomer">صورت مطالبات (اکسل)</button>
        <button class="rounded-xl px-3 py-2 text-sm text-red-500 hover:bg-red-50" @click="remove">حذف</button>
        <button class="rounded-xl px-2 py-2 text-slate-400 hover:bg-slate-100" title="بستن" @click="emit('close')">✕</button>
      </div>

      <div class="grid grid-cols-2 md:grid-cols-5 gap-2 text-sm">
        <div class="bg-slate-50 rounded-xl p-3">
          <p class="text-xs text-slate-500">مانده (محاسبه)</p>
          <p class="font-bold ltr-nums text-ink">{{ bal(d.balance) }}</p>
        </div>
        <div class="bg-slate-50 rounded-xl p-3">
          <p class="text-xs text-slate-500">مانده طبق آرپا</p>
          <p class="font-bold ltr-nums" :class="d.reconciled ? 'text-emerald-600' : 'text-red-600'">
            {{ d.file_balance === null ? "—" : bal(d.file_balance) }} {{ d.reconciled ? "✓" : "✗" }}
          </p>
        </div>
        <div class="bg-slate-50 rounded-xl p-3">
          <p class="text-xs text-slate-500">پیش دریافت</p>
          <p class="font-bold ltr-nums text-emerald-600">{{ blank(d.prepayment) }}</p>
        </div>
        <div class="bg-slate-50 rounded-xl p-3">
          <p class="text-xs text-slate-500">قدیمی‌ترین فاکتور باز</p>
          <p class="font-bold ltr-nums text-ink">{{ jd(d.oldest_open) }}</p>
        </div>
        <div class="bg-slate-50 rounded-xl p-3">
          <p class="text-xs text-slate-500">گزارش دستی <template v-if="d.account.manual_as_of">({{ jd(d.account.manual_as_of) }})</template></p>
          <p class="font-bold ltr-nums text-slate-600">{{ d.account.manual_balance === null ? "—" : bal(d.account.manual_balance) }}</p>
        </div>
      </div>

      <div class="flex flex-wrap items-end gap-2">
        <label class="flex-1 min-w-[220px] text-xs text-slate-500">توضیحات
          <input v-model="note" class="mt-1 w-full bg-slate-100 rounded-lg px-3 py-2 text-sm text-ink outline-none" />
        </label>
        <label class="w-48 text-xs text-slate-500">بازاریاب
          <input v-model="marketer" class="mt-1 w-full bg-slate-100 rounded-lg px-3 py-2 text-sm text-ink outline-none" />
        </label>
        <button
          class="rounded-xl px-4 py-2 text-sm bg-panel text-white"
          :disabled="note === d.account.note && marketer === d.account.marketer" @click="saveMeta"
        >ذخیره</button>
      </div>

      <div class="flex flex-wrap items-center gap-1 border-b border-slate-100">
        <button
          v-for="t in ([['items', `فاکتورها (${FA.format(d.items.length)})`], ['credits', `دریافت‌ها (${FA.format(d.credits.length)})`],
                        ['rows', `دفتر (${FA.format(d.rows.length)} ردیف)`], ['issues', `کنترل (${FA.format(d.issues.length)})`]] as const)"
          :key="t[0]"
          class="px-3 py-2 text-sm -mb-px border-b-2"
          :class="tab === t[0] ? 'border-sky-500 text-ink font-medium' : 'border-transparent text-slate-500'"
          @click="tab = t[0]"
        >{{ t[1] }}</button>
        <span class="flex-1" />
        <label v-if="tab === 'items'" class="flex items-center gap-1 text-xs text-slate-500">
          <input v-model="onlyOpen" type="checkbox" /> فقط باز
        </label>
      </div>

      <!-- فاکتورها -->
      <div v-if="tab === 'items'" class="overflow-x-auto">
        <table class="w-full text-xs whitespace-nowrap">
          <thead>
            <tr class="text-slate-500 bg-slate-50">
              <th class="text-right font-medium px-2 py-2">فاکتور</th>
              <th class="text-center font-medium px-2">تاریخ</th>
              <th class="text-center font-medium px-2">مبلغ</th>
              <th class="text-center font-medium px-2">دریافت‌شده</th>
              <th class="text-center font-medium px-2">مانده</th>
              <th class="text-center font-medium px-2">وضعیت</th>
              <th class="text-center font-medium px-2">تسویه</th>
              <th class="text-center font-medium px-2">سررسید</th>
              <th class="text-right font-medium px-2">دریافت‌ها</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="x in items" :key="x.key" class="border-t border-slate-100 align-top">
              <td class="px-2 py-2">
                <p class="font-medium text-ink">{{ x.kind === "invoice" ? `فاکتور ${faDigits(x.number)}` : x.label }}</p>
                <p class="text-[11px] text-slate-400">سند {{ faDigits(x.doc_no || "—") }}<template v-if="x.salesperson"> · {{ x.salesperson }}</template></p>
              </td>
              <td class="px-2 text-center ltr-nums">{{ jd(x.date) }}</td>
              <td class="px-2 text-center ltr-nums">
                {{ fa(x.amount) }}
                <p v-if="x.arpa_total && x.arpa_total !== x.amount" class="text-[11px] text-amber-600">فروش آرپا: {{ fa(x.arpa_total) }}</p>
              </td>
              <td class="px-2 text-center ltr-nums text-emerald-600">
                {{ blank(x.paid) }}
                <div class="h-1 rounded-full bg-slate-100 mt-1 w-20 overflow-hidden"><div class="h-full bg-emerald-500" :style="{ width: paidPct(x) }" /></div>
              </td>
              <td class="px-2 text-center ltr-nums font-bold" :class="Number(x.remaining) > 0 ? 'text-red-600' : 'text-slate-300'">{{ blank(x.remaining) }}</td>
              <td class="px-2"><span class="rounded-md px-1.5 py-0.5" :class="status(x).cls">{{ status(x).label }}</span></td>
              <td class="px-2 text-center ltr-nums text-slate-500">
                <template v-if="x.settled_on">{{ jd(x.settled_on) }}
                  <span class="block text-[11px]">{{ x.days_to_settle! < 0 ? `${FA.format(-x.days_to_settle!)} روز پیش از فاکتور` : `${FA.format(x.days_to_settle!)} روز` }}</span>
                </template>
                <template v-else-if="x.days_open !== null">{{ FA.format(x.days_open) }} روز باز</template>
              </td>
              <td class="px-2 text-center ltr-nums">
                <template v-if="x.due_date">{{ jd(x.due_date) }}
                  <span v-if="x.overdue_days" class="block text-[11px] text-red-600">{{ FA.format(x.overdue_days) }} روز گذشته</span>
                </template>
                <span v-else class="text-slate-300">—</span>
              </td>
              <td class="px-2 text-slate-600 whitespace-normal min-w-[260px]">
                <span v-for="(p, j) in x.payments" :key="j" class="inline-block ml-2">
                  {{ jd(p.date) }} · سند {{ faDigits(p.doc_no) }} · {{ METHOD[p.method] ?? p.method }}
                  <b class="ltr-nums">{{ fa(p.amount) }}</b>
                  <span v-if="HOW[p.how]" class="text-amber-600">({{ HOW[p.how] }})</span>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- دریافت‌ها -->
      <div v-else-if="tab === 'credits'" class="overflow-x-auto">
        <table class="w-full text-xs whitespace-nowrap">
          <thead>
            <tr class="text-slate-500 bg-slate-50">
              <th class="text-center font-medium px-2 py-2">تاریخ</th>
              <th class="text-center font-medium px-2">سند</th>
              <th class="text-center font-medium px-2">روش</th>
              <th class="text-center font-medium px-2">مبلغ</th>
              <th class="text-center font-medium px-2">بابت</th>
              <th class="text-right font-medium px-2">تسویه‌شده با</th>
              <th class="text-right font-medium px-2">شرح</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(c, i) in d.credits" :key="i" class="border-t border-slate-100 align-top">
              <td class="px-2 py-2 ltr-nums">{{ jd(c.date) }}</td>
              <td class="px-2 text-center ltr-nums">{{ faDigits(c.doc_no || "—") }}</td>
              <td class="px-2">{{ METHOD[c.method || c.kind] ?? "—" }}<template v-if="c.cheque_count"> ({{ FA.format(c.cheque_count) }} فقره)</template></td>
              <td class="px-2 text-center ltr-nums font-medium text-emerald-700">{{ fa(c.amount) }}</td>
              <td class="px-2">{{ c.invoice_no ? `فاکتور ${faDigits(c.invoice_no)}` : "علی‌الحساب" }}</td>
              <td class="px-2 whitespace-normal min-w-[180px]">
                <span v-for="(a, j) in c.allocations" :key="j" class="inline-block ml-2">
                  {{ /^\d+$/.test(a.label) ? `فاکتور ${faDigits(a.label)}` : a.label }}: <b class="ltr-nums">{{ fa(a.amount) }}</b>
                  <span v-if="HOW[a.how]" class="text-amber-600">({{ HOW[a.how] }})</span>
                </span>
                <span v-if="Number(c.left)" class="text-emerald-600">پیش دریافت: {{ fa(c.left) }}</span>
              </td>
              <td class="px-2 text-slate-500 whitespace-normal min-w-[260px]">{{ c.description }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- دفتر -->
      <div v-else-if="tab === 'rows'" class="overflow-x-auto max-h-[520px] overflow-y-auto">
        <table class="w-full text-xs whitespace-nowrap">
          <thead class="sticky top-0">
            <tr class="text-slate-500 bg-slate-50">
              <th class="text-center font-medium px-2 py-2">ردیف</th>
              <th class="text-center font-medium px-2">سند</th>
              <th class="text-center font-medium px-2">تاریخ</th>
              <th class="text-center font-medium px-2">بدهکار</th>
              <th class="text-center font-medium px-2">بستانکار</th>
              <th class="text-center font-medium px-2">مانده</th>
              <th class="text-center font-medium px-2">آرپا</th>
              <th class="text-right font-medium px-2">شرح</th>
            </tr>
          </thead>
          <tbody>
            <tr class="border-t border-slate-100 text-slate-500">
              <td class="px-2 py-1.5" colspan="5">موجودی قبل از دوره</td>
              <td class="px-2 text-center ltr-nums">{{ bal(d.account.opening) }}</td><td colspan="2" />
            </tr>
            <tr
              v-for="r in d.rows" :key="r.row" class="border-t border-slate-100"
              :class="r.file_balance !== null && r.file_balance !== r.balance ? 'bg-red-50' : ''"
            >
              <td class="px-2 py-1.5 text-slate-400">{{ FA.format(r.row) }}</td>
              <td class="px-2 text-center ltr-nums">{{ faDigits(r.doc_no) }}</td>
              <td class="px-2 text-center ltr-nums">{{ jd(r.date) }}</td>
              <td class="px-2 text-center ltr-nums">{{ Number(r.debit) ? fa(r.debit) : "" }}</td>
              <td class="px-2 text-center ltr-nums text-emerald-700">{{ Number(r.credit) ? fa(r.credit) : "" }}</td>
              <td class="px-2 text-center ltr-nums font-medium">{{ bal(r.balance) }}</td>
              <td class="px-2">{{ r.file_balance === null ? "" : r.file_balance === r.balance ? "✓" : `✗ ${bal(r.file_balance)}` }}</td>
              <td class="px-2 text-slate-600 whitespace-normal min-w-[300px]">{{ r.description }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- کنترل -->
      <div v-else class="space-y-1 text-sm">
        <p v-if="!d.issues.length" class="text-emerald-600">✓ همه‌ی ردیف‌ها با مانده‌ی آرپا می‌خوانند و هر دریافت جای مشخصی دارد.</p>
        <p
          v-for="(x, i) in d.issues" :key="i" class="rounded-lg px-3 py-2"
          :class="x.level === 'error' ? 'bg-red-50 text-red-700' : x.level === 'warn' ? 'bg-amber-50 text-amber-700' : 'bg-slate-50 text-slate-600'"
        >{{ x.message }}</p>
      </div>
    </template>
  </div>
</template>
