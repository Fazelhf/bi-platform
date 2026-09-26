<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { sales2Api, type SalesDoc, type Settings } from "@/api/sales2";
import { apiError } from "@/components/crm/formError";
import { faDate } from "@/utils/adminFormat";
import { rialInWords } from "@/utils/numberWords";

/**
 * چاپ رسمی — the page that goes to the customer.
 *
 * Laid out as the standard «صورتحساب فروش کالا و خدمات»: seller and buyer
 * blocks, the lines with their discount and VAT, the total in words, and
 * signature boxes. Always in Rial whatever the app's display unit is — a
 * printed invoice is a legal figure, not a dashboard one.
 */
const route = useRoute();
const doc = ref<SalesDoc | null>(null);
const company = ref<Settings | null>(null);
const error = ref("");

const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));

const title = computed(() => {
  if (!doc.value) return "";
  if (doc.value.kind === "proforma") return "پیش‌فاکتور";
  if (doc.value.kind === "return") return "صورتحساب مرجوعی فروش";
  return doc.value.is_official ? "صورتحساب فروش کالا و خدمات" : "فاکتور فروش";
});

const buyer = computed(() => {
  const d = doc.value!;
  const live = d.status === "draft";
  return {
    name: live ? d.customer_info.name_fa : d.customer_name,
    national_id: live ? d.customer_info.national_id : d.customer_national_id,
    economic_code: live ? d.customer_info.economic_code : d.customer_economic_code,
    address: live ? d.customer_info.address : d.customer_address,
    postal_code: live ? d.customer_info.postal_code : d.customer_postal_code,
    phone: live ? d.customer_info.phone : d.customer_phone,
  };
});

const printPage = () => window.print();
const closePage = () => window.close();

onMounted(async () => {
  try {
    const data = await sales2Api.printData(Number(route.params.id));
    doc.value = data.document;
    company.value = data.company;
    document.title = `${title.value} ${data.document.number}`;
  } catch (e) {
    error.value = apiError(e);
  }
});
</script>

