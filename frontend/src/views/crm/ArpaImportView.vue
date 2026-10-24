<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  crmApi,
  type ArpaBook,
  type ArpaImportResult,
  type ArpaImportRow,
  type SuspectInvoice,
  type SuspectList,
  type SuspectState,
} from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num, rial } from "@/utils/format";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import NavIcon from "@/components/NavIcon.vue";

/**
 * ورود از آرپا — the sales invoices come in from accounting, nowhere else.
 *
 * Choosing a file runs the import as a preview straight away (the server does
 * the whole thing and rolls it back), so what «ثبت» will do is on screen
 * before anyone commits to it: how many invoices are new, changed, already
 * in, and how many are held back as فروش سوری. Uploading the same export twice
 * says so instead of doing anything.
 *
 * فروش سوری is the second tab: invoices whose «مسوول فروش» was not one of the
 * three sales groups. They count nowhere until a manager rules on them, and
 * ruling one «واقعی» means saying which group sold it — the one fact آرپا did
 * not record.
 */
const crm = useCrmStore();
const route = useRoute();
const router = useRouter();

type Tab = "upload" | "suspect" | "history";
const tab = ref<Tab>((route.query.tab as Tab) || "upload");
watch(tab, (t) => router.replace({ query: { ...route.query, tab: t } }));

const CHANNELS = [
  { key: "team", label: "فروش همکار" },
  { key: "organizational", label: "فروش بانکی" },
  { key: "b2b", label: "فروش سازمانی" },
] as const;
const channelLabel = (k: string) => CHANNELS.find((c) => c.key === k)?.label ?? "—";

function jdate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString("fa-IR") : "—";
}
function jdatetime(iso: string | null): string {
  return iso
    ? new Date(iso).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" })
    : "—";
}

// ---- upload -------------------------------------------------------------------
const file = ref<File | null>(null);
const book = ref<ArpaBook>("main");
const preview = ref<ArpaImportResult | null>(null);
const done = ref<ArpaImportResult | null>(null);
const busy = ref<"" | "preview" | "commit">("");
const error = ref("");
const dragging = ref(false);
const input = ref<HTMLInputElement | null>(null);

/** آرپا names nothing in the file; the file name usually does. */
function guessBook(name: string): ArpaBook {
  return /رول|مارکت|market/i.test(name) ? "rollmarket" : "main";
}

function pick(f: File | null | undefined) {
  if (!f) return;
  file.value = f;
  book.value = guessBook(f.name);
  done.value = null;
  runPreview();
}

function onDrop(e: DragEvent) {
  dragging.value = false;
  pick(e.dataTransfer?.files?.[0]);
}

async function runPreview() {
  if (!file.value) return;
  busy.value = "preview";
  error.value = "";
  preview.value = null;
  try {
    preview.value = await crmApi.arpaImport(file.value, book.value, false);
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? "فایل خوانده نشد.";
  } finally {
    busy.value = "";
  }
}

watch(book, () => { if (file.value && !done.value) runPreview(); });

async function commit() {
  if (!file.value) return;
  busy.value = "commit";
  error.value = "";
  try {
    done.value = await crmApi.arpaImport(file.value, book.value, true);
    preview.value = null;
    crm.bump();
    await Promise.all([loadHistory(), loadSuspect()]);
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? "ثبت انجام نشد.";
  } finally {
    busy.value = "";
  }
}

function reset() {
  file.value = null;
  preview.value = null;
  done.value = null;
  error.value = "";
  if (input.value) input.value.value = "";
}

const shown = computed(() => done.value ?? preview.value);

// ---- فروش سوری ------------------------------------------------------------------
const state = ref<SuspectState>("suspect");
const list = ref<SuspectList | null>(null);
const loadingList = ref(false);
const search = ref("");
const selected = ref<Set<number>>(new Set());
const decideChannel = ref("");
const deciding = ref(false);
const listError = ref("");

