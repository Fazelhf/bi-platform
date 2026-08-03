<script setup lang="ts">
/**
 * لیست حساب‌ها — where the finance team defines the banks and cash boxes
 * every movement is attributed to.
 *
 * Balances are never typed here beyond the opening figure: everything else is
 * the ledger's answer, so this table cannot disagree with the report above it.
 */
import { computed, onMounted, ref } from "vue";
import { financeApi, type AccountBalance, type BankAccount } from "@/api/finance";
import { confirm, toast } from "@/composables/useUi";
import { useMoney } from "@/composables/useMoney";
import { num } from "@/utils/format";
import NavIcon from "@/components/NavIcon.vue";

const emit = defineEmits<{ (e: "changed"): void }>();

const accounts = ref<BankAccount[]>([]);
const balances = ref<AccountBalance[]>([]);
const totals = ref({ total: "0", unassigned: "0" });
const loading = ref(true);
const canEdit = ref(true);
const { money, unitLabel } = useMoney();

const PALETTE = ["#3b6fed", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#0ea5e9"];

const KINDS = [
  { value: "bank", label: "حساب بانکی" },
  { value: "cash", label: "صندوق" },
  { value: "petty", label: "تنخواه" },
];

async function load() {
  loading.value = true;
  try {
    const [list, snapshot] = await Promise.all([
      financeApi.accounts(),
      financeApi.accountBalances(),
    ]);
    accounts.value = list;
    balances.value = snapshot.accounts;
    totals.value = {
      total: snapshot.total_rial,
      unassigned: snapshot.unassigned_rial,
    };
  } catch (e: any) {
    if (e?.response?.status === 403) canEdit.value = false;
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const balanceOf = (id: number) =>
  balances.value.find((b) => b.id === id)?.balance_rial ?? "0";

const hasUnassigned = computed(() => Number(totals.value.unassigned) !== 0);

// ---- editor ---------------------------------------------------------------
const open = ref(false);
const editing = ref<BankAccount | null>(null);
const form = ref<Record<string, any>>({});

function blank() {
  return {
    title: "", bank_name: "", account_no: "", iban: "", kind: "bank",
    opening_balance_rial: "0", color: PALETTE[accounts.value.length % PALETTE.length],
    sort_order: accounts.value.length + 1, is_active: true, note: "",
  };
}

function openCreate() {
  editing.value = null;
  form.value = blank();
  open.value = true;
}

function openEdit(account: BankAccount) {
  editing.value = account;
  form.value = { ...account };
  open.value = true;
}

async function save() {
  try {
    await financeApi.saveAccount(form.value, editing.value?.id);
    toast.success("حساب ذخیره شد.");
    open.value = false;
    await load();
    emit("changed");
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || "ذخیره نشد.");
  }
}

async function remove(account: BankAccount) {
  if (!(await confirm({
    title: "حذف حساب",
    message: `«${account.title}» حذف شود؟`,
    danger: true,
  }))) return;
  try {
    await financeApi.removeAccount(account.id);
    toast.success("حساب حذف شد.");
    await load();
    emit("changed");
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || "حذف نشد.");
  }
}
</script>

<template>
  <section class="bg-surface rounded-card shadow-soft overflow-hidden">
    <div class="flex flex-wrap items-start justify-between gap-3 p-4 pb-3">
      <div>
        <h2 class="font-semibold text-ink">حساب‌ها</h2>
        <p class="text-xs text-slate-400 mt-0.5">
          هر واریز و برداشت به یکی از این حساب‌ها وصل می‌شود. ارقام به {{ unitLabel }}.
        </p>
      </div>
      <button
        v-if="canEdit"
        class="text-sm px-3 py-1.5 rounded-xl bg-brand-600 text-white hover:bg-brand-700 transition"
        @click="openCreate"
      >+ حساب جدید</button>
    </div>

    <div v-if="loading" class="p-8 text-center text-sm text-slate-400">در حال بارگذاری…</div>

    <div v-else-if="!accounts.length" class="p-10 text-center">
      <p class="font-medium text-ink">هنوز حسابی تعریف نشده</p>
      <p class="text-sm text-slate-400 mt-1">
        تا وقتی حسابی نباشد، گردش‌ها به هیچ بانکی نسبت داده نمی‌شوند.
      </p>
    </div>

    <div v-else class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead class="bg-slate-50/60 text-[11px] text-slate-400">
          <tr>
            <th class="text-right font-medium px-3 py-2">حساب</th>
            <th class="text-right font-medium px-3 py-2">نوع</th>
            <th class="text-right font-medium px-3 py-2">شماره / شبا</th>
            <th class="text-left font-medium px-3 py-2">موجودی اولیه</th>
            <th class="text-left font-medium px-3 py-2">موجودی فعلی</th>
            <th class="text-left font-medium px-3 py-2">گردش</th>
            <th class="w-px"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="a in accounts" :key="a.id"
            class="border-t border-slate-50 hover:bg-slate-50/60"
            :class="{ 'opacity-50': !a.is_active }"
          >
            <td class="px-3 py-2">
              <span class="flex items-center gap-2">
                <span
                  class="w-2.5 h-2.5 rounded-full shrink-0"
                  :style="{ background: a.color || '#94a3b8' }"
                ></span>
                <span class="text-ink">{{ a.title }}</span>
              </span>
              <span v-if="a.bank_name" class="block text-[11px] text-slate-400 pr-4.5">
                {{ a.bank_name }}
              </span>
            </td>
            <td class="px-3 py-2 text-slate-500">{{ a.kind_label }}</td>
            <td class="px-3 py-2 text-slate-500 ltr-nums text-xs">
              {{ a.account_no || a.iban || "—" }}
            </td>
            <td class="px-3 py-2 text-left ltr-nums text-slate-500">
              {{ money(a.opening_balance_rial, false) }}
            </td>
            <td
              class="px-3 py-2 text-left ltr-nums font-medium"
              :class="Number(balanceOf(a.id)) < 0 ? 'text-red-600' : 'text-ink'"
            >{{ money(balanceOf(a.id), false) }}</td>
            <td class="px-3 py-2 text-left ltr-nums text-slate-400">
              {{ num(a.movement_count) }}
            </td>
            <td class="px-3 py-2 text-left whitespace-nowrap">
              <button v-if="canEdit" class="text-xs text-brand-600 hover:underline ml-2" @click="openEdit(a)">ویرایش</button>
              <button v-if="canEdit" class="text-xs text-red-500 hover:underline" @click="remove(a)">حذف</button>
            </td>
          </tr>
        </tbody>
        <tfoot>
          <tr class="border-t-2 border-slate-100 bg-slate-50/40 font-semibold">
            <td class="px-3 py-2 text-ink" colspan="4">جمع کل</td>
            <td class="px-3 py-2 text-left ltr-nums">{{ money(totals.total, false) }}</td>
            <td colspan="2"></td>
          </tr>
        </tfoot>
      </table>
    </div>

    <p
      v-if="hasUnassigned"
      class="mx-4 mb-4 text-xs text-amber-700 bg-amber-50 rounded-xl px-3 py-2 flex items-start gap-2"
    >
      <NavIcon name="alert" :size="14" class="mt-0.5 shrink-0" />
      <span>
        {{ money(totals.unassigned) }} در گردش‌هایی است که هنوز به هیچ حسابی وصل نشده‌اند —
        در صفحه‌ی ورود اطلاعات برایشان حساب انتخاب کنید.
      </span>
    </p>

    <!-- ===== Editor ===== -->
    <div
      v-if="open"
      class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4"
      dir="rtl"
      @click.self="open = false"
    >
      <div class="bg-surface rounded-card shadow-pop w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto animate-pop">
        <h3 class="font-bold text-ink mb-4">{{ editing ? "ویرایش حساب" : "حساب جدید" }}</h3>
        <div class="grid sm:grid-cols-2 gap-3">
          <label class="block">
            <span class="text-xs text-slate-500">عنوان *</span>
            <input v-model="form.title" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">نوع</span>
            <select v-model="form.kind" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
              <option v-for="k in KINDS" :key="k.value" :value="k.value">{{ k.label }}</option>
            </select>
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">نام بانک</span>
            <input v-model="form.bank_name" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">شماره حساب</span>
            <input v-model="form.account_no" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
          </label>
          <label class="block sm:col-span-2">
            <span class="text-xs text-slate-500">شبا</span>
            <input v-model="form.iban" placeholder="IR…" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">موجودی اولیه (ریال)</span>
            <input v-model="form.opening_balance_rial" type="number" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">رنگ در نمودار</span>
            <input v-model="form.color" type="color" class="mt-1 w-full h-10 border border-slate-200 rounded-xl bg-surface" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">ترتیب نمایش</span>
            <input v-model.number="form.sort_order" type="number" min="0" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
          </label>
          <label class="flex items-center gap-2 pt-6 text-sm">
            <input v-model="form.is_active" type="checkbox" class="rounded" /> فعال
          </label>
          <label class="block sm:col-span-2">
            <span class="text-xs text-slate-500">توضیح</span>
            <input v-model="form.note" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
          </label>
        </div>
        <p class="text-[11px] text-slate-400 mt-3">
          موجودی اولیه همیشه به ریال وارد می‌شود؛ واحد نمایش فقط ظاهر گزارش‌ها را عوض می‌کند.
        </p>
        <div class="flex justify-end gap-2 pt-4">
          <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="open = false">انصراف</button>
          <button
            class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
            :disabled="!form.title"
            @click="save"
          >ذخیره</button>
        </div>
      </div>
    </div>
  </section>
</template>
