<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { crmApi, type Deal } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num, pct, rial } from "@/utils/format";
import { useListPrefs, useSort } from "@/composables/useListPrefs";
import { useClickOutside } from "@/composables/useClickOutside";
import { toast } from "@/composables/useUi";
import CrmFilterBar from "@/components/crm/CrmFilterBar.vue";
import CrmExportButton from "@/components/crm/CrmExportButton.vue";
import SortHeader from "@/components/crm/SortHeader.vue";
import DealForm from "@/components/crm/DealForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * معاملات — the flat, filterable list with a reconciling totals strip.
 *
 * What makes it a working list rather than a read-only one: every column
 * sorts on the server (so «بزرگ‌ترین» means the biggest of all of them, not
 * of the 30 on screen), the columns shown are the reader's choice, and rows
 * can be ticked and acted on together — moved, reassigned, exported.
 */
const crm = useCrmStore();
const router = useRouter();

const rows = ref<Deal[]>([]);
const total = ref(0);
const summary = ref<any>(null);
const loading = ref(true);
const search = ref("");
const status = ref("won");
const page = ref(1);
const PAGE_SIZE = 30;

const { ordering, sortBy, dir } = useSort("");

const params = computed(() => ({
  ...crm.query,
  status: status.value,
  // Open deals are dated by when they were created; closed ones by when they
  // closed. Without this, "جاری" would filter on a date they do not have.
  date_basis: status.value === "open" ? "opened" : status.value === "" ? "opened" : "closed",
  search: search.value,
  ordering: ordering.value,
}));

async function load() {
  loading.value = true;
  try {
    const [res, sum] = await Promise.all([
      crmApi.deals({ ...params.value, page: page.value, page_size: PAGE_SIZE }),
      crmApi.dealSummary(params.value),
    ]);
    rows.value = res.results;
    total.value = res.count;
    summary.value = sum;
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await crm.loadOptions(); await load(); });
// Something was saved from the global «ثبت جدید» button over the top of this
// page; the list under it is now stale.
watch(() => crm.revision, load);

/** A new question: back to page one, and a selection made against the old
 *  list no longer means anything. */
function restart() { page.value = 1; selected.value = new Set(); load(); }
watch(() => crm.query, restart, { deep: true });
watch([status, ordering], restart);
watch(page, load);

let t: number | undefined;
watch(search, () => { window.clearTimeout(t); t = window.setTimeout(restart, 350); });

const pages = computed(() => Math.max(Math.ceil(total.value / PAGE_SIZE), 1));

const showForm = ref(false);
function onSaved(id: number) {
  showForm.value = false;
  if (id) router.push({ name: "crm-deal", params: { id } });
  else load();
}

const TABS = [
  { key: "won", label: "موفق" },
  { key: "open", label: "جاری" },
  { key: "lost", label: "ناموفق" },
  { key: "", label: "همه" },
];
const statusClass: Record<string, string> = {
  won: "bg-emerald-100 text-emerald-700",
  lost: "bg-red-100 text-red-600",
  open: "bg-amber-100 text-amber-700",
};

// ---- columns ---------------------------------------------------------------
const COLUMNS = [
  { key: "owner", label: "کارشناس" },
  { key: "stage", label: "مرحله" },
  { key: "status", label: "وضعیت" },
  { key: "amount", label: "مبلغ" },
  { key: "profit", label: "سود" },
  { key: "margin", label: "حاشیه" },
  { key: "province", label: "استان", default: false },
  { key: "source", label: "منبع سرنخ", default: false },
  { key: "expected", label: "موعد بسته‌شدن", default: false },
  { key: "date", label: "تاریخ" },
];
const prefs = useListPrefs("deals", COLUMNS);
/** «کارشناس» is not a question for a rep looking at their own book. */
const col = (k: string) => prefs.shown(k) && (k !== "owner" || crm.seesAll);

const pickerOpen = ref(false);
const picker = ref<HTMLElement | null>(null);
useClickOutside(picker, () => (pickerOpen.value = false));

/** The date column sorts on whichever date it is showing. */
const dateKey = computed(() => (status.value === "open" || status.value === "" ? "opened" : "closed"));

// ---- selection + bulk ------------------------------------------------------------
const selected = ref<Set<number>>(new Set());
const allOnPage = computed(() => rows.value.length > 0 && rows.value.every((r) => selected.value.has(r.id)));

