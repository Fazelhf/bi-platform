<script setup lang="ts">
/**
 * 14 · Monitoring — server, API health, background queues and error summary.
 *
 * Where a metric genuinely cannot be collected on this stack (no Celery
 * worker, no disk API), the page says so instead of showing a fake zero.
 */
import { onMounted, onUnmounted, ref } from "vue";
import { monitoringApi } from "@/api/admin";
import { toast } from "@/composables/useUi";
import { apiError, duration, faDateTime, faNum, formatBytes } from "@/utils/adminFormat";
import PageHeader from "@/components/admin/PageHeader.vue";
import StatCard from "@/components/admin/StatCard.vue";
import Badge from "@/components/admin/Badge.vue";
import type { Monitoring } from "@/types/admin";

const data = ref<Monitoring | null>(null);
const loading = ref(true);
const auto = ref(true);
let timer: number | undefined;

async function load() {
  try {
    data.value = await monitoringApi.get();
  } catch (e) {
    toast.error(apiError(e, "بارگذاری وضعیت پایش ناموفق بود."));
  } finally {
    loading.value = false;
  }
}

function schedule() {
  window.clearInterval(timer);
  if (auto.value) timer = window.setInterval(load, 30_000);
}

onMounted(() => { load(); schedule(); });
onUnmounted(() => window.clearInterval(timer));

