<script setup lang="ts">
/**
 * تسهیلات، قرض و جاری شرکا — one screen, because they are one model.
 *
 * Every balance here is summed from the cash ledger, never typed, so it
 * cannot disagree with the نقدینگی report.
 */
import { computed, onMounted, ref } from "vue";
import { financeApi, type CreditLine } from "@/api/finance";
import { confirm, toast } from "@/composables/useUi";
import { num, rial } from "@/utils/format";

/** Rendered as a tab inside نقدینگی, so the page heading is dropped there. */
withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false });

type Kind = "facility" | "lending" | "partner";

const TABS: { key: Kind; label: string; hint: string }[] = [
  { key: "facility", label: "تسهیلات دریافتی", hint: "وامی که بانک به شرکت داده" },
  { key: "lending", label: "قرض پرداختی", hint: "پولی که شرکت به دیگران داده" },
  { key: "partner", label: "جاری شرکا", hint: "حساب جاری هر شریک" },
];

const tab = ref<Kind>("facility");
const rows = ref<CreditLine[]>([]);
const loading = ref(true);
const error = ref("");
const canEdit = ref(true);

const n = (v: string | null | undefined) => Number(v ?? 0);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    rows.value = await financeApi.creditLines(tab.value);
  } catch (e: any) {
    rows.value = [];
    error.value = e?.response?.status === 403
      ? "بخش مالی برای شما قابل مشاهده نیست."
      : "بارگذاری ناموفق بود.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function pick(kind: Kind) {
  tab.value = kind;
  load();
}

const totals = computed(() => {
  const balance = rows.value.reduce((s, r) => s + n(r.balance_rial), 0);
  return {
    balance,
    count: rows.value.length,
    open: rows.value.filter((r) => n(r.balance_rial) !== 0).length,
  };
});

/**
 * A negative balance means the company owes; positive means it is owed.
 * Spelling that out beats a minus sign the reader has to interpret.
 */
function balanceLabel(row: CreditLine): string {
  const b = n(row.balance_rial);
  if (b === 0) return "تسویه‌شده";
  return b < 0 ? "بدهی شرکت" : "طلب شرکت";
}
function balanceTone(row: CreditLine): string {
  const b = n(row.balance_rial);
  if (b === 0) return "text-slate-400";
  return b < 0 ? "text-red-500" : "text-green-600";
}

// ---- editor ---------------------------------------------------------------
const editorOpen = ref(false);
const editing = ref<CreditLine | null>(null);
const form = ref<Record<string, any>>({});

function blank() {
  return {
    kind: tab.value, title: "", counterparty: "", principal_rial: "0",
    rate_pct: "0", opened_on: null, due_on: null, installments: 0,
    status: "active", note: "",
  };
}

function openCreate() {
  editing.value = null;
  form.value = blank();
  editorOpen.value = true;
}

function openEdit(row: CreditLine) {
  editing.value = row;
  form.value = {
    kind: row.kind, title: row.title, counterparty: row.counterparty,
    principal_rial: row.principal_rial, rate_pct: row.rate_pct,
    opened_on: row.opened_on, due_on: row.due_on,
    installments: row.installments, status: row.status, note: row.note,
  };
  editorOpen.value = true;
}

async function save() {
  try {
    const payload = { ...form.value };
    for (const key of ["opened_on", "due_on"]) {
      if (!payload[key]) payload[key] = null;
    }
    await financeApi.saveCreditLine(payload, editing.value?.id);
    toast.success("ذخیره شد.");
    editorOpen.value = false;
    tab.value = payload.kind;
    await load();
  } catch (e: any) {
    const data = e?.response?.data ?? {};
    toast.error(data.principal_rial?.[0] || data.detail || "ذخیره نشد.");
  }
}

async function remove(row: CreditLine) {
  if (!(await confirm({
    title: "حذف",
    message: `«${row.title}» حذف شود؟`,
    danger: true,
  }))) return;
  try {
    await financeApi.removeCreditLine(row.id);
    toast.success("حذف شد.");
    await load();
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || "حذف نشد.");
  }
}

// ---- ledger drawer --------------------------------------------------------
const ledgerOf = ref<CreditLine | null>(null);
const ledger = ref<Awaited<ReturnType<typeof financeApi.creditMovements>>>([]);

async function openLedger(row: CreditLine) {
  ledgerOf.value = row;
  ledger.value = [];
  try {
    ledger.value = await financeApi.creditMovements(row.id);
  } catch {
    toast.error("گردش این مورد خوانده نشد.");
  }
}
</script>

