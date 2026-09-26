<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { sales2Api, type DocKind, type DocSummary } from "@/api/sales2";
import JalaliDateField from "@/components/JalaliDateField.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import { faDate } from "@/utils/adminFormat";

/** پیش‌فاکتورها / فاکتورهای فروش / مرجوعی‌ها — one list, three kinds. */
const props = defineProps<{ kind: DocKind }>();
const router = useRouter();

const FA = new Intl.NumberFormat("fa-IR");
const fa = (v: number | string | null | undefined) => FA.format(Math.round(Number(v ?? 0)));

const TITLE: Record<DocKind, string> = { proforma: "پیش‌فاکتور", invoice: "فاکتور", return: "مرجوعی" };
const STATUS_CLASS: Record<string, string> = {
  draft: "bg-slate-100 text-slate-600",
  issued: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-red-100 text-red-600",
};

const rows = ref<DocSummary[]>([]);
const loading = ref(true);
const search = ref("");
const status = ref("");
const dateFrom = ref("");
const dateTo = ref("");

async function load() {
  loading.value = true;
  try {
    rows.value = await sales2Api.documents({
      kind: props.kind, status: status.value, search: search.value.trim(),
      date_from: dateFrom.value, date_to: dateTo.value,
    });
  } finally {
    loading.value = false;
  }
}

let timer: ReturnType<typeof setTimeout> | undefined;
watch(search, () => { clearTimeout(timer); timer = setTimeout(load, 300); });
watch([status, dateFrom, dateTo, () => props.kind], load);
onMounted(load);

/** Drafts and cancelled documents are not sales; the header sums what counts. */
const counted = computed(() => rows.value.filter((r) => r.status === "issued"));
const totalNet = computed(() => counted.value.reduce((s, r) => s + Number(r.net_rial), 0));
const totalProfit = computed(() => counted.value.reduce((s, r) => s + Number(r.profit_rial), 0));

function open(r: DocSummary) {
  router.push({ name: "sales2-document", params: { id: r.id }, query: { kind: r.kind } });
}
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <input
        v-model="search" placeholder="جستجوی شماره یا مشتری…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 flex-1 min-w-[180px]"
      />
      <select v-model="status" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
        <option value="">همه وضعیت‌ها</option>
        <option value="draft">پیش‌نویس</option>
        <option value="issued">صادر شده</option>
        <option value="cancelled">ابطال</option>
      </select>
      <div class="w-36"><JalaliDateField v-model="dateFrom" placeholder="از تاریخ" /></div>
      <div class="w-36"><JalaliDateField v-model="dateTo" placeholder="تا تاریخ" /></div>
      <span class="text-xs text-slate-400 px-2">
        {{ FA.format(rows.length) }} سند · خالص <span class="ltr-nums">{{ fa(totalNet) }}</span>
        <template v-if="kind !== 'return'"> · سود <span class="ltr-nums">{{ fa(totalProfit) }}</span></template>
      </span>
      <router-link
        v-if="kind !== 'return'"
        :to="{ name: 'sales2-document-new', params: { kind } }"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm shrink-0"
      >+ {{ TITLE[kind] }} جدید</router-link>
    </div>

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 8" :key="i" class="h-12 rounded-xl" />
    </div>

    <EmptyState
      v-else-if="!rows.length"
      :title="`${TITLE[kind]}ی پیدا نشد`"
      :hint="kind === 'return' ? 'مرجوعی از صفحه‌ی یک فاکتور صادرشده ساخته می‌شود.' : 'با دکمه‌ی بالا اولین سند را بسازید.'"
    />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <div class="px-4 py-2 text-xs text-slate-400 border-b border-slate-100">مبالغ به ریال · خالص یعنی بدون ارزش افزوده</div>
      <ul class="md:hidden divide-y divide-slate-100">
        <li v-for="r in rows" :key="`m-${r.id}`" class="p-4" @click="open(r)">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="text-ink font-medium truncate">{{ r.display_customer }}</p>
              <p class="text-xs text-slate-400 ltr-nums">{{ r.number || `پیش‌نویس #${r.id}` }} · {{ faDate(r.doc_date) }}</p>
            </div>
            <span class="text-xs rounded-full px-2 py-0.5 shrink-0" :class="STATUS_CLASS[r.status]">{{ r.status_label }}</span>
          </div>
          <p class="mt-1 ltr-nums text-ink font-semibold">{{ fa(r.total_rial) }}</p>
        </li>
      </ul>
      <div class="hidden md:block overflow-x-auto">
        <table class="w-full text-sm min-w-[900px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-3">شماره</th>
              <th class="text-right font-medium px-3">تاریخ</th>
              <th class="text-right font-medium px-3">مشتری</th>
              <th class="text-right font-medium px-3">فروشنده</th>
              <th class="text-right font-medium px-3">خالص</th>
              <th class="text-right font-medium px-3">قابل پرداخت</th>
              <th v-if="kind !== 'return'" class="text-right font-medium px-3">سود</th>
              <th class="text-right font-medium px-3">وضعیت</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in rows" :key="r.id"
              class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
              @click="open(r)"
            >
              <td class="px-4 py-2.5 ltr-nums text-ink font-medium">
                {{ r.number || `پیش‌نویس #${r.id}` }}
                <p v-if="r.source_number" class="text-xs text-slate-400">از {{ r.source_number }}</p>
              </td>
              <td class="px-3 text-xs text-slate-500">
                {{ faDate(r.doc_date) }}
                <p v-if="kind === 'proforma' && r.valid_until" :class="r.is_expired ? 'text-amber-600' : 'text-slate-400'">
                  اعتبار تا {{ faDate(r.valid_until) }}
                </p>
                <p v-if="kind === 'invoice' && r.due_date" class="text-slate-400">سررسید {{ faDate(r.due_date) }}</p>
              </td>
              <td class="px-3 text-ink">{{ r.display_customer }}</td>
              <td class="px-3 text-slate-500">{{ r.salesperson_name || "—" }}</td>
              <td class="px-3 ltr-nums">{{ fa(r.net_rial) }}</td>
              <td class="px-3 ltr-nums font-medium text-ink">{{ fa(r.total_rial) }}</td>
              <td v-if="kind !== 'return'" class="px-3 ltr-nums" :class="Number(r.profit_rial) < 0 ? 'text-red-600' : 'text-emerald-600'">
                {{ Number(r.cost_rial) ? fa(r.profit_rial) : "—" }}
                <span v-if="r.override_reason" class="text-amber-600 text-xs" :title="r.override_reason">⚠</span>
              </td>
              <td class="px-3">
                <span class="text-xs rounded-full px-2 py-0.5" :class="STATUS_CLASS[r.status]">{{ r.status_label }}</span>
                <span v-if="r.is_expired" class="text-xs rounded-full px-2 py-0.5 bg-amber-100 text-amber-700 mr-1">منقضی</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
