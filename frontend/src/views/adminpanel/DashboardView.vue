<script setup lang="ts">
/** 6 · Dashboard — the panel's landing page. Every figure is measured. */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { shellApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { faDateTime, faNum, formatBytes } from "@/utils/adminFormat";
import NavIcon from "@/components/NavIcon.vue";
import PageHeader from "@/components/admin/PageHeader.vue";
import StatCard from "@/components/admin/StatCard.vue";
import Timeline from "@/components/admin/Timeline.vue";
import Badge from "@/components/admin/Badge.vue";
import type { DashboardStats } from "@/types/admin";

const admin = useAdminStore();
const router = useRouter();

const stats = ref<DashboardStats | null>(null);
const loading = ref(true);
let timer: number | undefined;

async function load() {
  try {
    stats.value = await shellApi.dashboard();
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  load();
  timer = window.setInterval(load, 60_000); // keep the "online now" figure honest
});
onUnmounted(() => window.clearInterval(timer));

const disk = computed(() => stats.value?.storage.disk);
const diskPct = computed(() => {
  const d = disk.value;
  if (!d?.available || !d.total) return 0;
  return Math.round(((d.used ?? 0) / d.total) * 100);
});

const topTables = computed(() => (stats.value?.database.tables ?? []).slice(0, 8));
const maxRows = computed(() => Math.max(1, ...topTables.value.map((t) => t.rows)));

const QUICK = [
  { name: "admin-users", label: "کاربر جدید", icon: "users", perm: "users.create" },
  { name: "admin-notifications", label: "ارسال اعلان", icon: "megaphone", perm: "notify.send" },
  { name: "admin-database", label: "تهیه پشتیبان", icon: "database", perm: "db.backup" },
  { name: "admin-reports", label: "ساخت گزارش", icon: "clipboard", perm: "reports.view" },
  { name: "admin-audit", label: "بررسی رخدادها", icon: "history", perm: "audit.view" },
  { name: "admin-system", label: "تنظیمات سیستم", icon: "settings", perm: "system.view" },
];
const quickLinks = computed(() => QUICK.filter((q) => admin.can(q.perm)));
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      title="نمای کلی سامانه"
      :description="stats ? `آخرین به‌روزرسانی: ${faDateTime(stats.generated_at)}` : 'در حال بارگذاری…'"
    >
      <template #actions>
        <button
          class="text-sm px-3 py-1.5 rounded-xl bg-slate-100 text-slate-600 hover:bg-slate-200 transition"
          @click="load"
        >بارگذاری مجدد</button>
      </template>
    </PageHeader>

    <div v-if="loading && !stats" class="text-center text-slate-400 py-16 text-sm">
      در حال بارگذاری آمار…
    </div>

    <template v-else-if="stats">
      <!-- Headline numbers -->
      <div class="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
        <StatCard
          label="کل کاربران" :value="faNum(stats.users.total)" icon="users" tone="brand"
          :hint="`${faNum(stats.users.new_this_week)} کاربر جدید این هفته`"
        />
        <StatCard
          label="کاربران فعال" :value="faNum(stats.users.active)" icon="check" tone="good"
          :hint="`${faNum(stats.users.inactive)} غیرفعال`"
        />
        <StatCard
          label="آنلاین در این لحظه" :value="faNum(stats.users.online)" icon="activity" tone="good"
        />
        <StatCard
          label="ادمین‌های سیستم" :value="faNum(stats.users.admins)" icon="shield"
        />
        <StatCard
          label="رخداد ۲۴ ساعت" :value="faNum(stats.activity.audit_24h)" icon="history"
          :hint="`${faNum(stats.activity.audit_total)} رخداد از ابتدا`"
        />
        <StatCard
          label="ورود ناموفق ۲۴ ساعت"
          :value="faNum(stats.activity.failed_logins_24h)"
          icon="alert"
          :tone="stats.activity.failed_logins_24h > 0 ? 'warn' : 'neutral'"
          :hint="`${faNum(stats.activity.logins_24h)} ورود موفق`"
        />
      </div>

      <div class="grid lg:grid-cols-3 gap-4">
        <!-- Activity timeline -->
        <section class="lg:col-span-2 bg-surface rounded-card shadow-soft p-4">
          <div class="flex items-center justify-between mb-3">
            <h2 class="font-semibold text-ink">آخرین فعالیت‌ها</h2>
            <button
              v-if="admin.can('audit.view')"
              class="text-xs text-brand-600 hover:underline"
              @click="router.push({ name: 'admin-audit' })"
            >مشاهده همه</button>
          </div>
          <Timeline :items="stats.recent_activity" />
        </section>

        <div class="space-y-4">
          <!-- Quick actions -->
          <section v-if="quickLinks.length" class="bg-surface rounded-card shadow-soft p-4">
            <h2 class="font-semibold text-ink mb-3">دسترسی سریع</h2>
            <div class="grid grid-cols-2 gap-2">
              <button
                v-for="q in quickLinks"
                :key="q.name + q.label"
                class="flex items-center gap-2 p-2.5 rounded-xl bg-slate-50 hover:bg-slate-100 text-sm text-slate-600 hover:text-ink transition text-right"
                @click="router.push({ name: q.name })"
              >
                <NavIcon :name="q.icon" :size="17" class="shrink-0 text-slate-400" />
                <span class="truncate">{{ q.label }}</span>
              </button>
            </div>
          </section>

          <!-- Storage -->
          <section class="bg-surface rounded-card shadow-soft p-4">
            <h2 class="font-semibold text-ink mb-3">فضای ذخیره‌سازی</h2>
            <template v-if="disk?.available">
              <div class="flex items-baseline justify-between text-sm mb-1">
                <span class="text-slate-500">دیسک سرور</span>
                <span class="ltr-nums text-ink">
                  {{ formatBytes(disk.used ?? 0) }} / {{ formatBytes(disk.total ?? 0) }}
                </span>
              </div>
              <div class="h-2 bg-slate-100 rounded-full overflow-hidden">
                <div
                  class="h-full rounded-full transition-all"
                  :class="diskPct > 90 ? 'bg-red-500' : diskPct > 75 ? 'bg-amber-500' : 'bg-accent-500'"
                  :style="{ width: `${diskPct}%` }"
                ></div>
              </div>
              <p class="text-[11px] text-slate-400 mt-1">{{ faNum(diskPct) }}٪ اشغال‌شده</p>
            </template>
            <p v-else class="text-sm text-slate-400">اطلاعات دیسک در دسترس نیست.</p>

            <dl class="mt-3 space-y-1.5 text-sm">
              <div class="flex justify-between">
                <dt class="text-slate-500">فایل‌های داخل پایگاه داده</dt>
                <dd class="ltr-nums text-ink">{{ formatBytes(stats.storage.db_files_bytes) }}</dd>
              </div>
              <div class="flex justify-between">
                <dt class="text-slate-500">تصاویر پروفایل</dt>
                <dd class="ltr-nums text-ink">{{ formatBytes(stats.storage.db_avatars_bytes) }}</dd>
              </div>
              <div class="flex justify-between">
                <dt class="text-slate-500">پشتیبان‌ها</dt>
                <dd class="ltr-nums text-ink">{{ formatBytes(stats.storage.backups_bytes) }}</dd>
              </div>
            </dl>
          </section>
        </div>
      </div>

      <div class="grid lg:grid-cols-3 gap-4">
        <!-- Database -->
        <section class="lg:col-span-2 bg-surface rounded-card shadow-soft p-4">
          <div class="flex items-center justify-between mb-3">
            <h2 class="font-semibold text-ink">بزرگ‌ترین جدول‌ها</h2>
            <Badge tone="neutral">
              {{ stats.database.vendor }} · {{ faNum(stats.database.table_count) }} جدول ·
              {{ faNum(stats.database.row_total) }} ردیف
            </Badge>
          </div>
          <ul class="space-y-2">
            <li v-for="t in topTables" :key="t.table" class="text-sm">
              <div class="flex items-baseline justify-between gap-2">
                <span class="text-ink truncate">{{ t.label || t.model }}</span>
                <span class="ltr-nums text-slate-400 text-xs shrink-0">
                  {{ faNum(t.rows) }} ردیف<template v-if="t.bytes"> · {{ formatBytes(t.bytes) }}</template>
                </span>
              </div>
              <div class="h-1.5 bg-slate-100 rounded-full mt-1 overflow-hidden">
                <div
                  class="h-full bg-brand-500 rounded-full"
                  :style="{ width: `${Math.max(2, (t.rows / maxRows) * 100)}%` }"
                ></div>
              </div>
            </li>
          </ul>
        </section>

        <!-- Health -->
        <section class="bg-surface rounded-card shadow-soft p-4">
          <h2 class="font-semibold text-ink mb-3">سلامت و خطاها</h2>
          <dl class="space-y-2 text-sm">
            <div class="flex items-center justify-between">
              <dt class="text-slate-500">ورود ناموفق ({{ faNum(stats.errors.window_days) }} روز)</dt>
              <dd>
                <Badge :tone="stats.errors.failed_logins ? 'warn' : 'good'">
                  {{ faNum(stats.errors.failed_logins) }}
                </Badge>
              </dd>
            </div>
            <div class="flex items-center justify-between">
              <dt class="text-slate-500">حساب‌های قفل‌شده</dt>
              <dd>
                <Badge :tone="stats.errors.locked_accounts ? 'bad' : 'good'">
                  {{ faNum(stats.errors.locked_accounts) }}
                </Badge>
              </dd>
            </div>
            <div class="flex items-center justify-between">
              <dt class="text-slate-500">توکن‌های منقضی</dt>
              <dd>
                <Badge :tone="stats.errors.expired_tokens ? 'warn' : 'good'">
                  {{ faNum(stats.errors.expired_tokens) }}
                </Badge>
              </dd>
            </div>
            <div class="flex items-center justify-between">
              <dt class="text-slate-500">اعلان‌های خوانده‌نشده</dt>
              <dd class="ltr-nums text-ink">{{ faNum(stats.activity.notifications_unread) }}</dd>
            </div>
            <div class="flex items-center justify-between">
              <dt class="text-slate-500">سطل بازیافت</dt>
              <dd class="ltr-nums text-ink">{{ faNum(stats.content.recycle_bin) }}</dd>
            </div>
            <div class="flex items-center justify-between">
              <dt class="text-slate-500">پشتیبان‌های موجود</dt>
              <dd class="ltr-nums text-ink">{{ faNum(stats.content.backups) }}</dd>
            </div>
          </dl>

          <div
            v-if="Object.keys(stats.errors.failed_by_reason).length"
            class="mt-3 pt-3 border-t border-slate-100"
          >
            <p class="text-xs text-slate-400 mb-1.5">علت ورودهای ناموفق</p>
            <div class="flex flex-wrap gap-1.5">
              <Badge
                v-for="(count, reason) in stats.errors.failed_by_reason"
                :key="reason" tone="warn"
              >{{ reason }}: {{ faNum(count) }}</Badge>
            </div>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>
