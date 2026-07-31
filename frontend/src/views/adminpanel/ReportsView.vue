<script setup lang="ts">
/**
 * 11 · Reports — preview on screen, download as xlsx/csv, or open a
 * print-ready page for PDF. Definitions can be saved and re-run.
 */
import { onMounted, ref } from "vue";
import { reportsApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { confirm, toast } from "@/composables/useUi";
import { apiError, faDateTime, faNum } from "@/utils/adminFormat";
import DataTable, { type Column } from "@/components/admin/DataTable.vue";
import Drawer from "@/components/admin/Drawer.vue";
import PageHeader from "@/components/admin/PageHeader.vue";
import Badge from "@/components/admin/Badge.vue";
import Toggle from "@/components/admin/Toggle.vue";
import type { ReportDefinition } from "@/types/admin";

const admin = useAdminStore();

const meta = ref<Awaited<ReturnType<typeof reportsApi.kinds>> | null>(null);
const saved = ref<ReportDefinition[]>([]);
const loading = ref(true);

const builder = ref({ kind: "users", days: "30" });
const preview = ref<Awaited<ReturnType<typeof reportsApi.preview>> | null>(null);
const previewing = ref(false);

const savedColumns: Column[] = [
  { key: "name", label: "گزارش" },
  { key: "kind_label", label: "نوع" },
  { key: "fmt", label: "قالب" },
  { key: "frequency_label", label: "تناوب" },
  { key: "last_run_at", label: "آخرین اجرا", type: "slot" },
  { key: "is_active", label: "فعال", type: "bool", align: "center" },
];

async function load() {
  loading.value = true;
  try {
    const [kinds, list] = await Promise.all([
      reportsApi.kinds(),
      reportsApi.list({ page_size: 100 }),
    ]);
    meta.value = kinds;
    saved.value = list.results;
  } catch (e) {
    toast.error(apiError(e, "بارگذاری گزارش‌ها ناموفق بود."));
  } finally {
    loading.value = false;
  }
}
onMounted(() => { load(); runPreview(); });

const NEEDS_DAYS = ["activity", "audit", "logins"];

async function runPreview() {
  previewing.value = true;
  try {
    const params: Record<string, any> = {};
    if (NEEDS_DAYS.includes(builder.value.kind)) params.days = builder.value.days;
    preview.value = await reportsApi.preview(builder.value.kind, params);
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    previewing.value = false;
  }
}

function downloadNow(fmt: string) {
  const params: Record<string, any> = {};
  if (NEEDS_DAYS.includes(builder.value.kind)) params.days = builder.value.days;
  reportsApi.run(builder.value.kind, fmt, params).catch((e) => toast.error(apiError(e)));
}

// ---------------------------------------------------------------- saved
const saveOpen = ref(false);
const editing = ref<ReportDefinition | null>(null);
const form = ref<Record<string, any>>({});

function openSave(definition?: ReportDefinition) {
  editing.value = definition ?? null;
  form.value = definition
    ? {
      name: definition.name, kind: definition.kind, fmt: definition.fmt,
      frequency: definition.frequency, is_active: definition.is_active,
      params: definition.params ?? {},
    }
    : {
      name: "", kind: builder.value.kind, fmt: "xlsx", frequency: "manual",
      is_active: true,
      params: NEEDS_DAYS.includes(builder.value.kind) ? { days: builder.value.days } : {},
    };
  saveOpen.value = true;
}

async function saveDefinition() {
  try {
    if (editing.value) await reportsApi.patch(editing.value.id, form.value);
    else await reportsApi.create(form.value);
    toast.success("گزارش ذخیره شد.");
    saveOpen.value = false;
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

async function removeDefinition(definition: ReportDefinition) {
  if (!(await confirm({
    title: "حذف گزارش",
    message: `«${definition.name}» حذف شود؟`,
    danger: true,
  }))) return;
  try {
    await reportsApi.remove(definition.id);
    toast.success("گزارش حذف شد.");
    await load();
  } catch (e) { toast.error(apiError(e)); }
}
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      title="گزارش‌ها"
      description="ساخت گزارش از داده‌های واقعی سامانه و خروجی گرفتن در قالب اکسل، CSV یا PDF"
    >
      <template #actions>
        <button
          v-if="admin.can('reports.generate')"
          class="text-sm px-3 py-1.5 rounded-xl bg-brand-600 text-white hover:bg-brand-700 transition"
          @click="openSave()"
        >+ ذخیره گزارش فعلی</button>
      </template>
    </PageHeader>

    <!-- Builder -->
    <section class="bg-surface rounded-card shadow-soft p-4">
      <div class="flex flex-wrap items-end gap-3">
        <label class="block">
          <span class="text-xs text-slate-500">نوع گزارش</span>
          <select
            v-model="builder.kind"
            class="mt-1 border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface min-w-[180px]"
            @change="runPreview"
          >
            <option v-for="k in meta?.kinds ?? []" :key="k.value" :value="k.value">{{ k.label }}</option>
          </select>
        </label>

        <label v-if="NEEDS_DAYS.includes(builder.kind)" class="block">
          <span class="text-xs text-slate-500">بازه (روز)</span>
          <input
            v-model="builder.days" type="number" min="1" max="365"
            class="mt-1 border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface w-28 ltr-nums"
            @change="runPreview"
          />
        </label>

        <div class="flex-1"></div>

        <div class="flex items-center gap-1.5">
          <button
            class="text-sm px-3 py-2 rounded-xl bg-slate-100 hover:bg-slate-200"
            @click="runPreview"
          >پیش‌نمایش</button>
          <button
            v-for="f in meta?.formats ?? []" :key="f.value"
            class="text-sm px-3 py-2 rounded-xl bg-slate-100 hover:bg-slate-200"
            :title="f.label"
            @click="downloadNow(f.value)"
          >{{ f.value.toUpperCase() }}</button>
        </div>
      </div>
      <p class="text-[11px] text-slate-400 mt-2">
        خروجی PDF یک صفحه آماده چاپ در تب جدید باز می‌کند؛ از پنجره چاپ مرورگر «ذخیره به PDF» را بزنید
        (این روش، متن فارسی را درست نمایش می‌دهد).
      </p>
    </section>

    <!-- Preview -->
    <section class="bg-surface rounded-card shadow-soft overflow-hidden">
      <div class="flex items-center justify-between gap-2 p-4 border-b border-slate-100">
        <h2 class="font-semibold text-ink">{{ preview?.title ?? "پیش‌نمایش" }}</h2>
        <Badge v-if="preview" tone="neutral">
          {{ faNum(preview.total) }} ردیف
          <span v-if="preview.total > preview.rows.length">
            · نمایش {{ faNum(preview.rows.length) }} ردیف اول
          </span>
        </Badge>
      </div>
      <div v-if="previewing" class="p-8 text-center text-sm text-slate-400">در حال ساخت…</div>
      <div v-else-if="!preview?.rows.length" class="p-8 text-center text-sm text-slate-400">
        داده‌ای برای این گزارش وجود ندارد.
      </div>
      <div v-else class="overflow-x-auto max-h-[420px]">
        <table class="w-full text-sm">
          <thead class="bg-slate-50/70 sticky top-0">
            <tr class="text-slate-400">
              <th
                v-for="c in preview.columns" :key="c.key"
                class="text-right font-medium px-3 py-2 whitespace-nowrap"
              >{{ c.label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, i) in preview.rows" :key="i"
              class="border-t border-slate-50 hover:bg-slate-50/60"
            >
              <td v-for="c in preview.columns" :key="c.key" class="px-3 py-1.5 whitespace-nowrap">
                {{ row[c.key] }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Saved definitions -->
    <DataTable
      :columns="savedColumns"
      :rows="saved"
      :loading="loading"
      empty-title="گزارش ذخیره‌شده‌ای ندارید"
      empty-hint="گزارشی بسازید و با «ذخیره گزارش فعلی» آن را نگه دارید."
      @refresh="load"
    >
      <template #cell-last_run_at="{ row }">
        <span v-if="!row.last_run_at" class="text-slate-300">—</span>
        <span v-else class="text-xs text-slate-500">
          {{ faDateTime(row.last_run_at) }} · {{ faNum(row.last_run_rows) }} ردیف
        </span>
      </template>
      <template #actions="{ row }">
        <div class="flex items-center gap-2 text-xs">
          <button
            class="text-brand-600 hover:underline"
            @click="reportsApi.runSaved(row.id).catch((e) => toast.error(apiError(e)))"
          >اجرا</button>
          <button
            v-if="admin.can('reports.generate')"
            class="text-slate-500 hover:text-ink"
            @click="openSave(row)"
          >ویرایش</button>
          <button
            v-if="admin.can('reports.generate')"
            class="text-red-500 hover:underline"
            @click="removeDefinition(row)"
          >حذف</button>
        </div>
      </template>
    </DataTable>

    <!-- ============ Save definition ============ -->
    <Drawer
      :open="saveOpen"
      :title="editing ? `ویرایش ${editing.name}` : 'ذخیره گزارش'"
      width="sm"
      @close="saveOpen = false"
    >
      <div class="space-y-3">
        <label class="block">
          <span class="text-xs text-slate-500">نام گزارش *</span>
          <input v-model="form.name" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">نوع</span>
          <select v-model="form.kind" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
            <option v-for="k in meta?.kinds ?? []" :key="k.value" :value="k.value">{{ k.label }}</option>
          </select>
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">قالب پیش‌فرض</span>
          <select v-model="form.fmt" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
            <option v-for="f in meta?.formats ?? []" :key="f.value" :value="f.value">{{ f.label }}</option>
          </select>
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">تناوب اجرا</span>
          <select v-model="form.frequency" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
            <option v-for="f in meta?.frequencies ?? []" :key="f.value" :value="f.value">{{ f.label }}</option>
          </select>
        </label>
        <p v-if="form.frequency !== 'manual'" class="text-[11px] text-amber-600 bg-amber-50 rounded-xl px-3 py-2">
          اجرای زمان‌بندی‌شده به کارگر Celery نیاز دارد؛ تا وقتی کارگری فعال نباشد، گزارش را باید دستی اجرا کنید.
        </p>
        <Toggle v-model="form.is_active" label="فعال" />
      </div>
      <template #footer>
        <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="saveOpen = false">انصراف</button>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          :disabled="!form.name"
          @click="saveDefinition"
        >ذخیره</button>
      </template>
    </Drawer>
  </div>
</template>
