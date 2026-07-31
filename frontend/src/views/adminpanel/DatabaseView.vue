<script setup lang="ts">
/** 12 · Database utilities — health, table sizes, backups and cleanup jobs. */
import { computed, onMounted, ref } from "vue";
import { databaseApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { confirm, toast } from "@/composables/useUi";
import { apiError, faNum, formatBytes } from "@/utils/adminFormat";
import DataTable, { type Column } from "@/components/admin/DataTable.vue";
import Drawer from "@/components/admin/Drawer.vue";
import PageHeader from "@/components/admin/PageHeader.vue";
import StatCard from "@/components/admin/StatCard.vue";
import Badge from "@/components/admin/Badge.vue";
import type { BackupRow } from "@/types/admin";

const admin = useAdminStore();

const stats = ref<Awaited<ReturnType<typeof databaseApi.stats>> | null>(null);
const backups = ref<BackupRow[]>([]);
const scopes = ref<Awaited<ReturnType<typeof databaseApi.scopes>> | null>(null);
const cleanup = ref<Awaited<ReturnType<typeof databaseApi.cleanupPreview>> | null>(null);
const loading = ref(true);
const cleanupDays = ref(90);
const busyJob = ref("");

const tableColumns: Column[] = [
  { key: "label", label: "جدول" },
  { key: "model", label: "مدل" },
  { key: "rows", label: "ردیف", type: "number" },
  { key: "bytes", label: "حجم", type: "slot" },
];

const backupColumns: Column[] = [
  { key: "filename", label: "فایل" },
  { key: "scope", label: "دامنه", type: "slot" },
  { key: "size_bytes", label: "حجم", type: "bytes" },
  { key: "note", label: "توضیح" },
  { key: "created_by_name", label: "ایجاد توسط" },
  { key: "created_at", label: "زمان", type: "datetime" },
];

async function load() {
  loading.value = true;
  try {
    const [dbStats, backupList, scopeList, cleanupPreview] = await Promise.all([
      databaseApi.stats(),
      databaseApi.backups.list({ page_size: 100 }),
      databaseApi.scopes(),
      admin.can("db.cleanup")
        ? databaseApi.cleanupPreview(cleanupDays.value)
        : Promise.resolve(null),
    ]);
    stats.value = dbStats;
    backups.value = backupList.results;
    scopes.value = scopeList;
    cleanup.value = cleanupPreview;
  } catch (e) {
    toast.error(apiError(e, "بارگذاری وضعیت پایگاه داده ناموفق بود."));
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const tables = computed(() => stats.value?.database.tables ?? []);

// ---------------------------------------------------------------- backup
const backupOpen = ref(false);
const backupForm = ref({ scope: "full", note: "" });
const creating = ref(false);

async function createBackup() {
  creating.value = true;
  try {
    const record = await databaseApi.createBackup(backupForm.value.scope, backupForm.value.note);
    toast.success(`پشتیبان «${record.filename}» ساخته شد.`);
    backupOpen.value = false;
    backupForm.value = { scope: "full", note: "" };
    await load();
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    creating.value = false;
  }
}

async function restore(record: BackupRow) {
  if (!(await confirm({
    title: "بازگردانی پشتیبان",
    message:
      `«${record.filename}» بازگردانی شود؟ رکوردهای فعلی که شناسه مشترک دارند بازنویسی می‌شوند. ` +
      "توصیه: قبل از بازگردانی، یک پشتیبان تازه بگیرید.",
    danger: true,
  }))) return;
  try {
    await databaseApi.restoreBackup(record.id);
    toast.success("بازگردانی انجام شد.");
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

async function removeBackup(record: BackupRow) {
  if (!(await confirm({
    title: "حذف پشتیبان",
    message: `فایل «${record.filename}» از سرور حذف شود؟`,
    danger: true,
  }))) return;
  try {
    await databaseApi.backups.remove(record.id);
    toast.success("پشتیبان حذف شد.");
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

// ---------------------------------------------------------------- cleanup
const JOB_HINTS: Record<string, string> = {
  purge_recycle_bin: "رکوردهای قدیمی سطل بازیافت را برای همیشه پاک می‌کند.",
  purge_audit: "رخدادهای قدیمی‌تر از بازه انتخابی را حذف می‌کند.",
  purge_logins: "تاریخچه ورود قدیمی را حذف می‌کند.",
  purge_notifications: "اعلان‌های خوانده‌شده قدیمی را حذف می‌کند.",
  purge_file_versions: "نسخه‌های بایگانی‌شده فایل‌ها را حذف می‌کند (نسخه فعلی می‌ماند).",
  clear_cache: "کش برنامه را خالی می‌کند.",
  vacuum: "فضای آزادشده SQLite را به سیستم بازمی‌گرداند.",
};

async function runJob(job: string, label: string) {
  const candidates = cleanup.value?.candidates?.[job];
  if (!(await confirm({
    title: label,
    message: candidates !== undefined
      ? `${faNum(candidates)} مورد حذف می‌شود. این عمل قابل بازگشت نیست.`
      : "این عمل انجام شود؟",
    danger: true,
  }))) return;
  busyJob.value = job;
  try {
    const result = await databaseApi.runCleanup(job, cleanupDays.value);
    toast.success(`${result.label}: ${faNum(result.removed)} مورد.`);
    await load();
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    busyJob.value = "";
  }
}
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="پایگاه داده" description="سلامت، حجم جدول‌ها، پشتیبان‌گیری و پاک‌سازی">
      <template #actions>
        <button
          v-if="admin.can('db.backup')"
          class="text-sm px-3 py-1.5 rounded-xl bg-brand-600 text-white hover:bg-brand-700 transition"
          @click="backupOpen = true"
        >+ تهیه پشتیبان</button>
      </template>
    </PageHeader>

    <div v-if="loading" class="text-center text-slate-400 py-16 text-sm">در حال بارگذاری…</div>

    <template v-else-if="stats">
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          label="موتور پایگاه داده" :value="stats.database.vendor" icon="database" tone="brand"
        />
        <StatCard
          label="حجم پایگاه داده"
          :value="stats.database.size_bytes ? formatBytes(stats.database.size_bytes) : '—'"
          icon="layers"
        />
        <StatCard label="تعداد جدول" :value="faNum(stats.database.table_count)" icon="grid" />
        <StatCard label="کل ردیف‌ها" :value="faNum(stats.database.row_total)" icon="clipboard" />
      </div>

      <!-- Health -->
      <section class="bg-surface rounded-card shadow-soft p-4">
        <h2 class="font-semibold text-ink mb-3">بررسی سلامت</h2>
        <div class="flex flex-wrap gap-2">
          <div
            v-for="check in stats.health.checks" :key="check.name"
            class="flex items-center gap-2 px-3 py-2 rounded-xl"
            :class="check.ok ? 'bg-accent-50' : 'bg-red-50'"
          >
            <Badge :tone="check.ok ? 'good' : 'bad'" dot>{{ check.name }}</Badge>
            <span v-if="check.ms" class="text-xs text-slate-500 ltr-nums">{{ check.ms }} ms</span>
            <span v-if="check.error" class="text-xs text-red-600">{{ check.error }}</span>
          </div>
        </div>
      </section>

      <div class="grid lg:grid-cols-2 gap-4">
        <!-- Cleanup -->
        <section v-if="cleanup" class="bg-surface rounded-card shadow-soft p-4">
          <div class="flex items-center justify-between gap-2 mb-3">
            <h2 class="font-semibold text-ink">پاک‌سازی</h2>
            <label class="flex items-center gap-2 text-xs text-slate-500">
              قدیمی‌تر از
              <input
                v-model.number="cleanupDays" type="number" min="1" max="3650"
                class="w-20 border border-slate-200 rounded-lg px-2 py-1 text-sm bg-surface ltr-nums"
                @change="load"
              />
              روز
            </label>
          </div>
          <ul class="space-y-2">
            <li
              v-for="job in cleanup.jobs" :key="job.key"
              class="flex items-start justify-between gap-3 pb-2 border-b border-slate-50 last:border-0"
            >
              <div class="min-w-0">
                <p class="text-sm text-ink">{{ job.label }}</p>
                <p class="text-[11px] text-slate-400">{{ JOB_HINTS[job.key] }}</p>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <Badge v-if="cleanup.candidates[job.key] !== undefined" tone="neutral">
                  {{ faNum(cleanup.candidates[job.key]) }}
                </Badge>
                <button
                  v-if="admin.can('db.cleanup')"
                  class="text-xs px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 disabled:opacity-40"
                  :disabled="busyJob === job.key"
                  @click="runJob(job.key, job.label)"
                >{{ busyJob === job.key ? "…" : "اجرا" }}</button>
              </div>
            </li>
          </ul>
        </section>

        <!-- Tables -->
        <section class="bg-surface rounded-card shadow-soft overflow-hidden">
          <h2 class="font-semibold text-ink p-4 pb-0">جدول‌ها</h2>
          <DataTable
            :columns="tableColumns"
            :rows="tables"
            row-key="table"
            :page-size="10"
            search-placeholder="نام جدول…"
            class="!shadow-none"
          >
            <template #cell-bytes="{ row }">
              <span v-if="row.bytes" class="ltr-nums">{{ formatBytes(row.bytes) }}</span>
              <span v-else class="text-slate-300">—</span>
            </template>
          </DataTable>
        </section>
      </div>

      <!-- Backups -->
      <DataTable
        :columns="backupColumns"
        :rows="backups"
        empty-title="پشتیبانی تهیه نشده است"
        empty-hint="پشتیبان‌ها فایل JSON قابل حمل هستند و روی SQLite و PostgreSQL کار می‌کنند."
        @refresh="load"
      >
        <template #cell-scope="{ row }">
          <Badge tone="neutral">
            {{ scopes?.scopes.find((s) => s.value === row.scope)?.label ?? row.scope }}
          </Badge>
        </template>
        <template #actions="{ row }">
          <div class="flex items-center gap-2 text-xs">
            <button
              class="text-brand-600 hover:underline"
              @click="databaseApi.downloadBackup(row.id, row.filename)"
            >دانلود</button>
            <button
              v-if="admin.can('db.restore')"
              class="text-amber-600 hover:underline"
              @click="restore(row)"
            >بازگردانی</button>
            <button
              v-if="admin.can('db.backup')"
              class="text-red-500 hover:underline"
              @click="removeBackup(row)"
            >حذف</button>
          </div>
        </template>
      </DataTable>

      <p
        v-if="scopes?.orphan_files.length"
        class="text-xs text-amber-700 bg-amber-50 rounded-xl px-3 py-2"
      >
        {{ faNum(scopes.orphan_files.length) }} فایل پشتیبان روی سرور هست که در این فهرست ثبت نشده
        (احتمالاً دستی کپی شده): {{ scopes.orphan_files.map((f) => f.filename).join("، ") }}
      </p>
    </template>

    <!-- ============ Backup drawer ============ -->
    <Drawer :open="backupOpen" title="تهیه پشتیبان" width="sm" :busy="creating" @close="backupOpen = false">
      <div class="space-y-3">
        <label class="block">
          <span class="text-xs text-slate-500">دامنه پشتیبان</span>
          <select v-model="backupForm.scope" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
            <option v-for="s in scopes?.scopes ?? []" :key="s.value" :value="s.value">{{ s.label }}</option>
          </select>
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">توضیح</span>
          <input
            v-model="backupForm.note" placeholder="مثلاً: قبل از تغییر ساختار تیم‌ها"
            class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface"
          />
        </label>
        <p class="text-[11px] text-slate-400">
          نشست‌ها و مجوزهای داخلی جنگو در پشتیبان نمی‌آیند؛ بازگردانی، نشست‌های مرده را زنده نمی‌کند.
        </p>
      </div>
      <template #footer>
        <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="backupOpen = false">انصراف</button>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          :disabled="creating"
          @click="createBackup"
        >{{ creating ? "در حال تهیه…" : "تهیه پشتیبان" }}</button>
      </template>
    </Drawer>
  </div>
</template>
