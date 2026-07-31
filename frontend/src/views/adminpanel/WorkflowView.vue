<script setup lang="ts">
/**
 * 13 · Workflow administration — the approval pipeline (draft → submitted →
 * approved) across sales and production, plus the ability to unstick records
 * that have been waiting too long.
 */
import { onMounted, ref } from "vue";
import { workflowApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { confirm, toast } from "@/composables/useUi";
import { apiError, faNum } from "@/utils/adminFormat";
import PageHeader from "@/components/admin/PageHeader.vue";
import Badge from "@/components/admin/Badge.vue";
import NavIcon from "@/components/NavIcon.vue";

const admin = useAdminStore();

const data = ref<Awaited<ReturnType<typeof workflowApi.overview>> | null>(null);
const loading = ref(true);
const selected = ref<Record<string, number[]>>({});

const STATUS_TONE: Record<string, any> = {
  draft: "neutral", submitted: "warn", approved: "good",
  rejected: "bad", needs_revision: "info",
};

async function load() {
  loading.value = true;
  try {
    data.value = await workflowApi.overview();
    selected.value = {};
  } catch (e) {
    toast.error(apiError(e, "بارگذاری گردش‌کار ناموفق بود."));
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function toggle(domain: string, id: number) {
  const current = selected.value[domain] ?? [];
  selected.value = {
    ...selected.value,
    [domain]: current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
  };
}

async function act(domain: string, action: "restart" | "force_approve") {
  const ids = selected.value[domain] ?? [];
  if (!ids.length) return;
  const label = action === "restart" ? "بازگرداندن به پیش‌نویس" : "تایید اجباری";
  if (!(await confirm({
    title: label,
    message: action === "restart"
      ? `${faNum(ids.length)} رکورد به وضعیت پیش‌نویس برمی‌گردد تا صاحبش دوباره ارسال کند.`
      : `${faNum(ids.length)} رکورد بدون طی مسیر عادی تایید می‌شود و در داشبوردها دیده خواهد شد.`,
    danger: true,
  }))) return;
  try {
    const result = await workflowApi.act(domain, ids, action);
    toast.success(`${faNum(result.changed)} رکورد به‌روزرسانی شد.`);
    await load();
  } catch (e) { toast.error(apiError(e)); }
}
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      title="مدیریت گردش‌کار"
      description="وضعیت مسیر تایید داده‌ها و رسیدگی به رکوردهای گیرکرده"
    >
      <template #actions>
        <button
          class="text-sm px-3 py-1.5 rounded-xl bg-slate-100 text-slate-600 hover:bg-slate-200 transition"
          @click="load"
        >بارگذاری مجدد</button>
      </template>
    </PageHeader>

    <div v-if="loading" class="text-center text-slate-400 py-16 text-sm">در حال بارگذاری…</div>

    <template v-else-if="data">
      <!-- Business rules -->
      <section class="bg-surface rounded-card shadow-soft p-4">
        <h2 class="font-semibold text-ink mb-3">قواعد جاری</h2>
        <div class="grid sm:grid-cols-3 gap-3 text-sm">
          <div class="bg-slate-50 rounded-xl p-3">
            <p class="text-xs text-slate-400">نقش تاییدکننده</p>
            <p class="text-ink mt-0.5">
              {{ data.rules.approver === "executive" ? "مدیرعامل" : data.rules.approver }}
            </p>
          </div>
          <div class="bg-slate-50 rounded-xl p-3">
            <p class="text-xs text-slate-400">تایید خودکار ایمپورت‌ها</p>
            <p class="text-ink mt-0.5">{{ data.rules.auto_approve_imports ? "بله" : "خیر" }}</p>
          </div>
          <div class="bg-slate-50 rounded-xl p-3">
            <p class="text-xs text-slate-400">الزام یادداشت هنگام رد</p>
            <p class="text-ink mt-0.5">{{ data.rules.require_note_on_reject ? "بله" : "خیر" }}</p>
          </div>
        </div>
        <p class="text-[11px] text-slate-400 mt-2">
          این قواعد از «تنظیمات سیستم» خوانده می‌شوند و آنجا قابل تغییرند.
        </p>
      </section>

      <!-- Domains -->
      <section
        v-for="domain in data.domains" :key="domain.key"
        class="bg-surface rounded-card shadow-soft p-4"
      >
        <div class="flex flex-wrap items-center justify-between gap-2 mb-3">
          <h2 class="font-semibold text-ink">{{ domain.label }}</h2>
          <Badge tone="neutral">{{ faNum(domain.total) }} رکورد</Badge>
        </div>

        <!-- Pipeline -->
        <div class="flex flex-wrap gap-2 mb-4">
          <div
            v-for="c in domain.counts" :key="c.status"
            class="flex-1 min-w-[130px] rounded-xl p-3 bg-slate-50"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="text-xs text-slate-500">{{ c.label }}</span>
              <Badge :tone="STATUS_TONE[c.status] || 'neutral'" dot>{{ faNum(c.n) }}</Badge>
            </div>
            <div class="h-1.5 bg-slate-200 rounded-full mt-2 overflow-hidden">
              <div
                class="h-full rounded-full"
                :class="{
                  'bg-slate-400': c.status === 'draft',
                  'bg-amber-500': c.status === 'submitted',
                  'bg-accent-500': c.status === 'approved',
                  'bg-red-500': c.status === 'rejected',
                  'bg-sky-500': c.status === 'needs_revision',
                }"
                :style="{ width: `${domain.total ? (c.n / domain.total) * 100 : 0}%` }"
              ></div>
            </div>
          </div>
        </div>

        <!-- Stuck records -->
        <div v-if="domain.stuck.length">
          <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
            <p class="text-sm font-medium text-ink flex items-center gap-1.5">
              <NavIcon name="alert" :size="15" class="text-amber-500" />
              رکوردهای در انتظار بیش از {{ faNum(data.stale_after_days) }} روز
            </p>
            <div v-if="admin.can('workflow.manage')" class="flex gap-1.5">
              <button
                class="text-xs px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 disabled:opacity-40"
                :disabled="!(selected[domain.key]?.length)"
                @click="act(domain.key, 'restart')"
              >بازگرداندن به پیش‌نویس</button>
              <button
                class="text-xs px-2.5 py-1 rounded-lg bg-accent-500 text-white hover:bg-accent-600 disabled:opacity-40"
                :disabled="!(selected[domain.key]?.length)"
                @click="act(domain.key, 'force_approve')"
              >تایید اجباری</button>
            </div>
          </div>
          <ul class="space-y-1">
            <li
              v-for="row in domain.stuck" :key="row.id"
              class="flex items-center gap-2.5 px-3 py-2 rounded-xl bg-amber-50/60 text-sm"
            >
              <input
                v-if="admin.can('workflow.manage')"
                type="checkbox" class="rounded shrink-0"
                :checked="(selected[domain.key] ?? []).includes(row.id)"
                @change="toggle(domain.key, row.id)"
              />
              <span class="flex-1 min-w-0 truncate text-ink">{{ row.repr }}</span>
              <Badge tone="neutral">{{ row.period }}</Badge>
              <Badge tone="warn">{{ faNum(row.waiting_days) }} روز در انتظار</Badge>
            </li>
          </ul>
        </div>
        <p v-else class="text-sm text-accent-600 bg-accent-50 rounded-xl px-3 py-2">
          هیچ رکوردی بیش از {{ faNum(data.stale_after_days) }} روز در انتظار تایید نمانده است.
        </p>
      </section>
    </template>
  </div>
</template>
