<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { foreignApi, type Shipment } from "@/api/commercialForeign";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * بارها — split by where they are, because the two groups need different
 * things: a container on the water needs watching, one in customs needs
 * clearing before it starts charging.
 */
const router = useRouter();
const { exact } = useMoney();

const rows = ref<Shipment[]>([]);
const loading = ref(true);
const search = ref("");

const FA = new Intl.NumberFormat("fa-IR");

type Tab = "customs" | "transit" | "done";
const tab = ref<Tab>("customs");

const IN_TRANSIT = new Set(["ready", "departed", "at_sea"]);
const AT_DESTINATION = new Set(["at_port", "customs"]);

const matched = computed(() => {
  const q = search.value.trim();
  if (!q) return rows.value;
  return rows.value.filter((s) =>
    `${s.container_no} ${s.bl_no} ${s.carrier} ${s.goods_desc} ${s.pi_no} ${s.file_no}`.includes(q),
  );
});

const groups = computed(() => ({
  customs: matched.value.filter((s) => AT_DESTINATION.has(s.status)),
  transit: matched.value.filter((s) => IN_TRANSIT.has(s.status)),
  done: matched.value.filter((s) => ["cleared", "delivered"].includes(s.status)),
}));

const shown = computed(() => groups.value[tab.value]);

const TABS = computed(() => [
  { key: "customs" as Tab, label: "در گمرک و بندر", count: groups.value.customs.length },
  { key: "transit" as Tab, label: "در راه", count: groups.value.transit.length },
  { key: "done" as Tab, label: "ترخیص‌شده", count: groups.value.done.length },
]);

/** Tonnage of what is on screen — the number the warehouse asks for. */
const tons = computed(() =>
  shown.value.reduce((sum, s) => sum + Number(s.weight_ton || 0), 0),
);

const accruing = computed(() =>
  shown.value.reduce((sum, s) => sum + Number(s.accruing_rial || 0), 0),
);

onMounted(async () => {
  await loadMoneySettings();
  try {
    rows.value = await foreignApi.shipments();
  } finally {
    loading.value = false;
  }
});

const STATUS_CLASS: Record<string, string> = {
  ready: "bg-slate-100 text-slate-500",
  departed: "bg-sky-100 text-sky-700",
  at_sea: "bg-cyan-100 text-cyan-700",
  at_port: "bg-amber-100 text-amber-700",
  customs: "bg-orange-100 text-orange-700",
  cleared: "bg-emerald-100 text-emerald-700",
  delivered: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-slate-100 text-slate-400",
};
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-2 flex flex-wrap gap-1">
      <button
        v-for="t in TABS" :key="t.key"
        class="px-4 py-2 rounded-xl text-sm transition-colors"
        :class="tab === t.key ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
        @click="tab = t.key"
      >
        {{ t.label }}
        <span class="ltr-nums opacity-70">({{ num(t.count) }})</span>
      </button>
    </div>

    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-3">
      <input
        v-model="search" placeholder="جستجوی کانتینر، بارنامه، شرکت حمل یا پروفرما…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 flex-1 min-w-[220px]"
      />
      <span class="text-xs text-slate-500 ltr-nums">
        {{ num(shown.length) }} کانتینر · {{ num(tons.toFixed(2)) }} تن
      </span>
      <span v-if="accruing" class="text-xs text-red-600 ltr-nums">
        {{ exact(accruing, true) }} دموراژ و انبارداری
      </span>
    </div>

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 8" :key="i" class="h-12 rounded-xl" />
    </div>

    <EmptyState
      v-else-if="!shown.length"
      title="باری در این وضعیت نیست"
    />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[1000px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-3">کانتینر</th>
              <th class="text-right font-medium px-3">پرونده</th>
              <th class="text-right font-medium px-3">کالا</th>
              <th class="text-right font-medium px-3">وزن</th>
              <th class="text-right font-medium px-3">ETD → ETA</th>
              <th class="text-right font-medium px-3">در بندر</th>
              <th class="text-right font-medium px-3">Free Days</th>
              <th class="text-right font-medium px-4">وضعیت</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in shown" :key="s.id"
              class="border-t border-slate-100 cursor-pointer"
              :class="s.demurrage_days > 0 ? 'bg-red-50/40' : 'hover:bg-slate-50'"
              @click="router.push({ name: 'foreign-order', params: { id: s.order } })"
            >
              <td class="px-4 py-2.5">
                <p class="text-ink font-medium ltr-nums">{{ s.container_no || "—" }}</p>
                <p class="text-xs text-slate-400 ltr-nums">{{ s.bl_no }}</p>
              </td>
              <td class="px-3 ltr-nums text-xs text-slate-500">
                {{ s.pi_no }}
                <p class="text-slate-400">{{ s.file_no }}</p>
              </td>
              <td class="px-3 text-slate-500">{{ s.goods_desc || "—" }}</td>
              <td class="px-3 ltr-nums text-slate-500">{{ num(s.weight_ton) }} تن</td>
              <td class="px-3 text-xs text-slate-500 ltr-nums">
                {{ s.etd ? faDate(s.etd) : "—" }} → {{ s.eta ? faDate(s.eta) : "—" }}
              </td>
              <td class="px-3 ltr-nums text-slate-500">
                <span v-if="s.days_at_port === null" class="text-slate-300">نرسیده</span>
                <span v-else>{{ FA.format(s.days_at_port) }} روز</span>
              </td>
              <td class="px-3 ltr-nums text-xs">
                <span v-if="s.free_days_left === null" class="text-slate-300">—</span>
                <span v-else-if="s.free_days_left === 0" class="text-red-600 font-medium">
                  تمام — {{ FA.format(s.demurrage_days) }} روز دموراژ
                </span>
                <span
                  v-else
                  :class="s.free_days_left <= 3 ? 'text-amber-600' : 'text-slate-500'"
                >{{ FA.format(s.free_days_left) }} روز مانده</span>
              </td>
              <td class="px-4">
                <span class="text-xs rounded-full px-2 py-0.5" :class="STATUS_CLASS[s.status]">
                  {{ s.status_label }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
