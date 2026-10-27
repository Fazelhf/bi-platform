<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { crmApi, type CrmCustomer } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num } from "@/utils/format";
import CrmFilterBar from "@/components/crm/CrmFilterBar.vue";
import CrmExportButton from "@/components/crm/CrmExportButton.vue";
import SortHeader from "@/components/crm/SortHeader.vue";
import { useSort } from "@/composables/useListPrefs";
import { toast } from "@/composables/useUi";
import CustomerForm from "@/components/crm/CustomerForm.vue";
import InlineCell from "@/components/crm/InlineCell.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/** مشتریان — the account list. Note it deliberately ignores the date window:
 *  a customer list filtered by "this month" would hide most of the book. */
const crm = useCrmStore();
const router = useRouter();

const rows = ref<CrmCustomer[]>([]);
const total = ref(0);
const loading = ref(true);
const search = ref("");
const status = ref("");
const page = ref(1);
/** Rows per page, remembered per browser. 100 by default: managing a book of
 *  thousands 30 rows at a time was most of the clicking on this page. */
const PAGE_SIZES = [30, 100, 200, 500];
function storedSize(): number {
  try {
    const n = Number(localStorage.getItem("crm.customers.pageSize"));
    return PAGE_SIZES.includes(n) ? n : 100;
  } catch {
    return 100;
  }
}
const pageSize = ref(storedSize());
watch(pageSize, (n) => {
  try { localStorage.setItem("crm.customers.pageSize", String(n)); } catch { /* private mode */ }
  page.value = 1;
  load();
});

const { ordering, sortBy, dir } = useSort("");

/** The question this list is asking — shared by the fetch and the export. */
const exportParams = computed(() => {
  const { owner, group, province, source } = crm.query;
  return {
    owner, group, province, source,
    search: search.value, status: status.value, ordering: ordering.value,
  };
});

async function load() {
  loading.value = true;
  try {
    const res = await crmApi.customers({
      ...exportParams.value,
      page: page.value, page_size: pageSize.value,
    });
    rows.value = res.results;
    total.value = res.count;
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await crm.loadOptions(); await load(); });
// Something was saved from the global «ثبت جدید» button over the top of this
// page; the list under it is now stale.
watch(() => crm.revision, load);

watch(() => [crm.filters.owner, crm.filters.group, crm.filters.province, crm.filters.source], () => { page.value = 1; load(); });
watch([status, page], load);
watch(ordering, () => { page.value = 1; load(); });

let t: number | undefined;
watch(search, () => { window.clearTimeout(t); t = window.setTimeout(() => { page.value = 1; load(); }, 350); });

const pages = computed(() => Math.max(Math.ceil(total.value / pageSize.value), 1));
/** The list rows with their FK ids, which the list serializer sends but the
 *  shared `CrmCustomer` type does not name. */
const editableRows = computed(() => rows.value as (CrmCustomer & Record<string, any>)[]);

// ---- editing in the table ------------------------------------------------
const STATUSES = [
  { id: "lead", name: "سرنخ" }, { id: "active", name: "مشتری فعال" },
  { id: "dormant", name: "راکد" }, { id: "lost", name: "از دست رفته" },
];
const opts = computed(() => ({
  groups: (crm.options?.groups ?? []).map((g) => ({ id: g.id, name: g.name_fa })),
  provinces: (crm.options?.provinces ?? []).map((p) => ({ id: p.id, name: p.name_fa })),
  sources: (crm.options?.sources ?? []).map((p) => ({ id: p.id, name: p.name_fa })),
  employees: (crm.options?.employees ?? []).map((e) => ({ id: e.id, name: e.name })),
}));
const nameOf = (list: { id: string | number; name: string }[], id: unknown) =>
  list.find((o) => o.id === id)?.name ?? "";

/**
 * Save one field and refresh the row from what the server stored. The row is
 * replaced in place, so the page, filter, sort and scroll position all stay
 * where the user left them; a row that no longer matches the filter stays
 * until the next load rather than vanishing under the cursor.
 */
async function saveField(c: CrmCustomer & Record<string, any>, field: string, value: unknown) {
  const saved: Record<string, any> = await crmApi.saveCustomer({ [field]: value }, c.id);
  const i = rows.value.findIndex((r) => r.id === c.id);
  if (i < 0) return;
  const row: Record<string, any> = { ...rows.value[i], ...saved };
  row.group_name = nameOf(opts.value.groups, row.group);
  row.province_name = nameOf(opts.value.provinces, row.province);
  row.source_name = nameOf(opts.value.sources, row.lead_source);
  row.owner_name = nameOf(opts.value.employees, row.owner) || row.owner_name;
  row.status_display = nameOf(STATUSES, row.status);
  rows.value[i] = row as CrmCustomer;
}