function toggleRow(id: number) {
  const next = new Set(selected.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  selected.value = next;
}
function togglePage() {
  const next = new Set(selected.value);
  if (allOnPage.value) rows.value.forEach((r) => next.delete(r.id));
  else rows.value.forEach((r) => next.add(r.id));
  selected.value = next;
}

const exportParams = computed(() => ({ ...params.value, ids: [...selected.value].join(",") }));

const bulkBusy = ref(false);
const moveTo = ref<number | "">("");
const assignTo = ref<number | "">("");
const lostReason = ref<number | "">("");

const moveStage = computed(() => crm.options?.stages.find((s) => s.id === moveTo.value));

async function bulkMove() {
  if (!moveTo.value) return;
  if (moveStage.value?.kind === "lost" && !lostReason.value) {
    toast.error("برای ناموفق کردن معاملات، دلیل را انتخاب کنید.");
    return;
  }
  bulkBusy.value = true;
  try {
    const res = await crmApi.bulkMoveDeals([...selected.value], Number(moveTo.value), {
      lost_reason: lostReason.value || undefined,
    });
    toast.success(`${num(res.moved)} معامله به «${moveStage.value?.name_fa}» منتقل شد`);
    moveTo.value = "";
    lostReason.value = "";
    restart();
  } catch (e: any) {
    toast.error(e?.response?.data?.detail ?? e?.response?.data?.lost_reason ?? "انتقال انجام نشد.");
  } finally {
    bulkBusy.value = false;
  }
}

async function bulkAssign() {
  if (!assignTo.value) return;
  bulkBusy.value = true;
  try {
    const res = await crmApi.bulkAssign("deals", [...selected.value], Number(assignTo.value));
    toast.success(`${num(res.updated)} معامله به ${res.owner_name} سپرده شد`);
    assignTo.value = "";
    restart();
  } catch (e: any) {
    toast.error(e?.response?.data?.detail ?? "تغییر کارشناس انجام نشد.");
  } finally {
    bulkBusy.value = false;
  }
}

function open(d: Deal) { router.push({ name: "crm-deal", params: { id: d.id } }); }
</script>

<template>
  <div class="space-y-4">
    <CrmFilterBar />

    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <div class="flex rounded-xl bg-slate-100 p-0.5">
        <button
          v-for="t2 in TABS" :key="t2.key"
          class="text-xs px-3 py-1.5 rounded-lg transition"
          :class="status === t2.key ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-400'"
          @click="status = t2.key"
        >{{ t2.label }}</button>
      </div>
      <input
        v-model="search" placeholder="جستجوی معامله یا مشتری…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 flex-1 min-w-[180px]"
      />

      <!-- Column picker -->
      <div ref="picker" class="relative hidden md:block">
        <button
          class="flex items-center gap-1.5 text-xs rounded-xl px-3 py-2 bg-slate-100 text-slate-600 hover:bg-slate-200"
          @click="pickerOpen = !pickerOpen"
        >
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" d="M9 4v16M15 4v16M4 4h16v16H4z" /></svg>
          ستون‌ها
        </button>
        <div v-if="pickerOpen" class="absolute left-0 top-full mt-1 z-30 w-52 bg-surface rounded-xl shadow-pop border border-slate-100 p-2">
          <label
            v-for="c in COLUMNS.filter((c) => c.key !== 'owner' || crm.seesAll)" :key="c.key"
            class="flex items-center gap-2 text-sm text-ink px-2 py-1.5 rounded-lg hover:bg-slate-50 cursor-pointer"
          >
            <input type="checkbox" :checked="prefs.shown(c.key)" class="accent-slate-700" @change="prefs.toggle(c.key)" />
            {{ c.label }}
          </label>
          <button class="w-full text-[11px] text-slate-400 hover:text-ink mt-1 py-1" @click="prefs.reset()">بازگشت به پیش‌فرض</button>
        </div>
      </div>

      <CrmExportButton kind="deals" :params="params" :total="total" title="معاملات" />
      <button
        v-if="crm.canEdit"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm shrink-0"
        @click="showForm = true"
      >+ معامله جدید</button>
    </div>

    <DealForm v-if="showForm" @close="showForm = false" @saved="onSaved" />

    <!-- Totals -->
    <div v-if="summary" class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-400">تعداد</p><p class="text-lg font-bold text-ink mt-1">{{ num(summary.count) }}</p></div>
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-400">مبلغ</p><p class="text-lg font-bold text-ink mt-1">{{ rial(summary.amount) }}</p></div>
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-400">سود</p><p class="text-lg font-bold text-emerald-600 mt-1">{{ rial(summary.profit) }}</p></div>
      <div class="bg-surface rounded-card shadow-soft p-4"><p class="text-xs text-slate-400">حاشیه سود</p><p class="text-lg font-bold text-ink mt-1">{{ pct(summary.margin_pct) }}</p></div>
    </div>

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 10" :key="i" class="h-12 rounded-xl" />
    </div>

    <EmptyState v-else-if="!rows.length" title="معامله‌ای در این بازه نیست" />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <!-- Phones get a card per deal instead of the table.
           An eight-column table cannot be narrowed to 375px — it can only be
           scrolled sideways, which on a phone means reading one column at a
           time and never seeing a row whole. The card keeps the same fields
           in reading order: what it is, then the money, then who and when. -->
      <ul class="md:hidden divide-y divide-slate-100">
        <li
          v-for="d in rows" :key="`m-${d.id}`"
          class="p-4 active:bg-slate-50 cursor-pointer"
          @click="open(d)"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="text-ink font-medium truncate">{{ d.title }}</p>
              <p class="text-xs text-slate-400 truncate">{{ d.customer_name }} · {{ d.province_name }}</p>
            </div>
            <span class="text-[11px] rounded-full px-2 py-0.5 shrink-0" :class="statusClass[d.status]">
              {{ d.status_display }}
            </span>
          </div>

          <div class="flex items-baseline gap-3 mt-2 flex-wrap">
            <span class="text-ink font-semibold ltr-nums">{{ rial(d.amount_rial) }}</span>
            <span class="text-xs ltr-nums" :class="Number(d.profit_rial) >= 0 ? 'text-emerald-600' : 'text-red-500'">
              سود {{ rial(d.profit_rial) }}
            </span>
            <span class="text-xs ltr-nums" :class="d.margin_pct >= 20 ? 'text-emerald-600' : d.margin_pct >= 10 ? 'text-amber-600' : 'text-red-500'">
              {{ pct(d.margin_pct) }}
            </span>
          </div>

          <div class="flex items-center justify-between gap-2 mt-1.5 text-xs text-slate-400">
            <span class="truncate"><template v-if="crm.seesAll">{{ d.owner_name }} · </template>{{ d.stage_name }}</span>
            <span class="shrink-0 ltr-nums">{{ d.closed_jalali || d.opened_jalali }}</span>
          </div>
          <p v-if="d.reason_name" class="text-[10px] text-red-400 mt-1">{{ d.reason_name }}</p>
        </li>
      </ul>

      <div class="hidden md:block overflow-x-auto">
        <table class="w-full text-sm min-w-[820px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="w-10 pr-4">
                <input type="checkbox" class="accent-slate-700" :checked="allOnPage" title="انتخاب همه‌ی این صفحه" @change="togglePage" />
              </th>
              <SortHeader label="معامله" :dir="dir('title')" @sort="sortBy('title')" />
              <SortHeader v-if="col('owner')" label="کارشناس" :dir="dir('owner')" @sort="sortBy('owner')" />
              <SortHeader v-if="col('stage')" label="مرحله" :dir="dir('stage')" @sort="sortBy('stage')" />
              <SortHeader v-if="col('status')" label="وضعیت" :dir="dir('status')" @sort="sortBy('status')" />
              <th v-if="col('province')" class="text-right font-medium px-3">استان</th>
              <th v-if="col('source')" class="text-right font-medium px-3">منبع</th>
              <SortHeader v-if="col('amount')" label="مبلغ" align="left" :dir="dir('amount')" @sort="sortBy('amount')" />
              <SortHeader v-if="col('profit')" label="سود" align="left" :dir="dir('profit')" @sort="sortBy('profit')" />
              <th v-if="col('margin')" class="text-left font-medium px-3">حاشیه</th>
              <SortHeader v-if="col('expected')" label="موعد" :dir="dir('expected')" @sort="sortBy('expected')" />
              <SortHeader v-if="col('date')" label="تاریخ" :dir="dir(dateKey)" @sort="sortBy(dateKey)" />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="d in rows" :key="d.id"
              class="border-t border-slate-100 cursor-pointer transition-colors"
              :class="selected.has(d.id) ? 'bg-sky-50/60' : 'hover:bg-slate-50'"
              @click="open(d)"
            >
              <td class="pr-4" @click.stop>
                <input type="checkbox" class="accent-slate-700" :checked="selected.has(d.id)" @change="toggleRow(d.id)" />
              </td>
              <td class="px-3 py-2.5">
                <p class="text-ink font-medium truncate max-w-[280px]">{{ d.title }}</p>
                <p class="text-xs text-slate-400">{{ d.customer_name }}<template v-if="!col('province') && d.province_name"> · {{ d.province_name }}</template></p>
              </td>
              <td v-if="col('owner')" class="px-3 text-slate-500">{{ d.owner_name || "—" }}</td>
              <td v-if="col('stage')" class="px-3 text-slate-500 text-xs">{{ d.stage_name }}</td>
              <td v-if="col('status')" class="px-3">
                <span class="text-[11px] rounded-full px-2 py-0.5" :class="statusClass[d.status]">{{ d.status_display }}</span>
                <span v-if="d.reason_name" class="text-[10px] text-red-400 block mt-0.5">{{ d.reason_name }}</span>
              </td>
              <td v-if="col('province')" class="px-3 text-slate-500 text-xs">{{ d.province_name || "—" }}</td>
              <td v-if="col('source')" class="px-3 text-slate-500 text-xs">{{ d.source_name || "—" }}</td>
              <td v-if="col('amount')" class="px-3 text-left text-ink whitespace-nowrap ltr-nums">{{ rial(d.amount_rial) }}</td>
              <td v-if="col('profit')" class="px-3 text-left whitespace-nowrap ltr-nums" :class="Number(d.profit_rial) >= 0 ? 'text-emerald-600' : 'text-red-500'">{{ rial(d.profit_rial) }}</td>
              <td v-if="col('margin')" class="px-3 text-left ltr-nums" :class="d.margin_pct >= 20 ? 'text-emerald-600' : d.margin_pct >= 10 ? 'text-amber-600' : 'text-red-500'">{{ pct(d.margin_pct) }}</td>
              <td v-if="col('expected')" class="px-3 text-xs text-slate-400 whitespace-nowrap">{{ d.expected_close_date || "—" }}</td>
              <td v-if="col('date')" class="px-3 text-xs text-slate-400 whitespace-nowrap">{{ d.closed_jalali || d.opened_jalali }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="pages > 1" class="px-4 py-3 border-t border-slate-100 flex items-center justify-between">
        <button class="text-sm px-3 py-1.5 rounded-lg bg-slate-100 text-slate-600 disabled:opacity-40" :disabled="page <= 1" @click="page--">قبلی</button>
        <span class="text-xs text-slate-400">صفحه {{ num(page) }} از {{ num(pages) }} · {{ num(total) }} معامله</span>
        <button class="text-sm px-3 py-1.5 rounded-lg bg-slate-100 text-slate-600 disabled:opacity-40" :disabled="page >= pages" @click="page++">بعدی</button>
      </div>
    </div>

    <!-- Bulk bar: appears once something is ticked, stays out of the way otherwise. -->
    <Transition name="bulk">
      <div
        v-if="selected.size"
        class="fixed bottom-4 inset-x-4 md:inset-x-auto md:left-1/2 md:-translate-x-1/2 z-40 bg-panel text-white rounded-2xl shadow-pop px-4 py-3 flex flex-wrap items-center gap-2"
        dir="rtl"
      >
        <span class="text-sm font-semibold ml-1">{{ num(selected.size) }} انتخاب‌شده</span>

        <template v-if="crm.canEdit">
          <select v-model="moveTo" class="bg-white/10 rounded-lg px-2 py-1.5 text-xs outline-none">
            <option value="" class="text-ink">انتقال به مرحله…</option>
            <option v-for="s in crm.options?.stages ?? []" :key="s.id" :value="s.id" class="text-ink">{{ s.name_fa }}</option>
          </select>
          <select v-if="moveStage?.kind === 'lost'" v-model="lostReason" class="bg-white/10 rounded-lg px-2 py-1.5 text-xs outline-none">
            <option value="" class="text-ink">دلیل…</option>
            <option v-for="r in crm.options?.reasons ?? []" :key="r.id" :value="r.id" class="text-ink">{{ r.name_fa }}</option>
          </select>
          <button v-if="moveTo" class="text-xs rounded-lg px-3 py-1.5 bg-white text-ink disabled:opacity-50" :disabled="bulkBusy" @click="bulkMove">انتقال</button>
        </template>

        <template v-if="crm.isManager">
          <span class="w-px h-5 bg-white/20 mx-1"></span>
          <select v-model="assignTo" class="bg-white/10 rounded-lg px-2 py-1.5 text-xs outline-none">
            <option value="" class="text-ink">سپردن به کارشناس…</option>
            <option v-for="e in crm.options?.employees ?? []" :key="e.id" :value="e.id" class="text-ink">{{ e.name }}</option>
          </select>
          <button v-if="assignTo" class="text-xs rounded-lg px-3 py-1.5 bg-white text-ink disabled:opacity-50" :disabled="bulkBusy" @click="bulkAssign">ثبت</button>
        </template>

        <span class="w-px h-5 bg-white/20 mx-1"></span>
        <CrmExportButton kind="deals" :params="exportParams" :total="selected.size" title="معاملات انتخاب‌شده" subtle />
        <button class="text-xs text-white/60 hover:text-white px-2" @click="selected = new Set()">لغو انتخاب</button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.bulk-enter-active,
.bulk-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.bulk-enter-from,
.bulk-leave-to {
  opacity: 0;
  transform: translateY(10px);
}
</style>
