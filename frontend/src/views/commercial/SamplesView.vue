<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { commercialApi, type Sample } from "@/api/commercial";
import { useAuthStore } from "@/stores/auth";
import { confirm } from "@/composables/useUi";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import PickerField from "@/components/PickerField.vue";
import SampleForm from "@/components/commercial/SampleForm.vue";
import SampleVerdictDialog from "@/components/commercial/SampleVerdictDialog.vue";
import StatTile from "@/components/commercial/StatTile.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * نمونه‌ها — what suppliers sent, and what was decided about it.
 *
 * The list is ordered by how long each sample has been waiting, not by date:
 * the question this page answers is «کدام نمونه معطل مانده؟», and a sample
 * sitting in the lab for three weeks is holding a purchase up whether it
 * arrived recently or not.
 */
const router = useRouter();
const auth = useAuthStore();

const rows = ref<Sample[]>([]);
const loading = ref(true);
const error = ref("");
const search = ref("");
const status = ref<string | null>(null);

const canEdit = computed(
  () => auth.department === "commercial" || !!auth.me?.is_superuser,
);

const STATUSES = [
  { value: "requested", label: "درخواست شد" },
  { value: "received", label: "دریافت شد" },
  { value: "testing", label: "در حال آزمایش" },
  { value: "approved", label: "تایید شد" },
  { value: "rejected", label: "رد شد" },
];

const CHIP: Record<string, string> = {
  requested: "bg-slate-100 text-slate-500",
  received: "bg-sky-50 text-sky-600",
  testing: "bg-amber-50 text-amber-700",
  approved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-red-50 text-red-500",
};

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const params: Record<string, unknown> = {};
    if (status.value) params.status = status.value;
    if (search.value.trim()) params.search = search.value.trim();
    rows.value = await commercialApi.samples(params);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

/** Undecided first, longest wait at the top — the work queue, in order. */
const ordered = computed(() => [...rows.value].sort((a, b) => {
  const aOpen = a.waiting_days !== null;
  const bOpen = b.waiting_days !== null;
  if (aOpen !== bOpen) return aOpen ? -1 : 1;
  if (aOpen && bOpen) return (b.waiting_days ?? 0) - (a.waiting_days ?? 0);
  return (b.decided_on ?? "").localeCompare(a.decided_on ?? "");
}));

const totals = computed(() => {
  const open = rows.value.filter((r) => r.waiting_days !== null);
  const decided = rows.value.filter((r) => r.waiting_days === null);
  const approved = decided.filter((r) => r.is_approved);
  const turnarounds = decided
    .map((r) => r.turnaround_days)
    .filter((d): d is number => d !== null);
  return {
    open: open.length,
    stale: open.filter((r) => (r.waiting_days ?? 0) > 14).length,
    approvedPct: decided.length
      ? Math.round((approved.length / decided.length) * 100)
      : null,
    decided: decided.length,
    avgTurnaround: turnarounds.length
      ? Math.round(turnarounds.reduce((a, b) => a + b, 0) / turnarounds.length)
      : null,
  };
});

const editing = ref<Sample | null>(null);
const showForm = ref(false);
const deciding = ref<Sample | null>(null);

function openForm(sample: Sample | null) {
  editing.value = sample;
  showForm.value = true;
}

function afterChange() {
  showForm.value = false;
  editing.value = null;
  deciding.value = null;
  load();
}