/** One value onto every ticked row, in one request. */
const bulkField = ref<"" | "group" | "province" | "status" | "lead_source">("");
const bulkValue = ref<string | number | "">("");
const BULK_FIELDS = [
  { key: "group", label: "گروه" }, { key: "province", label: "استان" },
  { key: "status", label: "وضعیت" }, { key: "lead_source", label: "منبع سرنخ" },
] as const;
const bulkOptions = computed(() => ({
  group: opts.value.groups, province: opts.value.provinces,
  status: STATUSES, lead_source: opts.value.sources, "": [],
}[bulkField.value]));
watch(bulkField, () => { bulkValue.value = ""; });

async function bulkUpdate() {
  if (!bulkField.value) return;
  acting.value = true;
  try {
    const res = await crmApi.bulkUpdateCustomers([...selected.value], {
      [bulkField.value]: bulkValue.value === "" ? null : bulkValue.value,
    });
    toast.success(`${num(res.updated)} مشتری به‌روز شد`);
    bulkField.value = "";
    selected.value = new Set();
    await load();
  } catch (e: any) {
    const d = e?.response?.data;
    toast.error(d?.detail ?? (d ? String(Object.values(d)[0]) : "انجام نشد."));
  } finally {
    acting.value = false;
  }
}

const showForm = ref(false);
function onSaved() {
  showForm.value = false;
  load();
}

/**
 * Selection, and the two things you can do with one.
 *
 * Managers only. Both actions are maintenance of the customer *file* rather
 * than work on a book of customers: one queues rows for a merge review that a
 * کارشناس cannot open, and the other deletes. Neither belongs to the person
 * whose job is to sell to the rows.
 *
 * The list holds 3,760 accounts now, most of them arrived from accounting and
 * a good share of them duplicates or dormant. Cleaning that up one row at a
 * time is not work anybody finishes, so the list needs to act on a handful at
 * once — but the two actions are deliberately not equals. Deleting is refused
 * for anything carrying deals or invoices, and «send to review» is the answer
 * for those: a duplicate account should be *merged*, which keeps its orders,
 * not deleted, which loses them.
 */
const canCurate = computed(() => crm.canEdit && crm.isManager);
/** Bulk field edits are scoped server-side, so an expert may use them on their own rows. */
const canSelect = computed(() => crm.canEdit);

const assignTo = ref<number | "">("");

/** Hand the ticked accounts to another کارشناس — the manager's most common
 *  clean-up after someone leaves or a territory is redrawn. */
async function assignSelected() {
  if (!assignTo.value) return;
  acting.value = true;
  try {
    const res = await crmApi.bulkAssign("customers", [...selected.value], Number(assignTo.value));
    toast.success(`${num(res.updated)} مشتری به ${res.owner_name} سپرده شد`);
    assignTo.value = "";
    selected.value = new Set();
    await load();
  } catch (e: any) {
    toast.error(e?.response?.data?.detail ?? "تغییر کارشناس انجام نشد.");
  } finally {
    acting.value = false;
  }
}

const selected = ref<Set<number>>(new Set());
const acting = ref(false);
const result = ref<{ ok: string; warn: { name_fa: string; reason: string }[] } | null>(null);

function toggle(id: number) {
  const next = new Set(selected.value);
  next.has(id) ? next.delete(id) : next.add(id);
  selected.value = next;
}

const allOnPage = computed(
  () => rows.value.length > 0 && rows.value.every((r) => selected.value.has(r.id)),
);

function toggleAll() {
  const next = new Set(selected.value);
  const ids = rows.value.map((r) => r.id);
  allOnPage.value ? ids.forEach((i) => next.delete(i)) : ids.forEach((i) => next.add(i));
  selected.value = next;
}

/** Selecting across pages then acting on rows you can no longer see is a good
 *  way to delete something by accident. The selection clears with the page. */
watch([page, status, search], () => {
  selected.value = new Set();
  result.value = null;
});

async function sendToReview() {
  acting.value = true;
  result.value = null;
  try {
    const res = await crmApi.bulkReview([...selected.value]);
    result.value = {
      ok: res.queued
        ? `${num(res.queued)} مورد به صف بازبینی رفت.`
        : "چیزی به صف اضافه نشد.",
      warn: res.skipped,
    };
    selected.value = new Set();
  } catch (e: any) {
    result.value = { ok: "", warn: [{ name_fa: "", reason: e?.response?.data?.detail ?? "انجام نشد." }] };
  } finally {
    acting.value = false;
  }
}

