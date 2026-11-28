<script setup lang="ts">
import { computed, ref } from "vue";
import { sales2Api, type CommissionFillResult } from "@/api/sales2";
import { apiError } from "@/components/crm/formError";
import { toast } from "@/composables/useUi";

/**
 * تکمیل اکسل پورسانت — finance uploads the month's commission workbook (one
 * sheet per salesperson) and gets it back with «قیمت نهایی کاغذ» filled from
 * the price list in force on each row's تاریخ پیش فاکتور: 200 cartons − 3%.
 * The workbook's own formulas do the rest, so no invoice has to be entered in
 * فروش ۲ first. Rows it cannot price are left empty and listed with the reason.
 */
const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: string | number | null) => (v === null ? "—" : FA.format(Math.round(Number(v))));

const open = ref(false);
const busy = ref(false);
const error = ref("");
const result = ref<CommissionFillResult | null>(null);
const showAll = ref(false);
const input = ref<HTMLInputElement | null>(null);

const shown = computed(() => {
  const rows = result.value?.rows ?? [];
  return showAll.value ? rows : rows.filter((r) => r.status !== "filled");
});

async function upload(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;
  busy.value = true;
  error.value = "";
  result.value = null;
  try {
    result.value = await sales2Api.fillCommissionWorkbook(file);
    const s = result.value.summary;
    toast.success(`${FA.format(s.filled + s.warn)} ردیف قیمت گرفت؛ ${FA.format(s.empty)} ردیف خالی ماند.`);
  } catch (err) {
    error.value = apiError(err);
  } finally {
    busy.value = false;
    if (input.value) input.value.value = "";
  }
}

function download() {
  if (!result.value) return;
  const bin = atob(result.value.file_b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  }));
  const a = document.createElement("a");
  a.href = url;
  a.download = result.value.filename;
  a.click();
  URL.revokeObjectURL(url);
}

const STATUS = {
  filled: { label: "پر شد", cls: "bg-emerald-100 text-emerald-700" },
  warn: { label: "بررسی شود", cls: "bg-amber-100 text-amber-700" },
  empty: { label: "خالی ماند", cls: "bg-red-100 text-red-700" },
} as const;
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft">
    <button class="w-full flex items-center gap-2 px-4 py-3 text-right" @click="open = !open">
      <span class="text-slate-300">{{ open ? "▾" : "◂" }}</span>
      <span class="font-medium text-ink">تکمیل اکسل پورسانت از لیست قیمت</span>
      <span class="text-xs text-slate-400">بدون نیاز به صدور فاکتور در فروش ۲</span>
    </button>
    <div v-if="open" class="px-4 pb-4 space-y-3">
      <p class="text-xs text-slate-500 leading-6">
        اکسل پورسانت ماه را بدهید (هر برگه یک فروشنده). برای هر ردیف، لیست قیمتی که در
        <b>تاریخ پیش‌فاکتور</b> معتبر بوده انتخاب می‌شود (همان گرماژ؛ ردیف با مالیات از لیست رسمی)،
        قیمت <b>۲۰۰ کارتن منهای ۳٪</b> در ستون «قیمت نهایی کاغذ» نوشته می‌شود و بقیه را فرمول‌های خود اکسل حساب می‌کنند.
        ردیفی که تاریخ، گرماژ یا قیمت معتبر ندارد خالی و قرمز می‌ماند. لیست‌های قیمت باید با روز شروعشان در صفحه‌ی «لیست قیمت» وارد شده باشند.
      </p>
      <div class="flex flex-wrap items-center gap-2">
        <label class="rounded-xl px-3 py-2 text-sm bg-panel text-white cursor-pointer" :class="busy ? 'opacity-60' : ''">
          {{ busy ? "در حال محاسبه…" : "انتخاب اکسل پورسانت" }}
          <input ref="input" type="file" accept=".xlsx,.xlsm" class="hidden" :disabled="busy" @change="upload" />
        </label>
        <button v-if="result" class="rounded-xl px-3 py-2 text-sm bg-emerald-600 text-white" @click="download">دریافت اکسل تکمیل‌شده</button>
      </div>
      <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line">{{ error }}</p>

      <template v-if="result">
        <div class="flex flex-wrap gap-2 text-xs">
          <span class="rounded-full px-2 py-0.5 bg-emerald-100 text-emerald-700">{{ FA.format(result.summary.filled) }} پر شد</span>
          <span class="rounded-full px-2 py-0.5 bg-amber-100 text-amber-700">{{ FA.format(result.summary.warn) }} پر شد، بررسی شود</span>
          <span class="rounded-full px-2 py-0.5 bg-red-100 text-red-700">{{ FA.format(result.summary.empty) }} خالی ماند</span>
          <label class="mr-auto flex items-center gap-1 text-slate-500"><input v-model="showAll" type="checkbox" /> همه‌ی ردیف‌ها</label>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-xs min-w-[900px]">
            <thead>
              <tr class="text-slate-400 bg-slate-50">
                <th class="text-right font-medium py-2 px-2">برگه · ردیف</th>
                <th class="text-right font-medium px-2">کالا</th>
                <th class="text-right font-medium px-2">پیش‌فاکتور</th>
                <th class="text-right font-medium px-2">لیست</th>
                <th class="text-right font-medium px-2">۲۰۰ کارتن</th>
                <th class="text-right font-medium px-2">قیمت نهایی</th>
                <th class="text-right font-medium px-2">وضعیت</th>
                <th class="text-right font-medium px-2">توضیح</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in shown" :key="`${r.sheet}-${r.row}`" class="border-t border-slate-100">
                <td class="py-1.5 px-2 whitespace-nowrap">{{ r.sheet }} · {{ FA.format(r.row) }}</td>
                <td class="px-2">{{ r.product }}<span v-if="r.grammage" class="text-slate-400"> · {{ FA.format(r.grammage) }}گ{{ r.official ? " · رسمی" : "" }}</span></td>
                <td class="px-2 ltr-nums">{{ r.pre_date || "—" }}</td>
                <td class="px-2 text-slate-500">{{ r.list || "—" }}</td>
                <td class="px-2 ltr-nums">{{ fa(r.price_200_rial) }}</td>
                <td class="px-2 ltr-nums font-medium">{{ fa(r.final_rial) }}</td>
                <td class="px-2"><span class="rounded-md px-1.5 py-0.5 whitespace-nowrap" :class="STATUS[r.status].cls">{{ STATUS[r.status].label }}</span></td>
                <td class="px-2 text-slate-500">{{ r.status === "filled" ? "" : r.note.split(" | ").pop() }}</td>
              </tr>
              <tr v-if="!shown.length"><td colspan="8" class="py-3 text-center text-slate-400">همه‌ی ردیف‌ها بی‌مشکل پر شدند.</td></tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>
  </div>
</template>