async function remove(sample: Sample) {
  const ok = await confirm({
    title: "حذف نمونه",
    message: `نمونه ${sample.sample_no} حذف شود؟`,
    danger: true,
  });
  if (!ok) return;
  try {
    await commercialApi.removeSample(sample.id);
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}

const FA = new Intl.NumberFormat("fa-IR");
const inp =
  "bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
</script>

<template>
  <div class="space-y-4">
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <StatTile
        label="در انتظار نتیجه"
        :value="num(totals.open)"
        :hint="totals.stale ? `${num(totals.stale)} مورد بیش از ۱۴ روز` : 'همه تازه‌اند'"
      />
      <StatTile
        label="نرخ تایید"
        :value="totals.approvedPct === null ? '—' : `${FA.format(totals.approvedPct)}٪`"
        :hint="`از ${num(totals.decided)} نمونه بررسی‌شده`"
      />
      <StatTile
        label="میانگین زمان بررسی"
        :value="totals.avgTurnaround === null
          ? '—'
          : `${FA.format(totals.avgTurnaround)} روز`"
        hint="از دریافت تا تصمیم"
      />
      <StatTile
        label="کل نمونه‌ها"
        :value="num(rows.length)"
        hint="با فیلترهای فعلی"
      />
    </div>

    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <input
        v-model="search" :class="inp" class="flex-1 min-w-[12rem]"
        placeholder="جستجوی شماره، کالا یا تامین‌کننده…"
        @keyup.enter="load"
      />
      <PickerField
        v-model="status" :options="STATUSES" placeholder="همه وضعیت‌ها"
        class="min-w-[10rem]"
      />
      <button class="bg-slate-100 text-ink rounded-xl px-4 py-2 text-sm" @click="load">
        اعمال
      </button>
      <button
        v-if="canEdit"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm"
        @click="openForm(null)"
      >+ درخواست نمونه</button>
    </div>

    <p
      v-if="error"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line"
    >{{ error }}</p>

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 6" :key="i" class="h-12 rounded-xl" />
    </div>

    <EmptyState
      v-else-if="!ordered.length"
      title="نمونه‌ای ثبت نشده"
      hint="پیش از خرید از یک تامین‌کننده تازه، نمونه بخواهید و نتیجه‌اش را همین‌جا ثبت کنید."
    />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[940px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-3">شماره</th>
              <th class="text-right font-medium px-3">کالا</th>
              <th class="text-right font-medium px-3">تامین‌کننده</th>
              <th class="text-right font-medium px-3">مشخصات درخواستی</th>
              <th class="text-right font-medium px-3">تاریخ</th>
              <th class="text-right font-medium px-3">وضعیت</th>
              <th class="px-4"></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in ordered" :key="s.id"
              class="border-t border-slate-100 hover:bg-slate-50"
            >
              <td class="px-4 py-2.5">
                <p class="text-ink font-medium ltr-nums">{{ s.sample_no }}</p>
                <button
                  v-if="s.request"
                  class="text-xs text-slate-400 hover:text-ink ltr-nums"
                  @click="router.push({
                    name: 'commercial-request', params: { id: s.request },
                  })"
                >{{ s.request_no }}</button>
              </td>
              <td class="px-3 text-ink">
                {{ s.material_name }}
                <p v-if="Number(s.quantity)" class="text-xs text-slate-400 ltr-nums">
                  {{ num(s.quantity) }} {{ s.material_unit }}
                </p>
              </td>
              <td class="px-3 text-slate-600">{{ s.supplier_name }}</td>
              <td class="px-3 text-xs text-slate-500 max-w-[16rem]">
                <p class="truncate">{{ s.spec || "—" }}</p>
                <p v-if="s.lab_note" class="text-slate-400 truncate">{{ s.lab_note }}</p>
              </td>
              <td class="px-3 text-xs text-slate-500 ltr-nums whitespace-nowrap">
                {{ faDate(s.requested_on) }}
                <p v-if="s.received_on" class="text-slate-400">
                  دریافت {{ faDate(s.received_on) }}
                </p>
              </td>
              <td class="px-3 whitespace-nowrap">
                <span
                  class="text-xs rounded-full px-2 py-0.5"
                  :class="CHIP[s.status]"
                >{{ s.status_label }}</span>
                <p v-if="s.reason_name" class="text-xs text-red-500 mt-0.5">
                  {{ s.reason_name }}
                </p>
                <p
                  v-else-if="s.waiting_days !== null"
                  class="text-xs mt-0.5"
                  :class="s.waiting_days > 14 ? 'text-amber-600' : 'text-slate-400'"
                >{{ num(s.waiting_days) }} روز در انتظار</p>
                <p v-else-if="s.decided_by_name" class="text-xs text-slate-400 mt-0.5">
                  {{ s.decided_by_name }} · {{ faDate(s.decided_on) }}
                </p>
              </td>
              <td class="px-4 text-left whitespace-nowrap">
                <button
                  v-if="canEdit"
                  class="text-xs rounded-lg px-2 py-1 ml-1"
                  :class="s.waiting_days !== null
                    ? 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                    : 'text-slate-400 hover:text-ink'"
                  @click="deciding = s"
                >{{ s.waiting_days !== null ? "ثبت نتیجه" : "تغییر نتیجه" }}</button>
                <button
                  v-if="canEdit"
                  class="text-xs text-slate-400 hover:text-ink px-1.5"
                  @click="openForm(s)"
                >ویرایش</button>
                <button
                  v-if="canEdit"
                  class="text-xs text-slate-400 hover:text-red-500 px-1.5"
                  @click="remove(s)"
                >حذف</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <SampleForm
      v-if="showForm"
      :sample="editing"
      @close="showForm = false" @saved="afterChange"
    />
    <SampleVerdictDialog
      v-if="deciding"
      :sample="deciding"
      @close="deciding = null" @saved="afterChange"
    />
  </div>
</template>
