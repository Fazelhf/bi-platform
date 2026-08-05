<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { commercialApi, type PurchaseRequest } from "@/api/commercial";
import { useAuthStore } from "@/stores/auth";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { num } from "@/utils/format";
import RequestForm from "@/components/commercial/RequestForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/** درخواست‌های خرید و وضعیت استعلامشان. */
const auth = useAuthStore();
const router = useRouter();
const { exact } = useMoney();

const rows = ref<PurchaseRequest[]>([]);
const loading = ref(true);
const search = ref("");
const status = ref("");

const canEdit = computed(
  () => auth.department === "commercial" || !!auth.me?.is_superuser,
);

const STATUS_CLASS: Record<string, string> = {
  open: "bg-sky-100 text-sky-700",
  quoting: "bg-amber-100 text-amber-700",
  awarded: "bg-violet-100 text-violet-700",
  ordered: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-slate-100 text-slate-500",
};

const filtered = computed(() => {
  const q = search.value.trim();
  return rows.value.filter((r) => {
    if (status.value && r.status !== status.value) return false;
    if (q && !`${r.request_no} ${r.material_name} ${r.requester_unit} ${r.note}`.includes(q))
      return false;
    return true;
  });
});

async function load() {
  loading.value = true;
  try {
    rows.value = await commercialApi.requests();
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await loadMoneySettings(); await load(); });

const showForm = ref(false);

function onSaved(saved: PurchaseRequest) {
  showForm.value = false;
  // Straight into the new request: the next thing anyone does after stating a
  // need is collect prices for it, and that lives on the detail page.
  router.push({ name: "commercial-request", params: { id: saved.id } });
}
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <input
        v-model="search" placeholder="جستجوی شماره، کالا یا واحد…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 flex-1 min-w-[200px]"
      />
      <select v-model="status" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
        <option value="">همه وضعیت‌ها</option>
        <option value="open">ثبت‌شده</option>
        <option value="quoting">در حال استعلام</option>
        <option value="awarded">تامین‌کننده انتخاب شد</option>
        <option value="ordered">سفارش ثبت شد</option>
        <option value="cancelled">لغو شده</option>
      </select>
      <span class="text-xs text-slate-400 px-2">{{ num(filtered.length) }} درخواست</span>
      <button
        v-if="canEdit"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm shrink-0"
        @click="showForm = true"
      >+ درخواست خرید</button>
    </div>

    <RequestForm v-if="showForm" @close="showForm = false" @saved="onSaved" />

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 8" :key="i" class="h-12 rounded-xl" />
    </div>

    <EmptyState
      v-else-if="!filtered.length"
      title="درخواستی ثبت نشده"
      hint="نیاز کارخانه را اینجا ثبت کنید، بعد از چند تامین‌کننده قیمت بگیرید."
    />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[840px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-3">شماره</th>
              <th class="text-right font-medium px-3">کالا</th>
              <th class="text-right font-medium px-3">مقدار</th>
              <th class="text-right font-medium px-3">واحد درخواست‌کننده</th>
              <th class="text-right font-medium px-3">استعلام</th>
              <th class="text-right font-medium px-3">کمترین قیمت</th>
              <th class="text-right font-medium px-3">انتخاب‌شده</th>
              <th class="text-right font-medium px-4">وضعیت</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in filtered" :key="r.id"
              class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
              @click="router.push({ name: 'commercial-request', params: { id: r.id } })"
            >
              <td class="px-4 py-2.5 text-ink font-medium ltr-nums">{{ r.request_no }}</td>
              <td class="px-3 text-ink">{{ r.material_name }}</td>
              <td class="px-3 text-slate-500 ltr-nums">
                {{ num(r.quantity) }} {{ r.material_unit }}
              </td>
              <td class="px-3 text-slate-500">{{ r.requester_unit || "—" }}</td>
              <td class="px-3 text-slate-500 ltr-nums">{{ num(r.quote_count) }}</td>
              <td class="px-3 text-ink ltr-nums">
                {{ Number(r.best_price_rial) ? exact(r.best_price_rial) : "—" }}
              </td>
              <td class="px-3 text-slate-500">{{ r.selected_supplier || "—" }}</td>
              <td class="px-4">
                <span
                  class="text-xs rounded-full px-2 py-0.5"
                  :class="STATUS_CLASS[r.status]"
                >{{ r.status_label }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
