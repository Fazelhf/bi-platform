<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { foreignApi, type Workbench } from "@/api/commercialForeign";
import { useAuthStore } from "@/stores/auth";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import FxRateForm from "@/components/commercial/FxRateForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * میز کار — what needs a person today, grouped by why.
 *
 * The old dashboard led with counts. Counts describe; they do not tell you
 * where to start. This leads with the work itself, worst first, and a file
 * appears in every group whose problem it has — two problems mean two rows,
 * because fixing one does not fix the other.
 *
 * The rate strip sits at the bottom: reference, glanced at, not worked on.
 */
const router = useRouter();
const auth = useAuthStore();
const { exact } = useMoney();

const data = ref<Workbench | null>(null);
const loading = ref(true);
const error = ref("");
const open = ref<Record<string, boolean>>({});

const FA = new Intl.NumberFormat("fa-IR");

const canEdit = computed(
  () => auth.department === "commercial" || !!auth.me?.is_superuser,
);

async function load() {
  loading.value = true;
  try {
    data.value = await foreignApi.workbench();
    // Danger groups start open; the rest collapsed, so the page opens on the
    // things that cost money rather than on a wall of rows.
    for (const g of data.value.groups) open.value[g.key] = g.level === "danger";
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await loadMoneySettings(); await load(); });

const showRateForm = ref(false);

function go(row: { id: number }) {
  router.push({ name: "foreign-order", params: { id: row.id } });
}

function ageTone(age: number | null): string {
  if (age === null) return "text-slate-300";
  if (age === 0) return "text-emerald-600";
  if (age <= 3) return "text-slate-400";
  return "text-amber-600";
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-16 rounded-card" />
      <Skeleton v-for="i in 3" :key="i" class="h-40 rounded-card" />
    </div>

    <p v-else-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">
      {{ error }}
    </p>

    <template v-else-if="data">
      <div class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <p class="text-ink">
          <span class="text-2xl font-bold ltr-nums">
            {{ num(data.totals.needing_action) }}
          </span>
          <span class="text-sm text-slate-500"> پرونده نیاز به اقدام دارد</span>
        </p>
        <p class="text-xs text-slate-400 ltr-nums">
          از {{ num(data.totals.live_files) }} پرونده فعال
        </p>
      </div>

      <EmptyState
        v-if="!data.groups.length"
        icon="✅"
        title="هیچ پرونده‌ای منتظر اقدام نیست"
        hint="نه مهلتی نزدیک است، نه کانتینری هزینه می‌سازد، نه پرونده‌ای بی‌حرکت مانده."
      />

      <!-- One card per reason -->
      <div
        v-for="g in data.groups" :key="g.key"
        class="bg-surface rounded-card shadow-soft overflow-hidden"
        :class="g.level === 'danger' ? 'ring-1 ring-red-100' : ''"
      >
        <button
          class="w-full px-4 py-3 flex items-center gap-3 text-right hover:bg-slate-50"
          @click="open[g.key] = !open[g.key]"
        >
          <span
            class="w-2.5 h-2.5 rounded-full shrink-0"
            :class="g.level === 'danger' ? 'bg-red-500' : 'bg-amber-400'"
          />
          <span class="font-bold text-ink text-sm">{{ g.title }}</span>
          <span
            class="text-xs rounded-full px-2 py-0.5 ltr-nums"
            :class="g.level === 'danger'
              ? 'bg-red-50 text-red-600' : 'bg-amber-50 text-amber-700'"
          >{{ num(g.rows.length) }}</span>
          <span class="text-xs text-slate-400 flex-1">{{ g.hint }}</span>
          <span class="text-slate-300 text-xs">{{ open[g.key] ? "▲" : "▼" }}</span>
        </button>

        <div v-if="open[g.key]" class="overflow-x-auto border-t border-slate-100">
          <table class="w-full text-sm min-w-[820px]">
            <tbody>
              <tr
                v-for="(r, i) in g.rows" :key="`${g.key}-${r.id}-${i}`"
                class="border-b border-slate-50 last:border-0 hover:bg-slate-50 cursor-pointer"
                @click="go(r)"
              >
                <td class="px-4 py-2.5 w-52">
                  <p class="text-ink font-medium ltr-nums">{{ r.pi_no }}</p>
                  <p class="text-xs text-slate-400">
                    {{ r.goods || r.file_no }}
                  </p>
                </td>
                <td class="px-3 text-xs text-slate-500 w-40">
                  {{ r.bank || "—" }}
                  <p class="text-slate-400 ltr-nums">
                    {{ FA.format(Number(r.amount)) }} {{ r.currency }}
                  </p>
                </td>
                <td class="px-3 text-sm">
                  <span
                    :class="g.level === 'danger' ? 'text-red-700' : 'text-amber-700'"
                  >{{ r.reason }}</span>
                  <p v-if="r.container_no" class="text-xs text-slate-400 ltr-nums">
                    کانتینر {{ r.container_no }}
                  </p>
                  <p v-else-if="r.deadline" class="text-xs text-slate-400 ltr-nums">
                    {{ faDate(r.deadline) }}
                  </p>
                </td>
                <td class="px-3 text-left ltr-nums whitespace-nowrap w-40">
                  <span
                    v-if="r.days !== null && r.days !== undefined"
                    class="text-sm"
                    :class="g.level === 'danger' ? 'text-red-700 font-medium' : 'text-slate-600'"
                  >
                    {{ r.days < 0
                      ? `${FA.format(Math.abs(r.days))} روز گذشته`
                      : `${FA.format(r.days)} روز` }}
                  </span>
                  <p v-if="r.over_by" class="text-xs text-slate-400">
                    {{ FA.format(r.over_by) }} روز فراتر از مهلت
                  </p>
                  <p v-if="r.accrued_rial && Number(r.accrued_rial)"
                     class="text-xs text-red-600">
                    {{ exact(r.accrued_rial) }}
                  </p>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Rate strip: reference, not a workplace -->
      <div class="bg-surface rounded-card shadow-soft p-3">
        <div class="flex items-center justify-between mb-2">
          <p class="text-xs text-slate-400">نرخ ارز</p>
          <button
            v-if="canEdit"
            class="text-xs text-slate-400 hover:text-ink"
            @click="showRateForm = true"
          >+ ثبت نرخ</button>
        </div>
        <div class="flex flex-wrap gap-x-6 gap-y-2">
          <span
            v-for="r in data.rates" :key="`${r.currency}-${r.kind}`"
            class="text-xs"
          >
            <span class="text-slate-500">{{ r.currency_label }} {{ r.kind_label }}</span>
            <span v-if="r.rate_rial" class="text-ink ltr-nums mr-1 font-medium">
              {{ FA.format(Number(r.rate_rial)) }}
            </span>
            <span v-else class="text-slate-300 mr-1">ثبت نشده</span>
            <span v-if="r.age_days" class="ltr-nums" :class="ageTone(r.age_days)">
              ({{ FA.format(r.age_days) }} روز پیش)
            </span>
          </span>
        </div>
      </div>

      <FxRateForm
        v-if="showRateForm"
        @close="showRateForm = false"
        @saved="showRateForm = false; load()"
      />
    </template>
  </div>
</template>