async function loadSuspect() {
  loadingList.value = true;
  try {
    list.value = await crmApi.suspectInvoices({ state: state.value, search: search.value });
    selected.value = new Set();
  } finally {
    loadingList.value = false;
  }
}
watch(state, loadSuspect);
let searchTimer: number | undefined;
watch(search, () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(loadSuspect, 300);
});

const rows = computed<SuspectInvoice[]>(() => list.value?.rows ?? []);
const allChecked = computed(() => rows.value.length > 0 && rows.value.every((r) => selected.value.has(r.id)));
function toggleAll() {
  selected.value = allChecked.value ? new Set() : new Set(rows.value.map((r) => r.id));
}
function toggle(id: number) {
  const s = new Set(selected.value);
  s.has(id) ? s.delete(id) : s.add(id);
  selected.value = s;
}
const selectedAmount = computed(() =>
  rows.value.filter((r) => selected.value.has(r.id)).reduce((a, r) => a + r.amount, 0),
);

async function decide(decision: SuspectState) {
  listError.value = "";
  if (decision === "real" && !decideChannel.value) {
    listError.value = "برای فروش واقعی، اول گروه فروش را انتخاب کنید.";
    return;
  }
  deciding.value = true;
  try {
    await crmApi.decideSuspect([...selected.value], decision, decideChannel.value);
    crm.bump();
    await Promise.all([loadSuspect(), loadHistory()]);
  } catch (e: any) {
    listError.value = e?.response?.data?.detail ?? "ثبت تصمیم انجام نشد.";
  } finally {
    deciding.value = false;
  }
}

const STATES: { key: SuspectState; label: string }[] = [
  { key: "suspect", label: "در انتظار بررسی" },
  { key: "real", label: "تأیید: واقعی" },
  { key: "fake", label: "تأیید: سوری" },
];

// ---- history -------------------------------------------------------------------
const history = ref<ArpaImportRow[]>([]);
const pending = ref(0);
const loadingHistory = ref(true);
async function loadHistory() {
  try {
    const r = await crmApi.arpaImports();
    history.value = r.imports;
    pending.value = r.pending_suspect;
  } finally {
    loadingHistory.value = false;
  }
}

onMounted(() => Promise.all([loadHistory(), loadSuspect()]));

const card = "bg-surface rounded-card shadow-soft p-4 min-w-0";
const tile = "bg-slate-50 rounded-xl p-3";
</script>

