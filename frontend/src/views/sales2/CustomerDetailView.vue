<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { sales2Api, type CustomerDetail, type StatementEntry } from "@/api/sales2";
import MoneyInput from "@/components/MoneyInput.vue";
import Skeleton from "@/components/Skeleton.vue";
import { apiError } from "@/components/crm/formError";
import { toast } from "@/composables/useUi";
import { faDate } from "@/utils/adminFormat";

/** پرونده‌ی فروش مشتری — balance, credit terms, documents and the running statement. */
const route = useRoute();
const router = useRouter();
const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));
const inp = "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";

const c = ref<CustomerDetail | null>(null);
const statement = ref<StatementEntry[]>([]);
const tab = ref<"docs" | "statement" | "receipts">("docs");
const error = ref("");
const account = ref({ credit_limit_rial: "", unlimited: true, credit_days: 0, on_hold: false, note: "" });

async function load() {
  const id = Number(route.params.id);
  c.value = await sales2Api.customer(id);
  const a = c.value.account;
  account.value = {
    credit_limit_rial: a.credit_limit_rial ?? "", unlimited: a.credit_limit_rial === null,
    credit_days: a.credit_days, on_hold: a.on_hold, note: a.note,
  };
  statement.value = (await sales2Api.statement(id)).entries;
}
onMounted(load);

