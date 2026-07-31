<script setup lang="ts">
/**
 * 4 · Data management — browse and edit any administrable table, import in
 * bulk (validate first, commit only when every row is clean), export, and
 * recover anything deleted from the recycle bin.
 */
import { computed, onMounted, ref, watch } from "vue";
import { dataApi, recycleApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { confirm, toast } from "@/composables/useUi";
import { apiError, faDateTime, faNum } from "@/utils/adminFormat";
import DataTable, { type Column } from "@/components/admin/DataTable.vue";
import Drawer from "@/components/admin/Drawer.vue";
import PageHeader from "@/components/admin/PageHeader.vue";
import Badge from "@/components/admin/Badge.vue";
import NavIcon from "@/components/NavIcon.vue";
import type { DataField, DataModelInfo, RecycleEntry } from "@/types/admin";

const admin = useAdminStore();

const tab = ref<"tables" | "recycle">("tables");
const tables = ref<DataModelInfo[]>([]);
const recyclePending = ref(0);
const model = ref("");
const fields = ref<DataField[]>([]);
const rows = ref<Record<string, any>[]>([]);
const total = ref(0);
const loading = ref(false);
const query = ref({ search: "", ordering: "", page: 1, page_size: 25 });
// DataTable is a generic component, so InstanceType<> cannot describe it —
// we only need the one method we call.
const table = ref<{ clearSelection: () => void } | null>(null);

const currentTable = computed(() => tables.value.find((t) => t.label === model.value));
const editableFields = computed(() => fields.value.filter((f) => f.editable));

const columns = computed<Column[]>(() =>
  fields.value.slice(0, 9).map((f) => ({
    key: f.name,
    label: f.label,
    type: f.type === "BooleanField" ? "bool"
      : f.type === "DateTimeField" ? "datetime"
      : f.type === "DateField" ? "date"
      : ["IntegerField", "BigIntegerField", "PositiveIntegerField",
         "PositiveSmallIntegerField", "DecimalField", "FloatField"].includes(f.type)
        ? "number"
        : "text",
  })),
);

async function loadOverview() {
  try {
    const data = await dataApi.overview();
    tables.value = data.tables;
    recyclePending.value = data.recycle_pending;
    if (!model.value && tables.value.length) model.value = tables.value[0].label;
  } catch (e) { toast.error(apiError(e)); }
}

async function loadSchema() {
  if (!model.value) return;
  const schema = await dataApi.schema(model.value);
  fields.value = schema.fields;
}

async function loadRows() {
  if (!model.value) return;
  loading.value = true;
  try {
    const data = await dataApi.rows(model.value, query.value);
    rows.value = data.results;
    total.value = data.count;
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    loading.value = false;
  }
}

watch(model, async () => {
  query.value = { search: "", ordering: "", page: 1, page_size: 25 };
  table.value?.clearSelection();
  await loadSchema();
  await loadRows();
});

onMounted(async () => {
  await loadOverview();
  await loadSchema();
  await loadRows();
});

// ---------------------------------------------------------------- record
const recordOpen = ref(false);
const saving = ref(false);
const editingId = ref<number | null>(null);
const form = ref<Record<string, any>>({});

function openCreate() {
  editingId.value = null;
  form.value = Object.fromEntries(
    editableFields.value.map((f) => [f.name, f.type === "BooleanField" ? false : ""]),
  );
  recordOpen.value = true;
}

function openEdit(row: Record<string, any>) {
  editingId.value = row.id;
  form.value = Object.fromEntries(editableFields.value.map((f) => [f.name, row[f.name]]));
  recordOpen.value = true;
}

async function saveRecord() {
  saving.value = true;
  try {
    const values = { ...form.value };
    // Blank optional fields must go as null, not "" — DRF rejects "" on FKs.
    for (const f of editableFields.value) {
      if (values[f.name] === "" && !f.required) values[f.name] = null;
    }
    if (editingId.value == null) await dataApi.create(model.value, values);
    else await dataApi.update(model.value, editingId.value, values);
    toast.success("ذخیره شد.");
    recordOpen.value = false;
    await Promise.all([loadRows(), loadOverview()]);
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    saving.value = false;
  }
}

async function removeRecord(row: Record<string, any>) {
  if (!(await confirm({
    title: "حذف رکورد",
    message: "این رکورد به سطل بازیافت منتقل می‌شود و بعداً قابل بازیابی است.",
    danger: true,
  }))) return;
  try {
    await dataApi.remove(model.value, row.id);
    toast.success("به سطل بازیافت منتقل شد.");
    await Promise.all([loadRows(), loadOverview()]);
  } catch (e) { toast.error(apiError(e)); }
}

async function bulkDelete(ids: number[]) {
  if (!(await confirm({
    title: "حذف گروهی",
    message: `${faNum(ids.length)} رکورد به سطل بازیافت منتقل شود؟`,
    danger: true,
  }))) return;
  try {
    const result = await dataApi.bulkDelete(model.value, ids);
    toast.success(`${faNum(result.deleted)} رکورد منتقل شد.`);
    table.value?.clearSelection();
    await Promise.all([loadRows(), loadOverview()]);
  } catch (e) { toast.error(apiError(e)); }
}

// ---------------------------------------------------------------- import
const importOpen = ref(false);
const importing = ref(false);
const importResult = ref<Awaited<ReturnType<typeof dataApi.import>> | null>(null);
const importFile = ref<string>("");
const importFileName = ref("");

function pickFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  importFileName.value = file.name;
  importResult.value = null;
  const reader = new FileReader();
  reader.onload = () => (importFile.value = String(reader.result));
  reader.readAsDataURL(file);
}