<template>
  <div class="space-y-4">
    <!-- Tabs -->
    <div class="flex flex-wrap items-center gap-2">
      <div class="flex bg-surface shadow-soft rounded-xl p-1 text-sm">
        <button
          v-for="t in ([['upload', 'بارگذاری فایل'], ['suspect', 'فروش سوری'], ['history', 'سابقه‌ی ورود']] as const)"
          :key="t[0]"
          class="px-4 py-2 rounded-lg transition flex items-center gap-2"
          :class="tab === t[0] ? 'bg-panel text-white' : 'text-slate-500 hover:text-ink'"
          @click="tab = t[0]"
        >
          {{ t[1] }}
          <span
            v-if="t[0] === 'suspect' && pending"
            class="text-[10px] rounded-full px-1.5 py-0.5"
            :class="tab === 'suspect' ? 'bg-white/20' : 'bg-amber-100 text-amber-700'"
          >{{ num(pending) }}</span>
        </button>
      </div>
      <p class="text-xs text-slate-400">فاکتورهای فروش فقط از آرپا وارد می‌شوند.</p>
    </div>

    <!-- ================= Upload ================= -->
    <template v-if="tab === 'upload'">
      <div :class="card">
        <div
          class="border-2 border-dashed rounded-2xl px-6 py-10 text-center transition cursor-pointer"
          :class="dragging ? 'border-sky-400 bg-sky-50' : 'border-slate-200 hover:border-slate-300'"
          @click="input?.click()"
          @dragover.prevent="dragging = true"
          @dragleave="dragging = false"
          @drop.prevent="onDrop"
        >
          <input ref="input" type="file" accept=".slk,.xlsx" class="hidden" @change="pick(($event.target as HTMLInputElement).files?.[0])" />
          <span class="w-12 h-12 rounded-2xl bg-slate-100 text-slate-500 grid place-items-center mx-auto">
            <NavIcon name="upload" :size="22" />
          </span>
          <p v-if="!file" class="mt-3 text-ink font-medium">خروجی «فاکتور فروش» آرپا را اینجا بکشید یا کلیک کنید</p>
          <p v-else class="mt-3 text-ink font-medium" dir="auto">{{ file.name }}</p>
          <p class="text-xs text-slate-400 mt-1">فایل ‎.slk‎ همان‌طور که آرپا می‌دهد، یا ‎.xlsx‎ — هر ۵۲ ستون خوانده می‌شود</p>
        </div>

        <div class="flex flex-wrap items-center gap-3 mt-4">
          <span class="text-sm text-slate-500">دفتر:</span>
          <div class="flex bg-slate-100 rounded-xl p-0.5 text-sm">
            <button
              v-for="b in ([['main', 'دفتر اصلی'], ['rollmarket', 'رول مارکت']] as const)" :key="b[0]"
              class="px-3 py-1.5 rounded-lg transition"
              :class="book === b[0] ? 'bg-surface shadow-soft text-ink' : 'text-slate-500 hover:text-ink'"
              :disabled="!!busy"
              @click="book = b[0]"
            >{{ b[1] }}</button>
          </div>
          <span class="text-[11px] text-slate-400">شماره‌ی فاکتورهای دو دفتر جداست؛ دفتر را درست انتخاب کنید.</span>
          <span class="flex-1"></span>
          <button v-if="file" class="text-sm text-slate-500 hover:text-ink" @click="reset">فایل دیگر</button>
        </div>
      </div>

      <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3">{{ error }}</p>

      <div v-if="busy === 'preview'" class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Skeleton v-for="i in 4" :key="i" class="h-20 rounded-card" />
      </div>

      <!-- Preview or result -->
      <div v-if="shown && !busy" :class="card" class="space-y-4">
        <!-- Nothing new: the file, or every row in it, is already in. -->
        <div v-if="shown.nothing_new" class="flex items-start gap-3 bg-sky-50 text-sky-800 rounded-xl px-4 py-3">
          <NavIcon name="check" :size="20" />
          <div class="text-sm leading-6">
            <p class="font-semibold">همه‌ی {{ num(shown.rows) }} فاکتور این فایل قبلاً خوانده شده‌اند؛ چیز تازه‌ای برای ثبت نیست.</p>
            <p v-if="shown.previous" class="text-xs">همین فایل {{ jdatetime(shown.previous.at) }} وارد شده بود.</p>
          </div>
        </div>
        <div v-else-if="shown.committed" class="flex items-start gap-3 bg-emerald-50 text-emerald-800 rounded-xl px-4 py-3">
          <NavIcon name="check" :size="20" />
          <p class="text-sm font-semibold leading-6">
            ثبت شد: {{ num(shown.created) }} فاکتور جدید، {{ num(shown.updated) }} به‌روزشده.
          </p>
        </div>
        <div v-else class="flex flex-wrap items-baseline gap-2">
          <h3 class="font-bold text-ink">پیش‌نمایش — هنوز چیزی ثبت نشده</h3>
          <span class="text-xs text-slate-400">
            {{ shown.book === "rollmarket" ? "رول مارکت" : "دفتر اصلی" }} ·
            {{ jdate(shown.date_from) }} تا {{ jdate(shown.date_to) }} · {{ num(shown.columns) }} ستون
          </span>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 text-sm">
          <div :class="tile">
            <p class="text-[11px] text-slate-400">فاکتور در فایل</p>
            <p class="font-bold text-ink text-lg mt-0.5">{{ num(shown.rows) }}</p>
            <p class="text-[11px] text-slate-400">{{ rial(shown.amount) }}</p>
          </div>
          <div :class="tile">
            <p class="text-[11px] text-slate-400">جدید</p>
            <p class="font-bold text-lg mt-0.5" :class="shown.created ? 'text-emerald-600' : 'text-ink'">{{ num(shown.created) }}</p>
          </div>
          <div :class="tile">
            <p class="text-[11px] text-slate-400">تغییرکرده در آرپا</p>
            <p class="font-bold text-lg mt-0.5" :class="shown.updated ? 'text-sky-600' : 'text-ink'">{{ num(shown.updated) }}</p>
          </div>
          <div :class="tile">
            <p class="text-[11px] text-slate-400">قبلاً خوانده شده</p>
            <p class="font-bold text-ink text-lg mt-0.5">{{ num(shown.unchanged) }}</p>
          </div>
          <div :class="tile">
            <p class="text-[11px] text-slate-400">مشتری جدید</p>
            <p class="font-bold text-ink text-lg mt-0.5">{{ num(shown.customers_created) }}</p>
          </div>
          <div class="rounded-xl p-3" :class="shown.suspect ? 'bg-amber-50' : 'bg-slate-50'">
            <p class="text-[11px]" :class="shown.suspect ? 'text-amber-700' : 'text-slate-400'">فروش سوری (بدون مسوول فروش)</p>
            <p class="font-bold text-lg mt-0.5" :class="shown.suspect ? 'text-amber-700' : 'text-ink'">{{ num(shown.suspect) }}</p>
            <p v-if="shown.suspect" class="text-[11px] text-amber-700">{{ rial(shown.suspect_amount) }}</p>
          </div>
        </div>

        <div v-if="Object.keys(shown.by_channel).length" class="flex flex-wrap gap-2 text-xs">
          <span class="text-slate-400">فروش شمرده‌شده:</span>
          <span v-for="(v, k) in shown.by_channel" :key="k" class="bg-slate-100 text-slate-600 rounded-full px-2.5 py-1">
            {{ channelLabel(String(k)) }}: {{ rial(v) }}
          </span>
          <span v-if="shown.by_kind.return" class="bg-red-50 text-red-500 rounded-full px-2.5 py-1">
            مرجوعی: {{ num(shown.by_kind.return.count) }} · {{ rial(shown.by_kind.return.amount) }}
          </span>
        </div>

        <div v-if="shown.unknown_reps.length" class="text-xs text-slate-500 bg-slate-50 rounded-xl px-4 py-3 leading-6">
          <p class="font-medium text-slate-600">بازاریاب‌هایی که در فهرست کارشناسان نیستند — فاکتورشان بدون کارشناس ثبت می‌شود:</p>
          <span v-for="r in shown.unknown_reps" :key="r.name" class="inline-block ml-3">{{ r.name }} ({{ num(r.count) }})</span>
        </div>

        <div v-if="shown.skipped.length" class="text-xs text-red-600 bg-red-50 rounded-xl px-4 py-3 leading-6">
          <p class="font-medium">{{ num(shown.skipped.length) }} ردیف رد شد:</p>
          <span v-for="(s, i) in shown.skipped.slice(0, 10)" :key="i" class="block">برگه {{ s.number || "؟" }} — {{ s.reason }}</span>
        </div>

        <div class="flex flex-wrap items-center gap-3 pt-1">
          <button
            v-if="!shown.committed && !shown.nothing_new"
            class="bg-panel text-white rounded-xl px-5 py-2.5 text-sm disabled:opacity-50"
            :disabled="!!busy"
            @click="commit"
          >ثبت {{ num(shown.created + shown.updated) }} فاکتور در سیستم</button>
          <button
            v-if="shown.committed && shown.suspect"
            class="bg-amber-500 text-white rounded-xl px-5 py-2.5 text-sm"
            @click="tab = 'suspect'"
          >بررسی فروش سوری</button>
          <button v-if="shown.committed || shown.nothing_new" class="text-sm text-slate-500 hover:text-ink" @click="reset">فایل بعدی</button>
        </div>
      </div>
      <div v-if="busy === 'commit'" class="text-sm text-slate-500 px-1">در حال ثبت…</div>
    </template>

    <!-- ================= فروش سوری ================= -->
    <template v-else-if="tab === 'suspect'">
      <div :class="card" class="space-y-3">
        <p class="text-xs text-slate-500 leading-6">
          فاکتورهایی که «مسوول فروش» آن‌ها فروش همکار، بانکی یا سازمانی نبوده. تا وقتی بررسی نشده‌اند در هیچ گزارشی شمرده نمی‌شوند.
          «واقعی» را با گروه فروشش تأیید کنید تا وارد گزارش‌ها شود؛ «سوری» برای همیشه بیرون می‌ماند.
        </p>
        <div class="flex flex-wrap items-center gap-2">
          <div class="flex bg-slate-100 rounded-xl p-0.5 text-sm">
            <button
              v-for="s in STATES" :key="s.key"
              class="px-3 py-1.5 rounded-lg transition flex items-center gap-1.5"
              :class="state === s.key ? 'bg-surface shadow-soft text-ink' : 'text-slate-500 hover:text-ink'"
              @click="state = s.key"
            >
              {{ s.label }}
              <span class="text-[10px] text-slate-400">{{ num(list?.counts[s.key]?.count ?? 0) }}</span>
            </button>
          </div>
          <span v-if="list?.counts[state]" class="text-xs text-slate-400">{{ rial(list.counts[state]!.amount) }}</span>
          <span class="flex-1"></span>
          <input
            v-model="search"
            class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 w-56"
            placeholder="جستجوی شماره یا مشتری"
          />
        </div>

        <!-- Bulk bar -->
        <div v-if="selected.size" class="flex flex-wrap items-center gap-2 bg-slate-50 rounded-xl px-3 py-2.5 text-sm">
          <span class="text-ink font-medium">{{ num(selected.size) }} فاکتور · {{ rial(selectedAmount) }}</span>
          <span class="flex-1"></span>
          <template v-if="state === 'suspect'">
            <select v-model="decideChannel" class="bg-surface rounded-lg px-2 py-1.5 text-sm border border-slate-200">
              <option value="">گروه فروش…</option>
              <option v-for="c in CHANNELS" :key="c.key" :value="c.key">{{ c.label }}</option>
            </select>
            <button class="bg-emerald-600 text-white rounded-lg px-3 py-1.5 disabled:opacity-50" :disabled="deciding" @click="decide('real')">فروش واقعی است</button>
            <button class="bg-red-500 text-white rounded-lg px-3 py-1.5 disabled:opacity-50" :disabled="deciding" @click="decide('fake')">سوری است</button>
          </template>
          <button v-else class="bg-surface border border-slate-200 rounded-lg px-3 py-1.5 disabled:opacity-50" :disabled="deciding" @click="decide('suspect')">برگرداندن به بررسی</button>
        </div>
        <p v-if="listError" class="text-sm text-red-600">{{ listError }}</p>

        <div v-if="loadingList && !list" class="space-y-2">
          <Skeleton v-for="i in 5" :key="i" class="h-10 rounded-xl" />
        </div>
        <EmptyState
          v-else-if="!rows.length"
          :title="state === 'suspect' ? 'فاکتوری در انتظار بررسی نیست' : 'موردی نیست'"
        />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-xs min-w-[760px]">
            <thead>
              <tr class="text-slate-400 border-b border-slate-100">
                <th class="py-2 w-8"><input type="checkbox" :checked="allChecked" @change="toggleAll" /></th>
                <th class="text-right font-medium py-2">برگه</th>
                <th class="text-right font-medium py-2">تاریخ</th>
                <th class="text-right font-medium py-2">دفتر</th>
                <th class="text-right font-medium py-2">مشتری</th>
                <th class="text-right font-medium py-2">بازاریاب</th>
                <th class="text-right font-medium py-2">ایجادکننده</th>
                <th class="text-left font-medium py-2">مبلغ فروش</th>
                <th v-if="state !== 'suspect'" class="text-right font-medium py-2 pr-3">{{ state === 'real' ? 'گروه' : 'تأییدکننده' }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in rows" :key="r.id"
                class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                :class="selected.has(r.id) ? 'bg-sky-50/60' : ''"
                @click="toggle(r.id)"
              >
                <td class="py-2 text-center"><input type="checkbox" :checked="selected.has(r.id)" @click.stop="toggle(r.id)" /></td>
                <td class="py-2 text-ink">{{ r.number }}<span v-if="r.kind === 'return'" class="text-red-500 mr-1">مرجوعی</span></td>
                <td class="py-2 text-slate-500 whitespace-nowrap">{{ r.issued_jalali }}</td>
                <td class="py-2 text-slate-500">{{ r.book_display }}</td>
                <td class="py-2 text-ink max-w-[220px] truncate">{{ r.customer }}</td>
                <td class="py-2 text-slate-500">{{ r.owner || "—" }}</td>
                <td class="py-2 text-slate-500">{{ r.created_by || "—" }}</td>
                <td class="py-2 text-left text-ink whitespace-nowrap font-medium">{{ rial(r.amount) }}</td>
                <td v-if="state !== 'suspect'" class="py-2 pr-3 text-slate-500">
                  {{ state === "real" ? channelLabel(r.channel) : r.reviewed_by || "—" }}
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="rows.length >= 500" class="text-[11px] text-slate-400 mt-2">۵۰۰ مورد اول نشان داده شده؛ با جستجو محدود کنید.</p>
        </div>
      </div>
    </template>

    <!-- ================= History ================= -->
    <template v-else>
      <div :class="card">
        <div v-if="loadingHistory" class="space-y-2">
          <Skeleton v-for="i in 4" :key="i" class="h-10 rounded-xl" />
        </div>
        <EmptyState v-else-if="!history.length" title="هنوز فایلی وارد نشده" />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-xs min-w-[760px]">
            <thead>
              <tr class="text-slate-400 border-b border-slate-100">
                <th class="text-right font-medium py-2">زمان</th>
                <th class="text-right font-medium py-2">فایل</th>
                <th class="text-right font-medium py-2">دفتر</th>
                <th class="text-right font-medium py-2">بازه</th>
                <th class="text-left font-medium py-2">فاکتور</th>
                <th class="text-left font-medium py-2">جدید</th>
                <th class="text-left font-medium py-2">به‌روز</th>
                <th class="text-left font-medium py-2">تکراری</th>
                <th class="text-left font-medium py-2">سوری</th>
                <th class="text-left font-medium py-2">مبلغ</th>
                <th class="text-right font-medium py-2 pr-3">توسط</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="h in history" :key="h.id" class="border-t border-slate-100">
                <td class="py-2 text-slate-500 whitespace-nowrap">{{ jdatetime(h.at) }}</td>
                <td class="py-2 text-ink max-w-[180px] truncate" dir="auto">{{ h.file_name }}</td>
                <td class="py-2 text-slate-500">{{ h.book_display }}</td>
                <td class="py-2 text-slate-500 whitespace-nowrap">{{ h.date_from }} تا {{ h.date_to }}</td>
                <td class="py-2 text-left">{{ num(h.rows) }}</td>
                <td class="py-2 text-left" :class="h.created ? 'text-emerald-600' : 'text-slate-400'">{{ num(h.created) }}</td>
                <td class="py-2 text-left" :class="h.updated ? 'text-sky-600' : 'text-slate-400'">{{ num(h.updated) }}</td>
                <td class="py-2 text-left text-slate-400">{{ num(h.unchanged) }}</td>
                <td class="py-2 text-left" :class="h.suspect ? 'text-amber-600' : 'text-slate-400'">{{ num(h.suspect) }}</td>
                <td class="py-2 text-left text-ink whitespace-nowrap">{{ rial(h.amount) }}</td>
                <td class="py-2 pr-3 text-slate-500">{{ h.by || "—" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
