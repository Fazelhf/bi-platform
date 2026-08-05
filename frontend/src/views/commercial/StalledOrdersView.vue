<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { foreignApi, type StalledReport } from "@/api/commercialForeign";
import { loadMoneySettings } from "@/composables/useMoney";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * سفارش‌های راکد.
 *
 * «Idle» counts from the last recorded action, not the last status change. A
 * file can sit at «در صف تخصیص» for months while someone chases it weekly —
 * that file is waiting, not abandoned — and the distinction is the whole
 * point of the report.
 */
const router = useRouter();

const data = ref<StalledReport | null>(null);
const loading = ref(true);
const level = ref<"all" | "ok" | "warn" | "danger">("all");

const FA = new Intl.NumberFormat("fa-IR");

const LEVEL = {
  ok: { label: "عادی", dot: "bg-emerald-400", text: "text-slate-600", row: "" },
  warn: { label: "نیازمند پیگیری", dot: "bg-amber-400", text: "text-amber-700", row: "bg-amber-50/40" },
  danger: { label: "راکد", dot: "bg-red-500", text: "text-red-700 font-medium", row: "bg-red-50/40" },
} as const;

onMounted(async () => {
  await loadMoneySettings();
  try {
    data.value = await foreignApi.stalled();
  } finally {
    loading.value = false;
  }
});

const rows = computed(() => {
  const all = data.value?.rows ?? [];
  return level.value === "all" ? all : all.filter((r) => r.level === level.value);
});

const bands = computed(() => data.value?.bands ?? { warn_after: 15, danger_after: 30 });
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-2">
      <Skeleton class="h-20 rounded-card" />
      <Skeleton v-for="i in 6" :key="i" class="h-12 rounded-xl" />
    </div>

    <template v-else-if="data">
      <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
        <button
          class="px-3 py-2 rounded-xl text-sm"
          :class="level === 'all' ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
          @click="level = 'all'"
        >همه ({{ num(data.rows.length) }})</button>
        <button
          v-for="key in (['ok', 'warn', 'danger'] as const)" :key="key"
          class="px-3 py-2 rounded-xl text-sm flex items-center gap-2"
          :class="level === key ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
          @click="level = key"
        >
          <span class="w-2 h-2 rounded-full" :class="LEVEL[key].dot" />
          {{ LEVEL[key].label }}
          <span class="ltr-nums opacity-70">({{ num(data.counts[key]) }})</span>
        </button>
        <span class="text-xs text-slate-400 px-2 ltr-nums">
          زرد پس از {{ FA.format(bands.warn_after) }} روز · قرمز پس از
          {{ FA.format(bands.danger_after) }} روز
        </span>
      </div>

      <EmptyState
        v-if="!rows.length"
        title="پرونده‌ای در این وضعیت نیست"
        hint="پرونده‌های بسته‌شده هیچ‌وقت راکد شمرده نمی‌شوند."
      />

      <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[980px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">پرونده</th>
                <th class="text-right font-medium px-3">کالا</th>
                <th class="text-right font-medium px-3">بانک</th>
                <th class="text-right font-medium px-3">مسئول</th>
                <th class="text-right font-medium px-3">بدون اقدام</th>
                <th class="text-right font-medium px-3">آخرین اقدام</th>
                <th class="text-right font-medium px-4">وضعیت</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in rows" :key="r.id"
                class="border-t border-slate-100 cursor-pointer hover:bg-slate-50"
                :class="LEVEL[r.level].row"
                @click="router.push({ name: 'foreign-order', params: { id: r.id } })"
              >
                <td class="px-4 py-2.5">
                  <p class="text-ink font-medium ltr-nums">{{ r.pi_no }}</p>
                  <p class="text-xs text-slate-400 ltr-nums">{{ r.file_no }}</p>
                </td>
                <td class="px-3 text-slate-500">
                  {{ r.goods || "—" }}
                  <p class="text-xs text-slate-400 ltr-nums">
                    {{ FA.format(Number(r.amount)) }} {{ r.currency }}
                  </p>
                </td>
                <td class="px-3 text-slate-500">{{ r.bank }}</td>
                <td class="px-3 text-slate-500">{{ r.owner || "—" }}</td>
                <td class="px-3 ltr-nums">
                  <span class="flex items-center gap-2" :class="LEVEL[r.level].text">
                    <span class="w-2 h-2 rounded-full shrink-0" :class="LEVEL[r.level].dot" />
                    {{ FA.format(r.idle_days) }} روز
                  </span>
                </td>
                <td class="px-3 text-xs">
                  <p class="text-slate-600">{{ r.last_action || "—" }}</p>
                  <p v-if="r.blocked_reason" class="text-red-500 mt-0.5">
                    علت توقف: {{ r.blocked_reason }}
                  </p>
                  <p v-if="r.last_action_on" class="text-slate-400 ltr-nums mt-0.5">
                    {{ faDate(r.last_action_on) }}
                  </p>
                </td>
                <td class="px-4">
                  <span class="text-xs rounded-full px-2 py-0.5 bg-slate-100 text-slate-600">
                    {{ r.status_label }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