<template>
  <div class="space-y-4">
    <section class="bg-surface rounded-card shadow-soft p-4">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 v-if="!embedded" class="font-bold text-ink">تسهیلات و قرض</h1>
          <p class="text-xs text-slate-400" :class="embedded ? '' : 'mt-0.5'">
            {{ TABS.find((t) => t.key === tab)?.hint }} — مانده‌ها از دفتر نقدینگی محاسبه می‌شوند.
          </p>
        </div>
        <button
          v-if="canEdit"
          class="text-sm px-3 py-1.5 rounded-xl bg-brand-600 text-white hover:bg-brand-700 transition"
          @click="openCreate"
        >+ مورد جدید</button>
      </div>
      <div class="flex flex-wrap gap-1.5 mt-3">
        <button
          v-for="t in TABS" :key="t.key"
          class="px-3 py-1.5 text-sm rounded-xl border transition"
          :class="tab === t.key
            ? 'bg-panel text-white border-panel'
            : 'border-slate-200 text-slate-500 hover:bg-slate-50'"
          @click="pick(t.key)"
        >{{ t.label }}</button>
      </div>
    </section>

    <p v-if="error" class="bg-red-50 text-red-600 rounded-card p-4 text-sm">{{ error }}</p>

    <template v-else>
      <div class="grid grid-cols-3 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">تعداد</p>
          <p class="text-lg font-bold text-ink ltr-nums">{{ num(totals.count) }}</p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">باز (تسویه‌نشده)</p>
          <p class="text-lg font-bold text-ink ltr-nums">{{ num(totals.open) }}</p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">خالص مانده</p>
          <p
            class="text-lg font-bold ltr-nums"
            :class="totals.balance < 0 ? 'text-red-500' : 'text-green-600'"
          >{{ rial(totals.balance) }}</p>
        </div>
      </div>

      <section class="bg-surface rounded-card shadow-soft overflow-hidden">
        <div v-if="loading" class="p-8 text-center text-sm text-slate-400">در حال بارگذاری…</div>
        <div v-else-if="!rows.length" class="p-10 text-center">
          <p class="font-medium text-ink">موردی ثبت نشده است</p>
          <p class="text-sm text-slate-400 mt-1">
            {{ TABS.find((t) => t.key === tab)?.hint }}
          </p>
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="bg-slate-50/60 text-[11px] text-slate-400">
              <tr>
                <th class="text-right font-medium px-3 py-2">عنوان</th>
                <th class="text-right font-medium px-3 py-2">طرف حساب</th>
                <th class="text-left font-medium px-3 py-2">اصل مبلغ</th>
                <th class="text-left font-medium px-3 py-2">دریافتی</th>
                <th class="text-left font-medium px-3 py-2">پرداختی</th>
                <th class="text-left font-medium px-3 py-2">مانده</th>
                <th class="text-left font-medium px-3 py-2">سررسید</th>
                <th class="text-left font-medium px-3 py-2">وضعیت</th>
                <th class="w-px"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in rows" :key="r.id" class="border-t border-slate-50 hover:bg-slate-50/60">
                <td class="px-3 py-2 text-ink">{{ r.title }}</td>
                <td class="px-3 py-2 text-slate-500">{{ r.counterparty }}</td>
                <td class="px-3 py-2 text-left ltr-nums">{{ rial(n(r.principal_rial)) }}</td>
                <td class="px-3 py-2 text-left ltr-nums text-slate-500">{{ rial(n(r.received_rial)) }}</td>
                <td class="px-3 py-2 text-left ltr-nums text-slate-500">{{ rial(n(r.paid_rial)) }}</td>
                <td class="px-3 py-2 text-left ltr-nums font-medium" :class="balanceTone(r)">
                  {{ rial(Math.abs(n(r.balance_rial))) }}
                  <span class="block text-[10px] font-normal">{{ balanceLabel(r) }}</span>
                </td>
                <td class="px-3 py-2 text-left ltr-nums text-slate-500">{{ r.due_on || "—" }}</td>
                <td class="px-3 py-2 text-left text-xs text-slate-500">{{ r.status_label }}</td>
                <td class="px-3 py-2 text-left whitespace-nowrap">
                  <button class="text-xs text-slate-500 hover:text-ink ml-2" @click="openLedger(r)">
                    گردش ({{ num(r.movement_count) }})
                  </button>
                  <button v-if="canEdit" class="text-xs text-brand-600 hover:underline ml-2" @click="openEdit(r)">ویرایش</button>
                  <button v-if="canEdit" class="text-xs text-red-500 hover:underline" @click="remove(r)">حذف</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <!-- ===== Editor ===== -->
    <div
      v-if="editorOpen"
      class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4"
      dir="rtl"
      @click.self="editorOpen = false"
    >
      <div class="bg-surface rounded-card shadow-pop w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto animate-pop">
        <h3 class="font-bold text-ink mb-4">
          {{ editing ? "ویرایش" : "مورد جدید" }}
        </h3>
        <div class="grid sm:grid-cols-2 gap-3">
          <label class="block sm:col-span-2">
            <span class="text-xs text-slate-500">نوع</span>
            <select v-model="form.kind" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
              <option v-for="t in TABS" :key="t.key" :value="t.key">{{ t.label }}</option>
            </select>
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">عنوان *</span>
            <input v-model="form.title" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">طرف حساب *</span>
            <input v-model="form.counterparty" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">
              اصل مبلغ (ریال){{ form.kind === "partner" ? "" : " *" }}
            </span>
            <input v-model="form.principal_rial" type="number" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">نرخ سود سالانه (٪)</span>
            <input v-model="form.rate_pct" type="number" step="0.01" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">تاریخ شروع</span>
            <input v-model="form.opened_on" type="date" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">سررسید</span>
            <input v-model="form.due_on" type="date" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">تعداد اقساط</span>
            <input v-model.number="form.installments" type="number" min="0" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">وضعیت</span>
            <select v-model="form.status" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
              <option value="active">جاری</option>
              <option value="settled">تسویه‌شده</option>
              <option value="overdue">معوق</option>
              <option value="cancelled">لغوشده</option>
            </select>
          </label>
          <label class="block sm:col-span-2">
            <span class="text-xs text-slate-500">توضیح</span>
            <textarea v-model="form.note" rows="2" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface"></textarea>
          </label>
        </div>
        <p class="text-[11px] text-slate-400 mt-3">
          مانده را اینجا وارد نمی‌کنید — از روی واریز و برداشت‌هایی که در صفحه‌ی
          نقدینگی به همین مورد وصل می‌شوند محاسبه می‌شود.
        </p>
        <div class="flex justify-end gap-2 pt-4">
          <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="editorOpen = false">انصراف</button>
          <button
            class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
            :disabled="!form.title || !form.counterparty"
            @click="save"
          >ذخیره</button>
        </div>
      </div>
    </div>

    <!-- ===== Ledger ===== -->
    <div
      v-if="ledgerOf"
      class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4"
      dir="rtl"
      @click.self="ledgerOf = null"
    >
      <div class="bg-surface rounded-card shadow-pop w-full max-w-lg p-6 max-h-[85vh] overflow-y-auto animate-pop">
        <h3 class="font-bold text-ink">گردش — {{ ledgerOf.title }}</h3>
        <p class="text-xs text-slate-400 mb-4">{{ ledgerOf.counterparty }}</p>
        <p v-if="!ledger.length" class="text-sm text-slate-400 py-6 text-center">
          هنوز حرکتی به این مورد وصل نشده است.
        </p>
        <table v-else class="w-full text-sm">
          <thead class="text-[11px] text-slate-400">
            <tr>
              <th class="text-right font-medium py-2">تاریخ</th>
              <th class="text-right font-medium py-2">دسته</th>
              <th class="text-left font-medium py-2">جهت</th>
              <th class="text-left font-medium py-2">مبلغ</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in ledger" :key="m.id" class="border-t border-slate-50">
              <td class="py-1.5 text-ink">{{ m.period_label }}</td>
              <td class="py-1.5 text-slate-500">{{ m.category_name }}</td>
              <td
                class="py-1.5 text-left text-xs"
                :class="m.direction === 'in' ? 'text-green-600' : 'text-red-500'"
              >{{ m.direction === "in" ? "واریز" : "برداشت" }}</td>
              <td class="py-1.5 text-left ltr-nums">{{ rial(n(m.amount_rial)) }}</td>
            </tr>
          </tbody>
        </table>
        <div class="flex justify-end pt-4">
          <button class="px-4 py-2 text-sm rounded-xl bg-slate-100 hover:bg-slate-200" @click="ledgerOf = null">بستن</button>
        </div>
      </div>
    </div>
  </div>
</template>