async function removeSelected() {
  const n = selected.value.size;
  if (!window.confirm(`${num(n)} مشتری حذف شود؟ مشتریانی که معامله یا فاکتور دارند حذف نمی‌شوند.`)) return;
  acting.value = true;
  result.value = null;
  try {
    const res = await crmApi.bulkDelete([...selected.value]);
    result.value = {
      ok: `${num(res.deleted)} مشتری حذف شد.`,
      warn: res.blocked,
    };
    selected.value = new Set();
    await load();
  } catch (e: any) {
    result.value = { ok: "", warn: [{ name_fa: "", reason: e?.response?.data?.detail ?? "حذف انجام نشد." }] };
  } finally {
    acting.value = false;
  }
}

/** «آخرین تماس» as an age, coloured once it is long enough to matter. */
function daysAgo(iso: string | null | undefined): number | null {
  return iso ? Math.floor((Date.now() - new Date(iso).getTime()) / 86400000) : null;
}
function sinceText(iso: string | null | undefined): string {
  const d = daysAgo(iso);
  if (d === null) return "هرگز";
  if (d < 1) return "امروز";
  return `${num(d)} روز پیش`;
}
function quietClass(iso: string | null | undefined): string {
  const d = daysAgo(iso);
  if (d === null || d >= 90) return "text-red-500";
  if (d >= 30) return "text-amber-600";
  return "text-slate-400";
}

const statusClass: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-700",
  lead: "bg-sky-100 text-sky-700",
  dormant: "bg-amber-100 text-amber-700",
  lost: "bg-red-100 text-red-600",
};
</script>

