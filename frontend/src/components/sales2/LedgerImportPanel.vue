<script setup lang="ts">
import { ref, watch } from "vue";
import { sales2Api, type LedgerBook, type LedgerIssue, type LedgerParsed } from "@/api/sales2";
import CustomerSearch from "./CustomerSearch.vue";
import { apiError } from "@/components/crm/formError";
import { toast } from "@/composables/useUi";
import { faDigits, isoToJalali } from "@/utils/jalali";

/**
 * Bringing files in.
 *
 * «دفتر حساب»: آرپا exports one customer per file, so several can be dropped
 * at once; each is read first (nothing saved), its customer guessed from the
 * file name («اجاقلو.xlsx»), and saved only when a person has confirmed the
 * customer and the book. Saving replaces that customer's ledger in that book.
 *
 * «گزارش وصولی»: finance's own workbook — its newest sheet gives each
 * customer's توضیحات، بازاریاب and the hand-typed مانده, kept beside the
 * computed one so any difference shows.
 */
const props = defineProps<{ book: LedgerBook }>();
const emit = defineEmits<{ (e: "imported"): void }>();

const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));
const jd = (iso: string | null) => {
  const j = iso ? isoToJalali(iso) : null;
  return j ? faDigits(`${j.jy}/${String(j.jm).padStart(2, "0")}/${String(j.jd).padStart(2, "0")}`) : "—";
};

interface Pending {
  file: File;
  book: LedgerBook;
  customer: number | null;
  customerLabel: string;
  parsed: LedgerParsed | null;
  suggestions: { id: number; name: string }[];
  error: string;
  busy: boolean;
  done: { balance: string; reconciled: boolean; issues: LedgerIssue[] } | null;
}

const mode = ref<"ledger" | "collections">("ledger");
const pending = ref<Pending[]>([]);
const ledgerInput = ref<HTMLInputElement | null>(null);
const collectionsBook = ref<LedgerBook>(props.book);
watch(() => props.book, (b) => { collectionsBook.value = b; });
const collectionsResult = ref<Awaited<ReturnType<typeof sales2Api.ledgerCollectionsImport>> | null>(null);
const collectionsBusy = ref(false);
const collectionsError = ref("");

async function addFiles(e: Event) {
  const files = Array.from((e.target as HTMLInputElement).files ?? []);
  (e.target as HTMLInputElement).value = "";
  for (const file of files) {
    const p: Pending = {
      file, book: props.book, customer: null, customerLabel: "", parsed: null, suggestions: [],
      error: "", busy: true, done: null,
    };
    pending.value.push(p);
    const item = pending.value[pending.value.length - 1];
    try {
      const res = await sales2Api.ledgerPreview(file, item.book);
      item.parsed = res.parsed;
      item.suggestions = res.suggestions;
      if (res.suggestions.length === 1) {
        item.customer = res.suggestions[0].id;
        item.customerLabel = res.suggestions[0].name;
      }
    } catch (err) {
      item.error = apiError(err);
    } finally {
      item.busy = false;
    }
  }
}

function choose(p: Pending, s: { id: number; name: string }) {
  p.customer = s.id;
  p.customerLabel = s.name;
}

async function save(p: Pending) {
  if (!p.customer || !p.parsed) return;
  p.busy = true;
  p.error = "";
  try {
    const res = await sales2Api.ledgerImport(p.file, p.book, p.customer);
    p.done = { balance: res.balance, reconciled: res.reconciled, issues: res.issues };
    toast.success(`دفتر «${res.name}» وارد شد: ${fa(res.parsed.rows)} ردیف، مانده ${fa(res.balance)}`);
    emit("imported");
  } catch (err) {
    p.error = apiError(err);
  } finally {
    p.busy = false;
  }
}

async function saveAll() {
  for (const p of pending.value) {
    if (!p.done && p.customer && p.parsed && !p.busy) await save(p);
  }
}