async function saveAccount() {
  error.value = "";
  try {
    await sales2Api.saveAccount(c.value!.id, {
      credit_limit_rial: account.value.unlimited ? null : String(account.value.credit_limit_rial || 0),
      credit_days: Number(account.value.credit_days || 0),
      on_hold: account.value.on_hold,
      note: account.value.note,
    });
    toast.success("شرایط اعتباری ذخیره شد.");
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}

function openDoc(id: number, kind: string) {
  router.push({ name: "sales2-document", params: { id }, query: { kind } });
}
</script>

<template>
  <div v-if="!c" class="space-y-3"><Skeleton class="h-32 rounded-card" /><Skeleton class="h-64 rounded-card" /></div>
  <div v-else class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-lg font-bold text-ink">{{ c.name_fa }}</h1>
        <p class="text-xs text-slate-500 ltr-nums mt-1">
          {{ [c.national_id && `شناسه ملی ${c.national_id}`, c.economic_code && `کد اقتصادی ${c.economic_code}`, c.phone, c.province, c.city].filter(Boolean).join(" · ") }}
        </p>
        <p v-if="c.address" class="text-xs text-slate-400 mt-1">{{ c.address }}</p>
        <p v-if="c.owner_name" class="text-xs text-slate-500 mt-1">کارشناس: {{ c.owner_name }}</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <router-link :to="{ name: 'sales2-document-new', params: { kind: 'proforma' }, query: { customer: c.id } }" class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-600">+ پیش‌فاکتور</router-link>
        <router-link :to="{ name: 'sales2-document-new', params: { kind: 'invoice' }, query: { customer: c.id } }" class="rounded-xl px-3 py-2 text-sm bg-panel text-white">+ فاکتور</router-link>
        <router-link :to="{ name: 'sales2-receipts', query: { customer: c.id, new: 1 } }" class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-600">+ دریافت</router-link>
      </div>
    </div>

    <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
      <div class="bg-surface rounded-card shadow-soft p-4">
        <p class="text-xs text-slate-500">مانده بدهی</p>
        <p class="text-xl font-bold text-ink ltr-nums mt-1">{{ fa(c.balance.balance_rial) }}</p>
      </div>
      <div class="bg-surface rounded-card shadow-soft p-4">
        <p class="text-xs text-slate-500">چک‌های وصول‌نشده</p>
        <p class="text-xl font-bold text-ink ltr-nums mt-1">{{ fa(c.balance.cheques_pending_rial) }}</p>
      </div>
      <div class="bg-surface rounded-card shadow-soft p-4">
        <p class="text-xs text-slate-500">ریسک کل (مانده + چک)</p>
        <p class="text-xl font-bold text-ink ltr-nums mt-1">{{ fa(c.balance.exposure_rial) }}</p>
      </div>
      <div class="bg-surface rounded-card shadow-soft p-4">
        <p class="text-xs text-slate-500">اعتبار باقی‌مانده</p>
        <p class="text-xl font-bold ltr-nums mt-1" :class="Number(c.balance.available_rial) < 0 ? 'text-red-600' : 'text-emerald-600'">
          {{ c.balance.available_rial === null ? "بدون سقف" : fa(c.balance.available_rial) }}
        </p>
      </div>
    </div>

    <div class="grid lg:grid-cols-3 gap-4">
      <div class="bg-surface rounded-card shadow-soft p-4 space-y-3">
        <h2 class="text-sm font-bold text-ink">شرایط اعتباری</h2>
        <label class="flex items-center gap-2 text-sm"><input v-model="account.unlimited" type="checkbox" /> بدون سقف اعتبار</label>
        <div v-if="!account.unlimited">
          <label class="text-xs text-slate-500 mb-1 block">سقف اعتبار (ریال) — صفر یعنی فقط نقدی</label>
          <MoneyInput v-model="account.credit_limit_rial" :class="inp" />
        </div>
        <div>
          <label class="text-xs text-slate-500 mb-1 block">مهلت پرداخت پیش‌فرض (روز)</label>
          <input v-model.number="account.credit_days" :class="inp" inputmode="numeric" />
        </div>
        <label class="flex items-center gap-2 text-sm text-red-600"><input v-model="account.on_hold" type="checkbox" /> توقف فروش به این مشتری</label>
        <div>
          <label class="text-xs text-slate-500 mb-1 block">یادداشت</label>
          <input v-model="account.note" :class="inp" />
        </div>
        <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
        <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm" @click="saveAccount">ذخیره</button>
        <p v-if="c.payment_terms" class="text-xs text-slate-400">شرایط پرداخت در آرپا: {{ c.payment_terms }}</p>
      </div>

      <div class="bg-surface rounded-card shadow-soft lg:col-span-2 overflow-hidden">
        <div class="flex gap-1 p-2 border-b border-slate-100 text-sm">
          <button class="px-3 py-1.5 rounded-lg" :class="tab === 'docs' ? 'bg-slate-100 text-ink' : 'text-slate-500'" @click="tab = 'docs'">اسناد</button>
          <button class="px-3 py-1.5 rounded-lg" :class="tab === 'statement' ? 'bg-slate-100 text-ink' : 'text-slate-500'" @click="tab = 'statement'">صورتحساب</button>
          <button class="px-3 py-1.5 rounded-lg" :class="tab === 'receipts' ? 'bg-slate-100 text-ink' : 'text-slate-500'" @click="tab = 'receipts'">دریافت‌ها</button>
        </div>
        <div class="overflow-x-auto">
          <table v-if="tab === 'docs'" class="w-full text-sm min-w-[600px]">
            <tbody>
              <tr v-for="d in c.documents" :key="d.id" class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer" @click="openDoc(d.id, d.kind)">
                <td class="px-4 py-2">{{ d.kind_label }} <span class="ltr-nums">{{ d.number }}</span></td>
                <td class="px-3 text-xs text-slate-500">{{ faDate(d.doc_date) }}</td>
                <td class="px-3 ltr-nums">{{ fa(d.total_rial) }}</td>
                <td class="px-3 text-xs text-slate-500">{{ d.status_label }}</td>
              </tr>
              <tr v-if="!c.documents.length"><td class="p-4 text-slate-400 text-sm">سندی صادر نشده.</td></tr>
            </tbody>
          </table>
          <table v-else-if="tab === 'statement'" class="w-full text-sm min-w-[640px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-2">تاریخ</th><th class="text-right font-medium px-3">شرح</th>
                <th class="text-right font-medium px-3">بدهکار</th><th class="text-right font-medium px-3">بستانکار</th><th class="text-right font-medium px-3">مانده</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(e, i) in statement" :key="i" class="border-t border-slate-100">
                <td class="px-4 py-2 text-xs text-slate-500">{{ faDate(e.date) }}</td>
                <td class="px-3">{{ e.label }}</td>
                <td class="px-3 ltr-nums">{{ Number(e.debit) ? fa(e.debit) : "" }}</td>
                <td class="px-3 ltr-nums">{{ Number(e.credit) ? fa(e.credit) : "" }}</td>
                <td class="px-3 ltr-nums font-medium">{{ fa(e.balance) }}</td>
              </tr>
              <tr v-if="!statement.length"><td colspan="5" class="p-4 text-slate-400 text-sm">گردشی ثبت نشده.</td></tr>
            </tbody>
          </table>
          <table v-else class="w-full text-sm min-w-[600px]">
            <tbody>
              <tr v-for="r in c.receipts" :key="r.id" class="border-t border-slate-100" :class="r.counts_as_paid ? '' : 'opacity-50'">
                <td class="px-4 py-2 ltr-nums">{{ r.number }}</td>
                <td class="px-3 text-xs text-slate-500">{{ faDate(r.received_on) }}</td>
                <td class="px-3">{{ r.method_label }} <span v-if="r.cheque_status_label" class="text-xs text-slate-400">({{ r.cheque_status_label }})</span></td>
                <td class="px-3 ltr-nums">{{ fa(r.amount_rial) }}</td>
              </tr>
              <tr v-if="!c.receipts.length"><td class="p-4 text-slate-400 text-sm">دریافتی ثبت نشده.</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>