async function runImport(mode: "validate" | "commit") {
  if (!importFile.value) return toast.error("ابتدا فایل را انتخاب کنید.");
  importing.value = true;
  try {
    importResult.value = await dataApi.import(model.value, { file: importFile.value, mode });
    if (mode === "commit") {
      toast.success(`${faNum(importResult.value.valid)} ردیف ثبت شد.`);
      await Promise.all([loadRows(), loadOverview()]);
    }
  } catch (e: any) {
    // A rejected commit still carries the per-row report — show it.
    if (e?.response?.data?.errors) importResult.value = e.response.data;
    toast.error(apiError(e, "ایمپورت ناموفق بود."));
  } finally {
    importing.value = false;
  }
}

function resetImport() {
  importFile.value = "";
  importFileName.value = "";
  importResult.value = null;
}

// ---------------------------------------------------------------- recycle
const bin = ref<RecycleEntry[]>([]);
const binLoading = ref(false);

const binColumns: Column[] = [
  { key: "model_label_fa", label: "نوع" },
  { key: "object_repr", label: "رکورد" },
  { key: "deleted_by_name", label: "حذف توسط" },
  { key: "deleted_at", label: "زمان حذف", type: "datetime" },
  { key: "is_restored", label: "وضعیت", type: "slot", align: "center" },
];

async function loadBin() {
  binLoading.value = true;
  try {
    const data = await recycleApi.list({ page_size: 200 });
    bin.value = data.results;
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    binLoading.value = false;
  }
}
watch(tab, (value) => { if (value === "recycle") loadBin(); });

async function restore(entry: RecycleEntry) {
  try {
    await recycleApi.restore(entry.id);
    toast.success("رکورد بازیابی شد.");
    await Promise.all([loadBin(), loadOverview(), loadRows()]);
  } catch (e) { toast.error(apiError(e)); }
}