const QUEUE_REASON: Record<string, string> = {
  eager: "کارها به‌صورت همزمان اجرا می‌شوند (بدون کارگر پس‌زمینه).",
  no_workers: "هیچ کارگر Celery پاسخ نداد — سرویس کارگر اجرا نشده است.",
  error: "ارتباط با بروکر برقرار نشد.",
};
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="پایش سامانه" description="وضعیت سرور، سلامت API، صف کارها و خلاصه خطاها">
      <template #actions>
        <label class="flex items-center gap-2 text-xs text-slate-500">
          <input v-model="auto" type="checkbox" class="rounded" @change="schedule" />
          به‌روزرسانی خودکار (۳۰ ثانیه)
        </label>
        <button
          class="text-sm px-3 py-1.5 rounded-xl bg-slate-100 text-slate-600 hover:bg-slate-200 transition"
          @click="load"
        >بررسی مجدد</button>
      </template>
    </PageHeader>

    <div v-if="loading" class="text-center text-slate-400 py-16 text-sm">در حال بررسی…</div>

    <template v-else-if="data">
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          label="وضعیت API"
          :value="data.api.ok ? 'سالم' : 'مشکل دارد'"
          icon="activity"
          :tone="data.api.ok ? 'good' : 'bad'"
        />
        <StatCard
          label="مدت فعالیت سرور"
          :value="duration(data.server.uptime_seconds)"
          icon="server"
        />
        <StatCard
          label="صف کارها"
          :value="data.queues.available ? 'فعال' : 'بدون کارگر'"
          icon="layers"
          :tone="data.queues.available ? 'good' : 'neutral'"
        />
        <StatCard
          label="خطاهای ۷ روز اخیر"
          :value="faNum(data.errors.failed_logins)"
          icon="alert"
          :tone="data.errors.failed_logins ? 'warn' : 'good'"
        />
      </div>

      <div class="grid lg:grid-cols-2 gap-4">
        <!-- Server -->
        <section class="bg-surface rounded-card shadow-soft p-4">
          <h2 class="font-semibold text-ink mb-3">سرور</h2>
          <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <div class="flex justify-between col-span-2">
              <dt class="text-slate-500">نام میزبان</dt>
              <dd class="text-ink ltr-nums">{{ data.server.hostname }}</dd>
            </div>
            <div class="flex justify-between col-span-2">
              <dt class="text-slate-500">سیستم‌عامل</dt>
              <dd class="text-ink ltr-nums">{{ data.server.platform }}</dd>
            </div>
            <div class="flex justify-between col-span-2">
              <dt class="text-slate-500">پایتون / جنگو</dt>
              <dd class="text-ink ltr-nums">{{ data.server.python }} / {{ data.server.django }}</dd>
            </div>
            <div class="flex justify-between col-span-2">
              <dt class="text-slate-500">منطقه زمانی</dt>
              <dd class="text-ink ltr-nums">{{ data.server.timezone }}</dd>
            </div>
            <div class="flex justify-between col-span-2">
              <dt class="text-slate-500">حالت اشکال‌زدایی</dt>
              <dd>
                <Badge :tone="data.server.debug ? 'bad' : 'good'">
                  {{ data.server.debug ? "روشن — برای محیط عملیاتی خاموش کنید" : "خاموش" }}
                </Badge>
              </dd>
            </div>
            <div class="flex justify-between col-span-2">
              <dt class="text-slate-500">شروع پردازه</dt>
              <dd class="text-ink">{{ faDateTime(data.server.started_at) }}</dd>
            </div>
          </dl>
        </section>

        <!-- API health -->
        <section class="bg-surface rounded-card shadow-soft p-4">
          <h2 class="font-semibold text-ink mb-3">سلامت سرویس‌ها</h2>
          <ul class="space-y-2">
            <li
              v-for="check in data.api.checks" :key="check.name"
              class="flex items-center justify-between gap-2 p-2.5 rounded-xl"
              :class="check.ok ? 'bg-accent-50' : 'bg-red-50'"
            >
              <span class="flex items-center gap-2 text-sm">
                <Badge :tone="check.ok ? 'good' : 'bad'" dot>{{ check.name }}</Badge>
                <span v-if="check.backend" class="text-xs text-slate-500">{{ check.backend }}</span>
              </span>
              <span v-if="check.ms" class="text-xs text-slate-500 ltr-nums">{{ check.ms }} ms</span>
              <span v-else-if="check.error" class="text-xs text-red-600 truncate">{{ check.error }}</span>
            </li>
          </ul>

          <h3 class="font-semibold text-ink text-sm mt-4 mb-2">پایگاه داده</h3>
          <dl class="space-y-1.5 text-sm">
            <div class="flex justify-between">
              <dt class="text-slate-500">موتور</dt>
              <dd class="text-ink ltr-nums">{{ data.database.vendor }}</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-500">حجم</dt>
              <dd class="text-ink ltr-nums">
                {{ data.database.size_bytes ? formatBytes(data.database.size_bytes) : "—" }}
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-500">جدول‌ها / ردیف‌ها</dt>
              <dd class="text-ink ltr-nums">
                {{ faNum(data.database.table_count) }} / {{ faNum(data.database.row_total) }}
              </dd>
            </div>
          </dl>
        </section>

        <!-- Queues -->
        <section class="bg-surface rounded-card shadow-soft p-4">
          <h2 class="font-semibold text-ink mb-3">کارهای پس‌زمینه</h2>
          <template v-if="data.queues.available">
            <p class="text-xs text-slate-400 mb-2 ltr-nums">بروکر: {{ data.queues.broker }}</p>
            <ul class="space-y-2">
              <li
                v-for="w in data.queues.workers ?? []" :key="w.name"
                class="p-2.5 rounded-xl bg-slate-50"
              >
                <p class="text-sm text-ink ltr-nums">{{ w.name }}</p>
                <div class="flex gap-2 mt-1">
                  <Badge tone="brand">در حال اجرا: {{ faNum(w.active) }}</Badge>
                  <Badge tone="neutral">رزروشده: {{ faNum(w.reserved) }}</Badge>
                  <Badge tone="info">زمان‌بندی‌شده: {{ faNum(w.scheduled) }}</Badge>
                </div>
              </li>
            </ul>
          </template>
          <div v-else class="bg-slate-50 rounded-xl p-3">
            <Badge tone="neutral">در دسترس نیست</Badge>
            <p class="text-sm text-slate-500 mt-2">
              {{ data.queues.detail || QUEUE_REASON[data.queues.reason ?? ""] || "وضعیت نامشخص" }}
            </p>
            <p class="text-[11px] text-slate-400 mt-1">
              گزارش‌های زمان‌بندی‌شده و کارهای سنگین به یک کارگر Celery نیاز دارند.
            </p>
          </div>
        </section>

        <!-- Errors -->
        <section class="bg-surface rounded-card shadow-soft p-4">
          <h2 class="font-semibold text-ink mb-3">
            خلاصه خطاها ({{ faNum(data.errors.window_days) }} روز اخیر)
          </h2>
          <dl class="space-y-2 text-sm">
            <div class="flex items-center justify-between">
              <dt class="text-slate-500">ورودهای ناموفق</dt>
              <dd>
                <Badge :tone="data.errors.failed_logins ? 'warn' : 'good'">
                  {{ faNum(data.errors.failed_logins) }}
                </Badge>
              </dd>
            </div>
            <div class="flex items-center justify-between">
              <dt class="text-slate-500">حساب‌های قفل‌شده</dt>
              <dd>
                <Badge :tone="data.errors.locked_accounts ? 'bad' : 'good'">
                  {{ faNum(data.errors.locked_accounts) }}
                </Badge>
              </dd>
            </div>
            <div class="flex items-center justify-between">
              <dt class="text-slate-500">توکن‌های منقضی فعال</dt>
              <dd>
                <Badge :tone="data.errors.expired_tokens ? 'warn' : 'good'">
                  {{ faNum(data.errors.expired_tokens) }}
                </Badge>
              </dd>
            </div>
          </dl>

          <div
            v-if="Object.keys(data.errors.failed_by_reason).length"
            class="mt-3 pt-3 border-t border-slate-100"
          >
            <p class="text-xs text-slate-400 mb-1.5">تفکیک بر اساس علت</p>
            <div class="flex flex-wrap gap-1.5">
              <Badge
                v-for="(count, reason) in data.errors.failed_by_reason"
                :key="reason" tone="warn"
              >{{ reason }}: {{ faNum(count) }}</Badge>
            </div>
          </div>
          <p v-else class="text-sm text-accent-600 bg-accent-50 rounded-xl px-3 py-2 mt-3">
            خطای امنیتی‌ای در این بازه ثبت نشده است.
          </p>
        </section>
      </div>

      <p class="text-[11px] text-slate-400 text-center">
        آخرین بررسی: {{ faDateTime(data.checked_at) }}
      </p>
    </template>
  </div>
</template>