<template>
  <div class="space-y-4">
    <CrmFilterBar />

    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <input
        v-model="search" placeholder="جستجوی نام، تلفن یا کد مشتری…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 flex-1 min-w-[200px]"
      />
      <select v-model="status" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
        <option value="">همه وضعیت‌ها</option>
        <option value="active">مشتری فعال</option>
        <option value="lead">سرنخ</option>
        <option value="dormant">راکد</option>
        <option value="lost">از دست رفته</option>
      </select>
      <span class="text-xs text-slate-400 px-2">{{ num(total) }} مشتری</span>
      <select v-model.number="pageSize" class="bg-slate-100 rounded-xl px-2 py-2 text-xs text-ink outline-none" aria-label="تعداد در هر صفحه">
        <option v-for="n in PAGE_SIZES" :key="n" :value="n">{{ num(n) }} در صفحه</option>
      </select>
      <CrmExportButton kind="customers" :params="exportParams" :total="total" title="مشتریان" />
      <button
        v-if="crm.canEdit"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm shrink-0"
        @click="showForm = true"
      >+ مشتری جدید</button>
    </div>

    <!-- Appears only once something is selected: an action bar that is always
         there invites a click, and one of these two deletes. -->
    <div
      v-if="canSelect && selected.size"
      class="bg-panel text-white rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2"
    >
      <span class="text-sm px-1">{{ num(selected.size) }} انتخاب شده</span>
      <select v-model="bulkField" class="bg-white/10 rounded-xl px-3 py-2 text-sm outline-none" aria-label="ویرایش گروهی">
        <option value="" class="text-ink">ویرایش گروهی…</option>
        <option v-for="f in BULK_FIELDS" :key="f.key" :value="f.key" class="text-ink">{{ f.label }}</option>
      </select>
      <template v-if="bulkField">
        <select v-model="bulkValue" class="bg-white/10 rounded-xl px-3 py-2 text-sm outline-none" aria-label="مقدار تازه">
          <option value="" class="text-ink">— خالی —</option>
          <option v-for="o in bulkOptions" :key="o.id" :value="o.id" class="text-ink">{{ o.name }}</option>
        </select>
        <button class="bg-white text-ink rounded-xl px-4 py-2 text-sm disabled:opacity-50" :disabled="acting" @click="bulkUpdate">
          اعمال روی {{ num(selected.size) }} مشتری
        </button>
      </template>
      <button
        v-if="canCurate"
        class="bg-white/15 rounded-xl px-4 py-2 text-sm disabled:opacity-50"
        :disabled="acting"
        @click="sendToReview"
      >ارسال به بازبینی</button>
      <select v-if="canCurate" v-model="assignTo" class="bg-white/10 rounded-xl px-3 py-2 text-sm outline-none">
        <option value="" class="text-ink">سپردن به کارشناس…</option>
        <option v-for="e in crm.options?.employees ?? []" :key="e.id" :value="e.id" class="text-ink">{{ e.name }}</option>
      </select>
      <button
        v-if="assignTo"
        class="bg-white text-ink rounded-xl px-4 py-2 text-sm disabled:opacity-50"
        :disabled="acting"
        @click="assignSelected"
      >ثبت کارشناس</button>
      <CrmExportButton
        kind="customers" :params="{ ...exportParams, ids: [...selected].join(',') }"
        :total="selected.size" title="مشتریان انتخاب‌شده" subtle
      />
      <button
        v-if="canCurate"
        class="bg-red-500/90 rounded-xl px-4 py-2 text-sm disabled:opacity-50"
        :disabled="acting"
        @click="removeSelected"
      >حذف</button>
      <button class="text-sm px-3 py-2 text-white/70" @click="selected = new Set()">
        لغو انتخاب
      </button>
      <span v-if="canCurate" class="text-xs text-white/60 basis-full sm:basis-auto sm:mr-auto">
        دو مشتری = همان جفت؛ یک یا چند تا = دنبال مشابهشان می‌گردد
      </span>
    </div>

    <div v-if="result" class="bg-surface rounded-card shadow-soft p-3 text-sm">
      <p v-if="result.ok" class="text-emerald-600">{{ result.ok }}</p>
      <ul v-if="result.warn.length" class="mt-1 space-y-0.5 text-xs text-slate-500">
        <li v-for="(w, i) in result.warn" :key="i">
          <span v-if="w.name_fa" class="text-ink">{{ w.name_fa }}</span>
          — {{ w.reason }}
        </li>
      </ul>
    </div>

    <CustomerForm v-if="showForm" @close="showForm = false" @saved="onSaved" />

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 10" :key="i" class="h-12 rounded-xl" />
    </div>

    <EmptyState v-else-if="!rows.length" title="مشتری‌ای یافت نشد" />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <!-- A card per customer on phones; see DealsView for why a seven-column
           table cannot simply be narrowed. -->
      <ul class="md:hidden divide-y divide-slate-100">
        <li
          v-for="c in rows" :key="`m-${c.id}`"
          class="p-4 active:bg-slate-50 cursor-pointer"
          @click="router.push({ name: 'crm-customer', params: { id: c.id } })"
        >
          <div class="flex items-start justify-between gap-3">
            <input
              v-if="canSelect" type="checkbox" class="mt-1 shrink-0"
              :checked="selected.has(c.id)"
              @click.stop @change="toggle(c.id)"
            />
            <div class="min-w-0 flex-1">
              <p class="text-ink font-medium truncate">{{ c.name_fa }}</p>
              <p class="text-xs text-slate-400 truncate">{{ c.contact_name }} · {{ c.mobile }}</p>
            </div>
            <span class="text-[11px] rounded-full px-2 py-0.5 shrink-0" :class="statusClass[c.status]">
              {{ c.status_display }}
            </span>
          </div>
          <div class="mt-2 text-xs text-slate-500 truncate">
            {{ [c.group_name, c.province_name].filter(Boolean).join(" · ") }}
          </div>
          <div class="flex items-center justify-between gap-2 mt-1 text-xs text-slate-400">
            <span class="truncate"><template v-if="crm.seesAll">{{ c.owner_name }}</template><template v-if="c.source_name"><template v-if="crm.seesAll"> · </template>{{ c.source_name }}</template></span>
            <span class="shrink-0 ltr-nums">{{ c.first_won_jalali || "—" }}</span>
          </div>
        </li>
      </ul>

      <div class="hidden md:block overflow-x-auto">
        <table class="w-full text-sm min-w-[1100px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th v-if="canSelect" class="w-10 px-3">
                <input type="checkbox" :checked="allOnPage" aria-label="انتخاب همه‌ی این صفحه" @change="toggleAll" />
              </th>
              <SortHeader label="مشتری" :dir="dir('name')" @sort="sortBy('name')" />
              <th class="text-right font-medium px-3">رابط</th>
              <th class="text-right font-medium px-3">موبایل</th>
              <SortHeader label="گروه" :dir="dir('group')" @sort="sortBy('group')" />
              <SortHeader label="استان" :dir="dir('province')" @sort="sortBy('province')" />
              <th class="text-right font-medium px-3">شهر</th>
              <SortHeader v-if="crm.seesAll" label="کارشناس" :dir="dir('owner')" @sort="sortBy('owner')" />
              <th class="text-right font-medium px-3">منبع سرنخ</th>
              <SortHeader label="وضعیت" :dir="dir('status')" @sort="sortBy('status')" />
              <SortHeader label="آخرین تماس" :dir="dir('last_activity')" @sort="sortBy('last_activity')" />
              <SortHeader label="اولین خرید" :dir="dir('first_won')" @sort="sortBy('first_won')" />
            </tr>
          </thead>
          <tbody>
            <!-- Cells edit in place (InlineCell); «پرونده» opens the customer page. -->
            <tr
              v-for="c in editableRows" :key="c.id"
              class="border-t border-slate-100 hover:bg-slate-50 align-top"
            >
              <td v-if="canSelect" class="px-3 py-2.5">
                <input
                  type="checkbox" :checked="selected.has(c.id)" :aria-label="'انتخاب ' + c.name_fa"
                  @change="toggle(c.id)"
                />
              </td>
              <td class="px-4 py-2 min-w-[12rem]">
                <InlineCell :value="c.name_fa" :disabled="!crm.canEdit" :save="(v) => saveField(c, 'name_fa', v)">
                  <span class="text-ink font-medium">{{ c.name_fa }}</span>
                </InlineCell>
                <router-link :to="{ name: 'crm-customer', params: { id: c.id } }" class="text-[11px] text-sky-600 hover:underline">
                  پرونده ›
                </router-link>
              </td>
              <td class="px-3 py-2 text-slate-500">
                <InlineCell :value="c.contact_name" :disabled="!crm.canEdit" :save="(v) => saveField(c, 'contact_name', v)" />
              </td>
              <td class="px-3 py-2 text-slate-500 ltr-nums">
                <InlineCell :value="c.mobile" :disabled="!crm.canEdit" :save="(v) => saveField(c, 'mobile', v)" />
              </td>
              <td class="px-3 py-2 text-slate-500">
                <InlineCell :value="c.group" :display="c.group_name || '—'" :options="opts.groups"
                            :disabled="!crm.canEdit" :save="(v) => saveField(c, 'group', v)" />
              </td>
              <td class="px-3 py-2 text-slate-500">
                <InlineCell :value="c.province" :display="c.province_name || '—'" :options="opts.provinces"
                            :disabled="!crm.canEdit" :save="(v) => saveField(c, 'province', v)" />
              </td>
              <td class="px-3 py-2 text-slate-500">
                <InlineCell :value="c.city" :disabled="!crm.canEdit" :save="(v) => saveField(c, 'city', v)" />
              </td>
              <!-- Every row would carry the reader's own name. -->
              <td v-if="crm.seesAll" class="px-3 py-2 text-slate-500">
                <InlineCell :value="c.owner" :display="c.owner_name || '—'" :options="opts.employees"
                            :disabled="!crm.canEdit || !crm.isManager" :save="(v) => saveField(c, 'owner', v)" />
              </td>
              <td class="px-3 py-2 text-slate-500">
                <InlineCell :value="c.lead_source" :display="c.source_name || '—'" :options="opts.sources"
                            :disabled="!crm.canEdit" :save="(v) => saveField(c, 'lead_source', v)" />
              </td>
              <td class="px-3 py-2">
                <InlineCell :value="c.status" :options="STATUSES" :disabled="!crm.canEdit" :save="(v) => saveField(c, 'status', v)">
                  <span class="text-[11px] rounded-full px-2 py-0.5" :class="statusClass[c.status]">
                    {{ c.status_display }}
                  </span>
                </InlineCell>
              </td>
              <td class="px-3 py-2.5 text-xs whitespace-nowrap" :class="quietClass(c.last_activity_at)">{{ sinceText(c.last_activity_at) }}</td>
              <td class="px-4 py-2.5 text-xs text-slate-400 whitespace-nowrap">{{ c.first_won_jalali || "—" }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="pages > 1" class="px-4 py-3 border-t border-slate-100 flex items-center justify-between">
        <button class="text-sm px-3 py-1.5 rounded-lg bg-slate-100 text-slate-600 disabled:opacity-40" :disabled="page <= 1" @click="page--">قبلی</button>
        <span class="text-xs text-slate-400">صفحه {{ num(page) }} از {{ num(pages) }} · {{ num(total) }} مشتری</span>
        <button class="text-sm px-3 py-1.5 rounded-lg bg-slate-100 text-slate-600 disabled:opacity-40" :disabled="page >= pages" @click="page++">بعدی</button>
      </div>
    </div>
  </div>
</template>
