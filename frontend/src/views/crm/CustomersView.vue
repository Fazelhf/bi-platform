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
const PAGE_SIZE = 30;

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
      page: page.value, page_size: PAGE_SIZE,
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

const pages = computed(() => Math.max(Math.ceil(total.value / PAGE_SIZE), 1));

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
      v-if="canCurate && selected.size"
      class="bg-panel text-white rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2"
    >
      <span class="text-sm px-1">{{ num(selected.size) }} انتخاب شده</span>
      <button
        class="bg-white/15 rounded-xl px-4 py-2 text-sm disabled:opacity-50"
        :disabled="acting"
        @click="sendToReview"
      >ارسال به بازبینی</button>
      <select v-model="assignTo" class="bg-white/10 rounded-xl px-3 py-2 text-sm outline-none">
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
        class="bg-red-500/90 rounded-xl px-4 py-2 text-sm disabled:opacity-50"
        :disabled="acting"
        @click="removeSelected"
      >حذف</button>
      <button class="text-sm px-3 py-2 text-white/70" @click="selected = new Set()">
        لغو انتخاب
      </button>
      <span class="text-xs text-white/60 basis-full sm:basis-auto sm:mr-auto">
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
              v-if="canCurate" type="checkbox" class="mt-1 shrink-0"
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
        <table class="w-full text-sm min-w-[760px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th v-if="canCurate" class="w-10 px-3">
                <input type="checkbox" :checked="allOnPage" @change="toggleAll" />
              </th>
              <SortHeader label="مشتری" :dir="dir('name')" @sort="sortBy('name')" />
              <SortHeader label="گروه" :dir="dir('group')" @sort="sortBy('group')" />
              <SortHeader label="استان" :dir="dir('province')" @sort="sortBy('province')" />
              <SortHeader v-if="crm.seesAll" label="کارشناس" :dir="dir('owner')" @sort="sortBy('owner')" />
              <th class="text-right font-medium px-3">منبع سرنخ</th>
              <SortHeader label="وضعیت" :dir="dir('status')" @sort="sortBy('status')" />
              <SortHeader label="آخرین تماس" :dir="dir('last_activity')" @sort="sortBy('last_activity')" />
              <SortHeader label="اولین خرید" :dir="dir('first_won')" @sort="sortBy('first_won')" />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="c in rows" :key="c.id"
              class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
              @click="router.push({ name: 'crm-customer', params: { id: c.id } })"
            >
              <td v-if="canCurate" class="px-3" @click.stop>
                <input
                  type="checkbox" :checked="selected.has(c.id)"
                  @change="toggle(c.id)"
                />
              </td>
              <td class="px-4 py-2.5">
                <p class="text-ink font-medium">{{ c.name_fa }}</p>
                <p class="text-xs text-slate-400">{{ c.contact_name }} · {{ c.mobile }}</p>
              </td>
              <td class="px-3 text-slate-500">{{ c.group_name }}</td>
              <td class="px-3 text-slate-500">{{ c.province_name }}</td>
              <!-- Every row would carry the reader's own name. -->
              <td v-if="crm.seesAll" class="px-3 text-slate-500">{{ c.owner_name }}</td>
              <td class="px-3 text-slate-500">{{ c.source_name }}</td>
              <td class="px-3">
                <span class="text-[11px] rounded-full px-2 py-0.5" :class="statusClass[c.status]">
                  {{ c.status_display }}
                </span>
              </td>
              <td class="px-3 text-xs whitespace-nowrap" :class="quietClass(c.last_activity_at)">{{ sinceText(c.last_activity_at) }}</td>
              <td class="px-4 text-xs text-slate-400 whitespace-nowrap">{{ c.first_won_jalali || "—" }}</td>
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