<template>
  <div dir="rtl" class="print-root min-h-screen bg-slate-200 print:bg-white py-6 print:py-0">
    <div class="no-print max-w-[210mm] mx-auto mb-3 flex gap-2 px-2">
      <button class="bg-slate-900 text-white rounded-xl px-4 py-2 text-sm" @click="printPage">چاپ / ذخیره PDF</button>
      <button class="bg-white text-slate-600 rounded-xl px-4 py-2 text-sm" @click="closePage">بستن</button>
      <span v-if="doc?.status === 'draft'" class="text-sm text-amber-700 self-center">این سند هنوز صادر نشده و شماره ندارد.</span>
    </div>

    <p v-if="error" class="max-w-[210mm] mx-auto bg-red-50 text-red-600 p-3 rounded">{{ error }}</p>

    <article v-if="doc && company" class="sheet bg-white text-black mx-auto shadow print:shadow-none">
      <div v-if="doc.status === 'cancelled'" class="watermark">ابطال شده</div>
      <div v-else-if="doc.status === 'draft'" class="watermark">پیش‌نویس</div>

      <header class="flex items-start justify-between gap-4 mb-3">
        <div class="text-xs leading-6 w-1/3">
          <div>شماره: <b class="ltr-nums">{{ doc.number || "—" }}</b></div>
          <div>تاریخ: <b>{{ faDate(doc.doc_date) }}</b></div>
          <div v-if="doc.kind === 'proforma' && doc.valid_until">اعتبار تا: <b>{{ faDate(doc.valid_until) }}</b></div>
          <div v-if="doc.kind === 'invoice' && doc.due_date">سررسید: <b>{{ faDate(doc.due_date) }}</b></div>
          <div v-if="doc.source_number">عطف به: <b class="ltr-nums">{{ doc.source_number }}</b></div>
        </div>
        <h1 class="text-lg font-bold text-center w-1/3 pt-2">{{ title }}</h1>
        <div class="w-1/3" />
      </header>

      <section class="box">
        <div class="box-title">مشخصات فروشنده</div>
        <div class="grid grid-cols-3 gap-x-4 gap-y-1 text-xs p-2">
          <div class="col-span-3">نام: <b>{{ company.company_name || "—" }}</b></div>
          <div>شناسه ملی: <span class="ltr-nums">{{ company.national_id || "—" }}</span></div>
          <div>کد اقتصادی: <span class="ltr-nums">{{ company.economic_code || "—" }}</span></div>
          <div>شماره ثبت: <span class="ltr-nums">{{ company.registration_no || "—" }}</span></div>
          <div class="col-span-2">نشانی: {{ company.address || "—" }}</div>
          <div>کد پستی: <span class="ltr-nums">{{ company.postal_code || "—" }}</span> · تلفن: <span class="ltr-nums">{{ company.phone || "—" }}</span></div>
        </div>
      </section>

      <section class="box">
        <div class="box-title">مشخصات خریدار</div>
        <div class="grid grid-cols-3 gap-x-4 gap-y-1 text-xs p-2">
          <div class="col-span-3">نام: <b>{{ buyer.name }}</b></div>
          <div>شناسه / کد ملی: <span class="ltr-nums">{{ buyer.national_id || "—" }}</span></div>
          <div>کد اقتصادی: <span class="ltr-nums">{{ buyer.economic_code || "—" }}</span></div>
          <div>تلفن: <span class="ltr-nums">{{ buyer.phone || "—" }}</span></div>
          <div class="col-span-2">نشانی: {{ buyer.address || "—" }}</div>
          <div>کد پستی: <span class="ltr-nums">{{ buyer.postal_code || "—" }}</span></div>
        </div>
      </section>

      <table class="lines w-full text-[11px] mt-2">
        <thead>
          <tr>
            <th>ردیف</th><th>کد کالا</th><th class="w-[30%]">شرح کالا</th><th>مقدار</th><th>واحد</th>
            <th>مبلغ واحد</th><th>مبلغ کل</th><th>تخفیف</th><th>پس از تخفیف</th>
            <th v-if="doc.is_official">ارزش افزوده</th><th>جمع کل</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(l, i) in doc.lines" :key="l.id">
            <td>{{ FA.format(i + 1) }}</td>
            <td class="ltr-nums">{{ l.product_code?.replace(/^pr-/, "") }}</td>
            <td class="text-right">{{ l.product_name }}<div v-if="l.description" class="text-[10px] text-gray-600">{{ l.description }}</div></td>
            <td>{{ fa(l.quantity) }}</td>
            <td>{{ l.unit }}</td>
            <td>{{ fa(l.unit_price_rial) }}</td>
            <td>{{ fa(l.gross_rial) }}</td>
            <td>{{ fa(l.discount_rial) }}</td>
            <td>{{ fa(l.net_rial) }}</td>
            <td v-if="doc.is_official">{{ fa(l.vat_rial) }}</td>
            <td><b>{{ fa(l.total_rial) }}</b></td>
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <td :colspan="6" class="text-right">جمع</td>
            <td>{{ fa(doc.subtotal_rial) }}</td>
            <td>{{ fa(doc.discount_rial) }}</td>
            <td>{{ fa(doc.net_rial) }}</td>
            <td v-if="doc.is_official">{{ fa(doc.vat_rial) }}</td>
            <td><b>{{ fa(doc.total_rial) }}</b></td>
          </tr>
        </tfoot>
      </table>

      <div class="box mt-2 text-xs p-2 flex flex-wrap justify-between gap-2">
        <span>مبلغ قابل پرداخت به حروف: <b>{{ rialInWords(doc.total_rial) }}</b></span>
        <span>نحوه‌ی تسویه: <b>{{ doc.settlement_label }}</b></span>
      </div>

      <div v-if="doc.note" class="text-xs mt-2 whitespace-pre-line">توضیحات: {{ doc.note }}</div>
      <div v-if="company.print_terms" class="text-[10px] mt-2 whitespace-pre-line text-gray-700">{{ company.print_terms }}</div>

      <footer class="grid grid-cols-2 gap-6 mt-8 text-xs text-center">
        <div class="sign">مهر و امضای فروشنده</div>
        <div class="sign">مهر و امضای خریدار</div>
      </footer>
    </article>
  </div>
</template>

<style scoped>
.sheet {
  width: 210mm;
  min-height: 297mm;
  padding: 12mm;
  position: relative;
  font-size: 12px;
}
.box { border: 1px solid #333; border-radius: 4px; margin-top: 6px; }
.box-title { background: #eee; border-bottom: 1px solid #333; padding: 2px 8px; font-size: 11px; font-weight: 700; }
.lines { border-collapse: collapse; }
.lines th, .lines td { border: 1px solid #333; padding: 3px 4px; text-align: center; }
.lines thead th { background: #eee; font-weight: 700; }
.lines tfoot td { background: #f6f6f6; font-weight: 700; }
.sign { border-top: 1px dashed #555; padding-top: 6px; height: 28mm; }
.watermark {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-size: 90px; font-weight: 800; color: rgba(200, 0, 0, 0.08); transform: rotate(-25deg);
  pointer-events: none;
}
@media print {
  @page { size: A4; margin: 0; }
  .no-print { display: none !important; }
  .sheet { box-shadow: none; margin: 0; }
}
</style>