async function purgeSelected(ids: number[]) {
  if (!(await confirm({
    title: "پاک‌سازی دائمی",
    message: `${faNum(ids.length)} مورد برای همیشه حذف شود؟ دیگر قابل بازیابی نیست.`,
    danger: true,
  }))) return;
  try {
    const result = await recycleApi.purge({ ids });
    toast.success(`${faNum(result.purged)} مورد پاک شد.`);
    await Promise.all([loadBin(), loadOverview()]);
  } catch (e) { toast.error(apiError(e)); }
}
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      title="مدیریت داده"
      description="مشاهده، ویرایش، ایمپورت گروهی و بازیابی داده‌های پایه و عملیاتی"
    >
      <template #actions>
        <div class="flex bg-surface rounded-xl shadow-soft p-1">
          <button
            class="px-3 py-1.5 text-sm rounded-lg transition"
            :class="tab === 'tables' ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
            @click="tab = 'tables'"
          >جدول‌ها</button>
          <button
            class="px-3 py-1.5 text-sm rounded-lg transition flex items-center gap-1.5"
            :class="tab === 'recycle' ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
            @click="tab = 'recycle'"
          >
            سطل بازیافت
            <span
              v-if="recyclePending"
              class="text-[10px] rounded-full px-1.5"
              :class="tab === 'recycle' ? 'bg-white/20' : 'bg-slate-200 text-slate-600'"
            >{{ faNum(recyclePending) }}</span>
          </button>
        </div>
      </template>
    </PageHeader>

    <!-- ============ Tables ============ -->
    <template v-if="tab === 'tables'">
      <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
        <label class="text-xs text-slate-500 shrink-0">جدول:</label>
        <select v-model="model" class="border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface min-w-[220px]">
          <optgroup
            v-for="app in [...new Set(tables.map((t) => t.app))]" :key="app" :label="app"
          >
            <option
              v-for="t in tables.filter((x) => x.app === app)" :key="t.label" :value="t.label"
            >{{ t.title }} ({{ faNum(t.rows) }})</option>
          </optgroup>
        </select>
        <Badge v-if="currentTable" tone="neutral">{{ currentTable.label }}</Badge>
        <div class="flex-1"></div>
        <button
          v-if="admin.can('data.import')"
          class="text-sm px-3 py-1.5 rounded-xl bg-slate-100 text-slate-600 hover:bg-slate-200 transition flex items-center gap-1.5"
          @click="resetImport(); importOpen = true"
        >
          <NavIcon name="upload" :size="15" /> ایمپورت
        </button>
        <button
          v-if="admin.can('data.edit')"
          class="text-sm px-3 py-1.5 rounded-xl bg-brand-600 text-white hover:bg-brand-700 transition"
          @click="openCreate"
        >+ رکورد جدید</button>
      </div>

      <DataTable
        ref="table"
        :columns="columns"
        :rows="rows"
        :loading="loading"
        :client="false"
        :total="total"
        :page-size="25"
        selectable
        :exportable="admin.can('data.export')"
        :empty-title="`در «${currentTable?.title ?? ''}» رکوردی نیست`"
        @query="(q) => { query = q; loadRows(); }"
        @refresh="loadRows"
        @export="(f) => dataApi.exportTable(model, f)"
      >
        <template #bulk="{ ids }">
          <button
            v-if="admin.can('data.delete')"
            class="text-xs px-2.5 py-1 rounded-lg bg-red-500 text-white hover:bg-red-600"
            @click="bulkDelete(ids)"
          >انتقال به سطل بازیافت</button>
        </template>
        <template #actions="{ row }">
          <div class="flex items-center gap-2 text-xs">
            <button v-if="admin.can('data.edit')" class="text-brand-600 hover:underline" @click="openEdit(row)">ویرایش</button>
            <button v-if="admin.can('data.delete')" class="text-red-500 hover:underline" @click="removeRecord(row)">حذف</button>
          </div>
        </template>
      </DataTable>
    </template>

    <!-- ============ Recycle bin ============ -->
    <DataTable
      v-else
      :columns="binColumns"
      :rows="bin"
      :loading="binLoading"
      selectable
      exportable
      empty-title="سطل بازیافت خالی است"
      empty-hint="هر رکوردی که از این پنل حذف شود ابتدا به اینجا می‌آید."
      @refresh="loadBin"
      @export="(f) => recycleApi.export(f)"
    >
      <template #bulk="{ ids }">
        <button
          v-if="admin.can('data.delete')"
          class="text-xs px-2.5 py-1 rounded-lg bg-red-500 text-white hover:bg-red-600"
          @click="purgeSelected(ids)"
        >پاک‌سازی دائمی</button>
      </template>
      <template #cell-is_restored="{ row }">
        <Badge :tone="row.is_restored ? 'good' : 'warn'" dot>
          {{ row.is_restored ? "بازیابی‌شده" : "در سطل" }}
        </Badge>
      </template>
      <template #actions="{ row }">
        <button
          v-if="!row.is_restored && admin.can('data.restore')"
          class="text-xs text-accent-600 hover:underline"
          @click="restore(row)"
        >بازیابی</button>
        <span v-else-if="row.is_restored" class="text-xs text-slate-400">
          {{ faDateTime(row.restored_at) }}
        </span>
      </template>
    </DataTable>

    <!-- ============ Record editor ============ -->
    <Drawer
      :open="recordOpen"
      :title="editingId == null ? `رکورد جدید — ${currentTable?.title}` : `ویرایش رکورد #${editingId}`"
      :subtitle="model"
      :busy="saving"
      @close="recordOpen = false"
    >
      <form class="grid sm:grid-cols-2 gap-3" @submit.prevent="saveRecord">
        <label v-for="f in editableFields" :key="f.name" class="block">
          <span class="text-xs text-slate-500">
            {{ f.label }}<span v-if="f.required" class="text-red-500"> *</span>
          </span>
          <select
            v-if="f.choices"
            v-model="form[f.name]"
            class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface"
          >
            <option v-for="c in f.choices" :key="String(c.value)" :value="c.value">{{ c.label }}</option>
          </select>
          <label v-else-if="f.type === 'BooleanField'" class="mt-1 flex items-center gap-2 text-sm">
            <input v-model="form[f.name]" type="checkbox" class="rounded" /> بله
          </label>
          <input
            v-else
            v-model="form[f.name]"
            :type="['IntegerField', 'BigIntegerField', 'PositiveIntegerField',
                    'PositiveSmallIntegerField', 'DecimalField', 'FloatField', 'FK'].includes(f.type)
              ? 'number' : 'text'"
            step="any"
            :required="f.required"
            :placeholder="f.type === 'FK' ? `شناسه ${f.related}` : ''"
            class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface"
          />
        </label>
      </form>

      <template #footer>
        <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="recordOpen = false">انصراف</button>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          :disabled="saving"
          @click="saveRecord"
        >ذخیره</button>
      </template>
    </Drawer>

    <!-- ============ Import ============ -->
    <Drawer
      :open="importOpen"
      :title="`ایمپورت — ${currentTable?.title ?? ''}`"
      subtitle="ابتدا اعتبارسنجی، سپس ثبت"
      width="lg"
      :busy="importing"
      @close="importOpen = false"
    >
      <div class="space-y-4">
        <ol class="text-sm text-slate-500 space-y-1 bg-slate-50 rounded-xl p-3">
          <li>۱. الگوی اکسل را بگیرید تا نام ستون‌ها دقیقاً درست باشد.</li>
          <li>۲. فایل پرشده را انتخاب کنید و «اعتبارسنجی» بزنید — چیزی ذخیره نمی‌شود.</li>
          <li>۳. اگر هیچ خطایی نبود، «ثبت نهایی» را بزنید. ثبت یا کامل انجام می‌شود یا اصلاً.</li>
        </ol>

        <button
          class="text-sm px-3 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 flex items-center gap-2"
          @click="dataApi.importTemplate(model)"
        >
          <NavIcon name="download" :size="15" /> دریافت الگوی اکسل
        </button>

        <label class="block border-2 border-dashed border-slate-200 rounded-xl p-5 text-center cursor-pointer hover:border-brand-300 transition">
          <input type="file" accept=".xlsx,.xls,.csv" class="hidden" @change="pickFile" />
          <NavIcon name="upload" :size="24" class="mx-auto text-slate-300 mb-1" />
          <p class="text-sm text-ink">{{ importFileName || "فایل xlsx یا csv را انتخاب کنید" }}</p>
          <p class="text-[11px] text-slate-400 mt-0.5">حداکثر ۵۰۰۰ ردیف در هر ایمپورت</p>
        </label>

        <div v-if="importResult" class="space-y-3">
          <div class="grid grid-cols-4 gap-2 text-center">
            <div class="bg-slate-50 rounded-xl p-2.5">
              <p class="text-lg font-bold text-ink ltr-nums">{{ faNum(importResult.total) }}</p>
              <p class="text-[11px] text-slate-400">کل ردیف</p>
            </div>
            <div class="bg-accent-50 rounded-xl p-2.5">
              <p class="text-lg font-bold text-accent-600 ltr-nums">{{ faNum(importResult.valid) }}</p>
              <p class="text-[11px] text-slate-400">معتبر</p>
            </div>
            <div class="rounded-xl p-2.5" :class="importResult.invalid ? 'bg-red-50' : 'bg-slate-50'">
              <p class="text-lg font-bold ltr-nums" :class="importResult.invalid ? 'text-red-600' : 'text-ink'">
                {{ faNum(importResult.invalid) }}
              </p>
              <p class="text-[11px] text-slate-400">خطادار</p>
            </div>
            <div class="bg-brand-50 rounded-xl p-2.5">
              <p class="text-lg font-bold text-brand-700 ltr-nums">
                {{ faNum(importResult.create) }}+{{ faNum(importResult.update) }}
              </p>
              <p class="text-[11px] text-slate-400">جدید + به‌روزرسانی</p>
            </div>
          </div>

          <div v-if="importResult.errors?.length" class="border border-red-100 rounded-xl overflow-hidden">
            <p class="bg-red-50 text-red-700 text-xs px-3 py-2 font-medium">
              ردیف‌های خطادار (تا ۲۰۰ مورد نمایش داده می‌شود)
            </p>
            <ul class="max-h-56 overflow-y-auto divide-y divide-slate-50">
              <li v-for="err in importResult.errors" :key="err.row" class="px-3 py-2 text-xs">
                <span class="font-medium text-ink">ردیف {{ faNum(err.row) }}:</span>
                <span class="text-red-600 mr-1">{{ JSON.stringify(err.errors) }}</span>
              </li>
            </ul>
          </div>
          <p
            v-else-if="!importResult.committed"
            class="text-sm text-accent-600 bg-accent-50 rounded-xl px-3 py-2"
          >همه ردیف‌ها معتبرند — می‌توانید ثبت نهایی را بزنید.</p>
          <p v-else class="text-sm text-accent-600 bg-accent-50 rounded-xl px-3 py-2">
            ایمپورت با موفقیت ثبت شد.
          </p>
        </div>
      </div>

      <template #footer>
        <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="importOpen = false">بستن</button>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-slate-100 hover:bg-slate-200 disabled:opacity-50"
          :disabled="!importFile || importing"
          @click="runImport('validate')"
        >اعتبارسنجی</button>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          :disabled="!importResult || !!importResult.invalid || importing || importResult.committed"
          @click="runImport('commit')"
        >ثبت نهایی</button>
      </template>
    </Drawer>
  </div>
</template>
