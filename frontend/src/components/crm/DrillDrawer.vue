<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { crmApi, type CrmActivity, type CrmCustomer, type Deal } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num, pct, rial } from "@/utils/format";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * The drill-down panel: the records behind a number.
 *
 * It never builds a query of its own — it replays the `drill` payload the
 * report attached to the row, so what it lists is by construction exactly
 * what was counted. The header repeats the aggregate so the reconciliation
 * is visible rather than promised.
 */
const crm = useCrmStore();
const router = useRouter();

const loading = ref(false);
const rows = ref<any[]>([]);
const total = ref(0);
const summary = ref<Record<string, number> | null>(null);
const page = ref(1);
const PAGE_SIZE = 25;

const kind = computed(() => crm.drill?.drill.kind ?? "deals");
const open = computed(() => !!crm.drill);

async function load() {
  if (!crm.drill) return;
  loading.value = true;
  try {
    const d = crm.drill.drill;
    const res: any = await crmApi.drill(d, { page: page.value, page_size: PAGE_SIZE });
    rows.value = res.results ?? [];
    total.value = res.count ?? 0;
    // The totals strip: deals show money, activities show call quality.
    summary.value =
      d.kind === "activities"
        ? await crmApi.activitySummary(d.params)
        : d.kind === "deals"
        ? await crmApi.dealSummary(d.params)
        : null;
  } finally {
    loading.value = false;
  }
}

watch(() => crm.drill, (v) => { if (v) { page.value = 1; load(); } }, { immediate: true });
watch(page, load);

const pages = computed(() => Math.max(Math.ceil(total.value / PAGE_SIZE), 1));

function goDeal(d: Deal) { crm.closeDrill(); router.push({ name: "crm-deal", params: { id: d.id } }); }
function goCustomer(id: number) { crm.closeDrill(); router.push({ name: "crm-customer", params: { id } }); }

const statusClass: Record<string, string> = {
  won: "bg-emerald-100 text-emerald-700",
  lost: "bg-red-100 text-red-600",
  open: "bg-amber-100 text-amber-700",
};
const resultClass: Record<string, string> = {
  success: "bg-emerald-100 text-emerald-700",
  no_answer: "bg-slate-200 text-slate-600",
  follow_up: "bg-amber-100 text-amber-700",
  failed: "bg-red-100 text-red-600",
};

