<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { crmApi, type CrmCustomer } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num } from "@/utils/format";
import CrmFilterBar from "@/components/crm/CrmFilterBar.vue";
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

async function load() {
  loading.value = true;
  try {
    const { owner, group, province, source } = crm.query;
    const res = await crmApi.customers({
      owner, group, province, source,
      search: search.value, status: status.value,
      page: page.value, page_size: PAGE_SIZE,
    });
    rows.value = res.results;
    total.value = res.count;
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await crm.loadOptions(); await load(); });
watch(() => [crm.filters.owner, crm.filters.group, crm.filters.province, crm.filters.source], () => { page.value = 1; load(); });
watch([status, page], load);

let t: number | undefined;
watch(search, () => { window.clearTimeout(t); t = window.setTimeout(() => { page.value = 1; load(); }, 350); });

const pages = computed(() => Math.max(Math.ceil(total.value / PAGE_SIZE), 1));

const showForm = ref(false);
function onSaved() {
  showForm.value = false;
  load();
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
      <button
        v-if="crm.canEdit"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm shrink-0"
        @click="showForm = true"
      >+ مشتری جدید</button>
    </div>

    <CustomerForm v-if="showForm" @close="showForm = false" @saved="onSaved" />

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 10" :key="i" class="h-12 rounded-xl" />
    </div>

    <EmptyState v-else-if="!rows.length" title="مشتری‌ای یافت نشد" />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[760px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-3">مشتری</th>
              <th class="text-right font-medium px-3">گروه</th>
              <th class="text-right font-medium px-3">استان</th>
              <th class="text-right font-medium px-3">کارشناس</th>
              <th class="text-right font-medium px-3">منبع سرنخ</th>
              <th class="text-right font-medium px-3">وضعیت</th>
              <th class="text-right font-medium px-4">اولین خرید</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="c in rows" :key="c.id"
              class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
              @click="router.push({ name: 'crm-customer', params: { id: c.id } })"
            >
              <td class="px-4 py-2.5">
                <p class="text-ink font-medium">{{ c.name_fa }}</p>
                <p class="text-xs text-slate-400">{{ c.contact_name }} · {{ c.mobile }}</p>
              </td>
              <td class="px-3 text-slate-500">{{ c.group_name }}</td>
              <td class="px-3 text-slate-500">{{ c.province_name }}</td>
              <td class="px-3 text-slate-500">{{ c.owner_name }}</td>
              <td class="px-3 text-slate-500">{{ c.source_name }}</td>
              <td class="px-3">
                <span class="text-[11px] rounded-full px-2 py-0.5" :class="statusClass[c.status]">
                  {{ c.status_display }}
                </span>
              </td>
              <td class="px-4 text-xs text-slate-400 whitespace-nowrap">{{ c.first_won_jalali || "—" }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="pages > 1" class="px-4 py-3 border-t border-slate-100 flex items-center justify-between">
        <button class="text-sm px-3 py-1.5 rounded-lg bg-slate-100 text-slate-600 disabled:opacity-40" :disabled="page <= 1" @click="page--">قبلی</button>
        <span class="text-xs text-slate-400">صفحه {{ num(page) }} از {{ num(pages) }}</span>
        <button class="text-sm px-3 py-1.5 rounded-lg bg-slate-100 text-slate-600 disabled:opacity-40" :disabled="page >= pages" @click="page++">بعدی</button>
      </div>
    </div>
  </div>
</template>