async function importCollections(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  (e.target as HTMLInputElement).value = "";
  if (!file) return;
  collectionsBusy.value = true;
  collectionsError.value = "";
  try {
    collectionsResult.value = await sales2Api.ledgerCollectionsImport(file, collectionsBook.value);
    emit("imported");
  } catch (err) {
    collectionsError.value = apiError(err);
  } finally {
    collectionsBusy.value = false;
  }
}
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4 space-y-4">
    <div class="flex flex-wrap gap-2">
      <button
        class="rounded-xl px-3 py-1.5 text-sm"
        :class="mode === 'ledger' ? 'bg-panel text-white' : 'bg-slate-100 text-slate-600'"
        @click="mode = 'ledger'"
      >دفتر حساب مشتری (آرپا)</button>
      <button
        class="rounded-xl px-3 py-1.5 text-sm"
        :class="mode === 'collections' ? 'bg-panel text-white' : 'bg-slate-100 text-slate-600'"
        @click="mode = 'collections'"
      >گزارش وصولی دستی</button>
    </div>

    <!-- ---- دفتر حساب ---- -->
    <template v-if="mode === 'ledger'">
      <p class="text-xs text-slate-500 leading-6">
        در آرپا «دفتر حساب» هر طرف حساب را با ستون‌های شماره سند، تاریخ سند، مبلغ بدهکار، مبلغ بستانکار، مانده، وضعیت و شرح ردیف سند
        خروجی اکسل بگیرید. چند فایل را با هم می‌شود انتخاب کرد؛ مشتری از نام فایل حدس زده می‌شود. ورود دوباره، دفتر قبلی همان مشتری در همان دفتر را جایگزین می‌کند.
      </p>
      <div class="flex flex-wrap items-center gap-2">
        <input ref="ledgerInput" type="file" accept=".xlsx,.xlsm" multiple class="hidden" @change="addFiles" />
        <button class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-700" @click="ledgerInput?.click()">انتخاب فایل‌ها…</button>
        <button
          v-if="pending.some((p) => !p.done && p.customer && p.parsed)"
          class="rounded-xl px-4 py-2 text-sm bg-panel text-white" @click="saveAll"
        >ثبت همه</button>
        <button v-if="pending.length" class="text-xs text-slate-400" @click="pending = []">پاک کردن فهرست</button>
      </div>

      <div v-for="(p, i) in pending" :key="i" class="border border-slate-100 rounded-xl p-3 space-y-2">
        <div class="flex flex-wrap items-center gap-2">
          <span class="font-medium text-ink text-sm">{{ p.file.name }}</span>
          <span v-if="p.busy" class="text-xs text-slate-400">در حال خواندن…</span>
          <span v-if="p.done" class="text-xs" :class="p.done.reconciled ? 'text-emerald-600' : 'text-red-600'">
            {{ p.done.reconciled ? "✓ ثبت شد و با مانده‌ی آرپا می‌خواند" : "ثبت شد ولی با مانده‌ی آرپا نمی‌خواند" }}
            · مانده {{ fa(p.done.balance) }}
          </span>
        </div>
        <p v-if="p.error" class="bg-red-50 text-red-600 text-xs rounded-lg px-2 py-1">{{ p.error }}</p>
        <div v-if="p.parsed" class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
          <span>{{ fa(p.parsed.rows) }} ردیف · از {{ jd(p.parsed.first_date) }} تا {{ jd(p.parsed.last_date) }}</span>
          <span>فاکتور {{ fa(p.parsed.invoices) }} · دریافت {{ fa(p.parsed.receipts) }}<template v-if="p.parsed.returns"> · برگشت {{ fa(p.parsed.returns) }}</template><template v-if="p.parsed.other"> · سایر {{ fa(p.parsed.other) }}</template></span>
          <span>قبل از دوره {{ fa(p.parsed.opening) }} · بدهکار {{ fa(p.parsed.debit) }} · بستانکار {{ fa(p.parsed.credit) }}</span>
          <span class="text-ink">مانده آرپا {{ fa(p.parsed.file_balance) }}</span>
        </div>
        <div v-if="p.parsed && !p.done" class="flex flex-wrap items-start gap-2">
          <select v-model="p.book" class="bg-slate-100 rounded-lg px-2 py-2 text-sm text-ink">
            <option value="main">دفتر اصلی</option>
            <option value="second">دفتر دوم (رول مارکت)</option>
          </select>
          <div class="flex-1 min-w-[220px]">
            <CustomerSearch v-model="p.customer" :label="p.customerLabel" @picked="(c) => (p.customerLabel = c?.name_fa ?? '')" />
            <div v-if="p.suggestions.length > 1 && !p.customer" class="flex flex-wrap gap-1 mt-1">
              <button
                v-for="s in p.suggestions" :key="s.id"
                class="text-xs rounded-lg bg-sky-50 text-sky-700 px-2 py-1" @click="choose(p, s)"
              >{{ s.name }}</button>
            </div>
          </div>
          <button
            class="rounded-xl px-4 py-2 text-sm bg-panel text-white" :disabled="!p.customer || p.busy"
            @click="save(p)"
          >ثبت</button>
        </div>
        <ul v-if="p.done?.issues.length" class="text-xs space-y-0.5">
          <li v-for="(x, j) in p.done.issues" :key="j" :class="x.level === 'error' ? 'text-red-600' : x.level === 'warn' ? 'text-amber-600' : 'text-slate-500'">
            {{ x.message }}
          </li>
        </ul>
      </div>
    </template>

    <!-- ---- گزارش وصولی ---- -->
    <template v-else>
      <p class="text-xs text-slate-500 leading-6">
        فایل «گزارش وصولی» که تا امروز دستی پر می‌شد: از جدیدترین برگه، توضیحات و بازاریاب هر مشتری می‌آید و مانده‌ی دستی کنار مانده‌ی محاسبه‌شده می‌نشیند تا اختلاف دیده شود.
        مشتری با کد تفصیل آرپا و بعد با نام پیدا می‌شود؛ مشتری تازه‌ای ساخته نمی‌شود.
      </p>
      <div class="flex flex-wrap items-center gap-2">
        <select v-model="collectionsBook" class="bg-slate-100 rounded-lg px-2 py-2 text-sm text-ink">
          <option value="main">دفتر اصلی</option>
          <option value="second">دفتر دوم (رول مارکت)</option>
        </select>
        <label class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-700 cursor-pointer">
          {{ collectionsBusy ? "در حال خواندن…" : "انتخاب فایل گزارش وصولی…" }}
          <input type="file" accept=".xlsx,.xlsm" class="hidden" :disabled="collectionsBusy" @change="importCollections" />
        </label>
      </div>
      <p v-if="collectionsError" class="bg-red-50 text-red-600 text-xs rounded-lg px-2 py-1">{{ collectionsError }}</p>
      <div v-if="collectionsResult" class="text-sm space-y-2">
        <p class="text-ink">
          برگه‌ی {{ faDigits(collectionsResult.sheet) }} (منتهی به {{ jd(collectionsResult.as_of) }}):
          {{ fa(collectionsResult.matched) }} مشتری پیدا شد<template v-if="collectionsResult.unmatched.length">، {{ fa(collectionsResult.unmatched.length) }} پیدا نشد</template>.
        </p>
        <div v-if="collectionsResult.unmatched.length" class="max-h-56 overflow-y-auto border border-slate-100 rounded-xl">
          <table class="w-full text-xs">
            <tr class="bg-slate-50 text-slate-500"><th class="text-right px-2 py-1.5">کد</th><th class="text-right px-2">نام</th><th class="text-right px-2">مانده دستی</th></tr>
            <tr v-for="u in collectionsResult.unmatched" :key="u.code + u.name" class="border-t border-slate-100">
              <td class="px-2 py-1 ltr-nums">{{ faDigits(u.code) }}</td><td class="px-2">{{ u.name }}</td>
              <td class="px-2 ltr-nums">{{ u.balance === null ? "" : fa(u.balance) }}</td>
            </tr>
          </table>
        </div>
        <p v-if="collectionsResult.unmatched.length" class="text-xs text-slate-500">
          این‌ها در CRM با این کد یا نام نیستند؛ با ورود دفتر حسابشان و انتخاب دستی مشتری اضافه می‌شوند.
        </p>
      </div>
    </template>
  </div>
</template>
