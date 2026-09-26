<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { sales2Api, type CustomerRow } from "@/api/sales2";
import ExcelImport from "@/components/ExcelImport.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * مشتریان و اعتبار. The customer file is CRM's; this page shows it from the
 * sales side — what each one owes and how much more they may buy. With no
 * search it lists the customers already trading here.
 */
const router = useRouter();
const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));

const rows = ref<CustomerRow[]>([]);
const loading = ref(true);
const q = ref("");

async function load() {
  loading.value = true;
  try {
    rows.value = await sales2Api.customers({ q: q.value.trim() });
  } finally {
    loading.value = false;
  }
}
let timer: ReturnType<typeof setTimeout> | undefined;
watch(q, () => { clearTimeout(timer); timer = setTimeout(load, 300); });
onMounted(load);
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <input
        v-model="q" placeholder="جستجو در همه‌ی مشتریان CRM: نام، کد، شناسه ملی یا تلفن…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none flex-1 min-w-[220px]"
      />
      <ExcelImport import-key="sales2-credit" label="اکسل اعتبار مشتریان" @done="load" />
      <span class="text-xs text-slate-400 px-2">{{ q ? "نتیجه‌ی جستجو (حداکثر ۶۰)" : "مشتریانی که در فروش ۲ سند یا دریافت دارند" }}</span>
    </div>

    <div v-if="loading" class="space-y-2"><Skeleton v-for="i in 6" :key="i" class="h-12 rounded-xl" /></div>
    <EmptyState
      v-else-if="!rows.length"
      title="مشتری‌ای نیست"
      :hint="q ? 'با نام دیگری جستجو کنید.' : 'هنوز برای هیچ مشتری سندی صادر نشده؛ بالا جستجو کنید.'"
    />
    <div v-else class="bg-surface rounded-card shadow-soft overflow-x-auto">
      <table class="w-full text-sm min-w-[820px]">
        <thead>
          <tr class="text-xs text-slate-400 bg-slate-50">
            <th class="text-right font-medium px-4 py-3">مشتری</th>
            <th class="text-right font-medium px-3">کارشناس</th>
            <th class="text-right font-medium px-3">مانده بدهی</th>
            <th class="text-right font-medium px-3">چک در جریان</th>
            <th class="text-right font-medium px-3">سقف اعتبار</th>
            <th class="text-right font-medium px-3">اعتبار باقی</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="c in rows" :key="c.id"
            class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
            @click="router.push({ name: 'sales2-customer', params: { id: c.id } })"
          >
            <td class="px-4 py-2.5">
              <p class="text-ink font-medium">
                {{ c.name_fa }}
                <span v-if="c.balance?.on_hold" class="text-xs rounded-full px-2 bg-red-100 text-red-600">توقف فروش</span>
              </p>
              <p class="text-xs text-slate-400 ltr-nums">{{ [c.national_id, c.phone, c.city].filter(Boolean).join(" · ") }}</p>
            </td>
            <td class="px-3 text-slate-500">{{ c.owner_name || "—" }}</td>
            <td class="px-3 ltr-nums font-medium" :class="Number(c.balance?.balance_rial) > 0 ? 'text-ink' : 'text-slate-400'">{{ fa(c.balance?.balance_rial) }}</td>
            <td class="px-3 ltr-nums text-slate-500">{{ fa(c.balance?.cheques_pending_rial) }}</td>
            <td class="px-3 ltr-nums text-slate-500">{{ c.balance?.credit_limit_rial == null ? "—" : fa(c.balance.credit_limit_rial) }}</td>
            <td class="px-3 ltr-nums" :class="Number(c.balance?.available_rial) < 0 ? 'text-red-600' : 'text-emerald-600'">
              {{ c.balance?.available_rial == null ? "—" : fa(c.balance.available_rial) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