/** Export the drilled rows to CSV — the manager's usual next step. */
function exportCsv() {
  const head =
    kind.value === "deals"
      ? ["کد", "عنوان", "مشتری", "کارشناس", "استان", "وضعیت", "مبلغ", "سود", "حاشیه", "تاریخ"]
      : kind.value === "activities"
      ? ["نوع", "مشتری", "کارشناس", "نتیجه", "مدت (دقیقه)", "تاریخ", "توضیح"]
      : kind.value === "feedback"
      ? ["مشتری", "کارشناس", "امتیاز", "توضیح", "تاریخ"]
      : ["کد", "نام", "گروه", "استان", "کارشناس", "وضعیت", "اولین خرید"];
  const body = rows.value.map((r: any) =>
    kind.value === "deals"
      ? [r.code, r.title, r.customer_name, r.owner_name, r.province_name, r.status_display, r.amount_rial, r.profit_rial, r.margin_pct, r.closed_jalali || r.opened_jalali]
      : kind.value === "activities"
      ? [r.kind_display, r.customer_name, r.owner_name, r.result_display, r.duration_min, r.at_jalali, r.note]
      : kind.value === "feedback"
      ? [r.customer_name, r.employee_name, r.score, r.note, r.at_jalali]
      : [r.code, r.name_fa, r.group_name, r.province_name, r.owner_name, r.status_display, r.first_won_jalali],
  );
  const csv = [head, ...body].map((line) => line.map((c: any) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${crm.drill?.title ?? "drill"}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
</script>

<template>
  <Teleport to="body">
    <Transition name="drill">
      <div v-if="open" class="fixed inset-0 z-[60] flex" dir="rtl" @keydown.esc="crm.closeDrill()">
        <div class="flex-1 bg-black/40 backdrop-blur-[2px]" @click="crm.closeDrill()"></div>

        <aside class="w-full max-w-4xl bg-surface h-full shadow-pop flex flex-col animate-slide">
          <!-- Header -->
          <header class="px-5 py-4 bg-panel text-white flex items-start justify-between gap-3 shrink-0">
            <div class="min-w-0">
              <p class="text-[11px] text-white/60">ریز اطلاعات</p>
              <h2 class="font-bold truncate">{{ crm.drill?.title }}</h2>
              <p class="text-xs text-white/70 mt-0.5">{{ num(total) }} رکورد</p>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <button
                class="text-xs bg-white/10 hover:bg-white/20 rounded-lg px-3 py-1.5"
                @click="exportCsv"
              >خروجی اکسل</button>
              <button class="text-white/70 hover:text-white text-2xl leading-none px-1" @click="crm.closeDrill()">×</button>
            </div>
          </header>

          <!-- Reconciliation strip -->
          <div v-if="summary" class="grid grid-cols-2 sm:grid-cols-4 gap-px bg-slate-100 shrink-0">
            <template v-if="kind === 'deals'">
              <div class="bg-surface p-3"><p class="text-[11px] text-slate-400">تعداد</p><p class="font-bold text-ink">{{ num(summary.count) }}</p></div>
              <div class="bg-surface p-3"><p class="text-[11px] text-slate-400">مبلغ</p><p class="font-bold text-ink">{{ rial(summary.amount) }}</p></div>
              <div class="bg-surface p-3"><p class="text-[11px] text-slate-400">سود</p><p class="font-bold text-emerald-600">{{ rial(summary.profit) }}</p></div>
              <div class="bg-surface p-3"><p class="text-[11px] text-slate-400">حاشیه سود</p><p class="font-bold text-ink">{{ pct(summary.margin_pct) }}</p></div>
            </template>
            <template v-else-if="kind === 'activities'">
              <div class="bg-surface p-3"><p class="text-[11px] text-slate-400">تعداد</p><p class="font-bold text-ink">{{ num(summary.count) }}</p></div>
              <div class="bg-surface p-3"><p class="text-[11px] text-slate-400">موفق</p><p class="font-bold text-emerald-600">{{ num(summary.success) }}</p></div>
              <div class="bg-surface p-3"><p class="text-[11px] text-slate-400">نرخ موفقیت</p><p class="font-bold text-ink">{{ pct(summary.success_rate) }}</p></div>
              <div class="bg-surface p-3"><p class="text-[11px] text-slate-400">مشتریان</p><p class="font-bold text-ink">{{ num(summary.customers) }}</p></div>
            </template>
          </div>

          <!-- Rows -->
          <div class="flex-1 overflow-auto">
            <div v-if="loading" class="p-4 space-y-2">
              <Skeleton v-for="i in 8" :key="i" class="h-11 w-full" />
            </div>

            <EmptyState v-else-if="!rows.length" title="رکوردی یافت نشد" />

            <table v-else class="w-full text-sm">
              <thead class="sticky top-0 bg-surface shadow-[0_1px_0_rgb(0,0,0,0.06)] z-10">
                <tr class="text-slate-400 text-xs">
                  <template v-if="kind === 'deals'">
                    <th class="text-right font-medium px-4 py-2.5">معامله</th>
                    <th class="text-right font-medium px-3">کارشناس</th>
                    <th class="text-right font-medium px-3">وضعیت</th>
                    <th class="text-left font-medium px-3">مبلغ</th>
                    <th class="text-left font-medium px-3">سود</th>
                    <th class="text-right font-medium px-4">تاریخ</th>
                  </template>
                  <template v-else-if="kind === 'activities'">
                    <th class="text-right font-medium px-4 py-2.5">فعالیت</th>
                    <th class="text-right font-medium px-3">مشتری</th>
                    <th class="text-right font-medium px-3">کارشناس</th>
                    <th class="text-right font-medium px-3">نتیجه</th>
                    <th class="text-right font-medium px-4">تاریخ</th>
                  </template>
                  <template v-else-if="kind === 'feedback'">
                    <th class="text-right font-medium px-4 py-2.5">مشتری</th>
                    <th class="text-right font-medium px-3">کارشناس</th>
                    <th class="text-right font-medium px-3">امتیاز</th>
                    <th class="text-right font-medium px-3">توضیح</th>
                    <th class="text-right font-medium px-4">تاریخ</th>
                  </template>
                  <template v-else>
                    <th class="text-right font-medium px-4 py-2.5">مشتری</th>
                    <th class="text-right font-medium px-3">گروه</th>
                    <th class="text-right font-medium px-3">استان</th>
                    <th class="text-right font-medium px-3">کارشناس</th>
                    <th class="text-right font-medium px-4">اولین خرید</th>
                  </template>
                </tr>
              </thead>
              <tbody>
                <!-- Deals -->
                <template v-if="kind === 'deals'">
                  <tr
                    v-for="d in (rows as Deal[])" :key="d.id"
                    class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                    @click="goDeal(d)"
                  >
                    <td class="px-4 py-2.5">
                      <p class="text-ink font-medium truncate max-w-[260px]">{{ d.title }}</p>
                      <p class="text-xs text-slate-400 truncate">{{ d.customer_name }}</p>
                    </td>
                    <td class="px-3 text-slate-500">{{ d.owner_name }}</td>
                    <td class="px-3">
                      <span class="text-[11px] rounded-full px-2 py-0.5" :class="statusClass[d.status]">
                        {{ d.status_display }}
                      </span>
                    </td>
                    <td class="px-3 text-left text-ink whitespace-nowrap">{{ rial(d.amount_rial) }}</td>
                    <td class="px-3 text-left whitespace-nowrap" :class="Number(d.profit_rial) >= 0 ? 'text-emerald-600' : 'text-red-500'">
                      {{ rial(d.profit_rial) }}
                    </td>
                    <td class="px-4 text-xs text-slate-400 whitespace-nowrap">{{ d.closed_jalali || d.opened_jalali }}</td>
                  </tr>
                </template>

                <!-- Activities -->
                <template v-else-if="kind === 'activities'">
                  <tr v-for="a in (rows as CrmActivity[])" :key="a.id" class="border-t border-slate-100 hover:bg-slate-50">
                    <td class="px-4 py-2.5">
                      <p class="text-ink">{{ a.kind_display }}</p>
                      <p v-if="a.note" class="text-xs text-slate-400 truncate max-w-[220px]">{{ a.note }}</p>
                    </td>
                    <td class="px-3">
                      <button class="text-slate-500 hover:text-ink hover:underline" @click="goCustomer(a.customer)">
                        {{ a.customer_name }}
                      </button>
                    </td>
                    <td class="px-3 text-slate-500">{{ a.owner_name }}</td>
                    <td class="px-3">
                      <span class="text-[11px] rounded-full px-2 py-0.5" :class="resultClass[a.result]">{{ a.result_display }}</span>
                    </td>
                    <td class="px-4 text-xs text-slate-400 whitespace-nowrap">{{ a.at_jalali }}</td>
                  </tr>
                </template>

                <!-- Feedback -->
                <template v-else-if="kind === 'feedback'">
                  <tr v-for="fb in rows" :key="fb.id" class="border-t border-slate-100 hover:bg-slate-50">
                    <td class="px-4 py-2.5 text-ink">{{ fb.customer_name }}</td>
                    <td class="px-3 text-slate-500">{{ fb.employee_name }}</td>
                    <td class="px-3">
                      <span class="text-[11px] rounded-full px-2 py-0.5" :class="fb.score <= 2 ? 'bg-red-100 text-red-600' : fb.score >= 4 ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-200 text-slate-600'">
                        {{ num(fb.score) }} / ۵
                      </span>
                    </td>
                    <td class="px-3 text-slate-400 text-xs truncate max-w-[220px]">{{ fb.note || "—" }}</td>
                    <td class="px-4 text-xs text-slate-400 whitespace-nowrap">{{ fb.at_jalali }}</td>
                  </tr>
                </template>

                <!-- Customers -->
                <template v-else>
                  <tr
                    v-for="c in (rows as CrmCustomer[])" :key="c.id"
                    class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                    @click="goCustomer(c.id)"
                  >
                    <td class="px-4 py-2.5">
                      <p class="text-ink font-medium">{{ c.name_fa }}</p>
                      <p class="text-xs text-slate-400">{{ c.mobile }}</p>
                    </td>
                    <td class="px-3 text-slate-500">{{ c.group_name }}</td>
                    <td class="px-3 text-slate-500">{{ c.province_name }}</td>
                    <td class="px-3 text-slate-500">{{ c.owner_name }}</td>
                    <td class="px-4 text-xs text-slate-400 whitespace-nowrap">{{ c.first_won_jalali || "—" }}</td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>

          <!-- Pagination -->
          <footer v-if="pages > 1" class="px-4 py-3 border-t border-slate-100 flex items-center justify-between shrink-0">
            <button
              class="text-sm px-3 py-1.5 rounded-lg bg-slate-100 text-slate-600 disabled:opacity-40"
              :disabled="page <= 1" @click="page--"
            >قبلی</button>
            <span class="text-xs text-slate-400">صفحه {{ num(page) }} از {{ num(pages) }}</span>
            <button
              class="text-sm px-3 py-1.5 rounded-lg bg-slate-100 text-slate-600 disabled:opacity-40"
              :disabled="page >= pages" @click="page++"
            >بعدی</button>
          </footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.drill-enter-active, .drill-leave-active { transition: opacity 0.18s ease; }
.drill-enter-from, .drill-leave-to { opacity: 0; }
@keyframes slide-in { from { transform: translateX(-24px); opacity: 0.4; } to { transform: translateX(0); opacity: 1; } }
.animate-slide { animation: slide-in 0.22s cubic-bezier(0.22, 1, 0.36, 1); }
</style>
