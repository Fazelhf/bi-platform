<script setup lang="ts">
/**
 * 10 · File management — folders, uploads, versions and storage usage.
 *
 * Files live in the database as data-URLs (the deployment has no writable
 * media directory), so the size cap is enforced client- and server-side.
 */
import { computed, onMounted, ref } from "vue";
import { filesApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { confirm, toast } from "@/composables/useUi";
import { apiError, faNum, formatBytes } from "@/utils/adminFormat";
import DataTable, { type Column } from "@/components/admin/DataTable.vue";
import Drawer from "@/components/admin/Drawer.vue";
import PageHeader from "@/components/admin/PageHeader.vue";
import StatCard from "@/components/admin/StatCard.vue";
import Badge from "@/components/admin/Badge.vue";
import NavIcon from "@/components/NavIcon.vue";
import type { FileRow, FolderRow } from "@/types/admin";

const MAX_BYTES = 4 * 1024 * 1024;

const admin = useAdminStore();

const files = ref<FileRow[]>([]);
const folders = ref<FolderRow[]>([]);
const usage = ref<Awaited<ReturnType<typeof filesApi.usage>> | null>(null);
const loading = ref(true);
const activeFolder = ref<number | "">("");

const columns: Column[] = [
  { key: "name", label: "نام فایل", type: "slot" },
  { key: "folder_path", label: "پوشه" },
  { key: "mime", label: "نوع" },
  { key: "size_bytes", label: "حجم", type: "bytes" },
  { key: "version", label: "نسخه", type: "slot", align: "center" },
  { key: "visibility", label: "دسترسی", type: "slot", align: "center" },
  { key: "uploaded_by_name", label: "آپلود توسط" },
  { key: "created_at", label: "تاریخ", type: "datetime" },
];

const visible = computed(() =>
  activeFolder.value === ""
    ? files.value
    : files.value.filter((f) => f.folder === activeFolder.value),
);

async function load() {
  loading.value = true;
  try {
    const [fileList, folderList, stats] = await Promise.all([
      filesApi.list({ page_size: 300 }),
      filesApi.folders.list({ page_size: 200 }),
      filesApi.usage(),
    ]);
    files.value = fileList.results;
    folders.value = folderList.results;
    usage.value = stats;
  } catch (e) {
    toast.error(apiError(e, "بارگذاری فایل‌ها ناموفق بود."));
  } finally {
    loading.value = false;
  }
}
onMounted(load);

// ---------------------------------------------------------------- upload
const uploadOpen = ref(false);
const uploading = ref(false);
const upload = ref({
  name: "", folder: null as number | null, visibility: "private",
  content: "", mime: "", size: 0,
});

function pickFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  if (file.size > MAX_BYTES) {
    toast.error(`حجم فایل بیش از ${formatBytes(MAX_BYTES)} است.`);
    return;
  }
  upload.value.name = file.name;
  upload.value.mime = file.type || "application/octet-stream";
  upload.value.size = file.size;
  const reader = new FileReader();
  reader.onload = () => (upload.value.content = String(reader.result));
  reader.readAsDataURL(file);
}

async function submitUpload() {
  if (!upload.value.content) return toast.error("ابتدا فایل را انتخاب کنید.");
  uploading.value = true;
  try {
    await filesApi.create({
      name: upload.value.name, folder: upload.value.folder,
      visibility: upload.value.visibility, content: upload.value.content,
      mime: upload.value.mime,
    });
    toast.success("فایل آپلود شد.");
    uploadOpen.value = false;
    upload.value = { name: "", folder: null, visibility: "private", content: "", mime: "", size: 0 };
    await load();
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    uploading.value = false;
  }
}

async function removeFile(file: FileRow) {
  if (!(await confirm({
    title: "حذف فایل",
    message: `«${file.name}» حذف شود؟`,
    danger: true,
  }))) return;
  try {
    await filesApi.remove(file.id);
    toast.success("فایل حذف شد.");
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

// ---------------------------------------------------------------- folders
const folderOpen = ref(false);
const folderForm = ref({ name: "", parent: null as number | null });

async function createFolder() {
  try {
    await filesApi.folders.create(folderForm.value);
    toast.success("پوشه ساخته شد.");
    folderOpen.value = false;
    folderForm.value = { name: "", parent: null };
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

async function removeFolder(folder: FolderRow) {
  if (!(await confirm({ title: "حذف پوشه", message: `«${folder.path}» حذف شود؟`, danger: true }))) return;
  try {
    await filesApi.folders.remove(folder.id);
    toast.success("پوشه حذف شد.");
    await load();
  } catch (e) { toast.error(apiError(e, "پوشه باید خالی باشد.")); }
}

// ---------------------------------------------------------------- versions
const versionsOf = ref<FileRow | null>(null);
const versions = ref<FileRow[]>([]);

async function openVersions(file: FileRow) {
  versionsOf.value = file;
  versions.value = [];
  try {
    versions.value = await filesApi.versions(file.id);
  } catch (e) { toast.error(apiError(e)); }
}
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="مدیریت فایل‌ها" description="آپلود، سازمان‌دهی در پوشه‌ها، نسخه‌ها و پایش فضا">
      <template #actions>
        <button
          v-if="admin.can('files.manage')"
          class="text-sm px-3 py-1.5 rounded-xl bg-slate-100 text-slate-600 hover:bg-slate-200 transition"
          @click="folderOpen = true"
        >+ پوشه</button>
        <button
          v-if="admin.can('files.manage')"
          class="text-sm px-3 py-1.5 rounded-xl bg-brand-600 text-white hover:bg-brand-700 transition"
          @click="uploadOpen = true"
        >+ آپلود فایل</button>
      </template>
    </PageHeader>

    <div v-if="usage" class="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <StatCard label="فایل‌های فعلی" :value="faNum(usage.file_count)" icon="file" tone="brand" />
      <StatCard label="نسخه‌های قدیمی" :value="faNum(usage.version_count)" icon="history" />
      <StatCard label="فضای مصرفی" :value="formatBytes(usage.total_bytes)" icon="database" />
      <StatCard label="پوشه‌ها" :value="faNum(folders.length)" icon="folder" />
    </div>

    <div class="grid lg:grid-cols-4 gap-4">
      <!-- Folder rail -->
      <aside class="bg-surface rounded-card shadow-soft p-3">
        <p class="text-xs text-slate-400 px-2 mb-1.5">پوشه‌ها</p>
        <button
          class="w-full flex items-center gap-2 px-2.5 py-2 rounded-xl text-sm transition text-right"
          :class="activeFolder === '' ? 'bg-brand-50 text-brand-700' : 'text-slate-600 hover:bg-slate-50'"
          @click="activeFolder = ''"
        >
          <NavIcon name="layers" :size="16" />
          <span class="flex-1">همه فایل‌ها</span>
          <span class="text-[11px] text-slate-400">{{ faNum(files.length) }}</span>
        </button>
        <button
          v-for="f in folders" :key="f.id"
          class="w-full flex items-center gap-2 px-2.5 py-2 rounded-xl text-sm transition text-right group"
          :class="activeFolder === f.id ? 'bg-brand-50 text-brand-700' : 'text-slate-600 hover:bg-slate-50'"
          @click="activeFolder = f.id"
        >
          <NavIcon name="folder" :size="16" />
          <span class="flex-1 truncate">{{ f.name }}</span>
          <span class="text-[11px] text-slate-400">{{ faNum(f.file_count) }}</span>
          <span
            v-if="admin.can('files.manage') && !f.file_count"
            class="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-600"
            @click.stop="removeFolder(f)"
          ><NavIcon name="trash" :size="13" /></span>
        </button>

        <div v-if="usage?.by_folder.length" class="mt-4 pt-3 border-t border-slate-100">
          <p class="text-xs text-slate-400 px-2 mb-1.5">مصرف فضا</p>
          <ul class="space-y-1.5 px-2">
            <li v-for="u in usage.by_folder.slice(0, 6)" :key="u.folder" class="text-[11px]">
              <div class="flex justify-between text-slate-500">
                <span class="truncate">{{ u.folder }}</span>
                <span class="ltr-nums shrink-0">{{ formatBytes(u.bytes) }}</span>
              </div>
              <div class="h-1 bg-slate-100 rounded-full mt-0.5 overflow-hidden">
                <div
                  class="h-full bg-brand-500 rounded-full"
                  :style="{ width: `${usage.total_bytes ? Math.max(2, (u.bytes / usage.total_bytes) * 100) : 0}%` }"
                ></div>
              </div>
            </li>
          </ul>
        </div>
      </aside>

      <div class="lg:col-span-3">
        <DataTable
          :columns="columns"
          :rows="visible"
          :loading="loading"
          exportable
          empty-title="فایلی در این پوشه نیست"
          @refresh="load"
          @export="(f) => filesApi.export(f)"
        >
          <template #cell-name="{ row }">
            <div class="flex items-center gap-2 min-w-0">
              <NavIcon name="file" :size="16" class="text-slate-400 shrink-0" />
              <span class="text-ink truncate">{{ row.name }}</span>
            </div>
          </template>
          <template #cell-version="{ row }">
            <button
              v-if="row.version_count > 1"
              class="text-xs text-brand-600 hover:underline"
              @click="openVersions(row)"
            >v{{ faNum(row.version) }} ({{ faNum(row.version_count) }})</button>
            <span v-else class="text-xs text-slate-400">v{{ faNum(row.version) }}</span>
          </template>
          <template #cell-visibility="{ row }">
            <Badge :tone="row.visibility === 'private' ? 'neutral' : 'info'">
              {{ row.visibility === "private" ? "فقط ادمین" : "کاربران سیستم" }}
            </Badge>
          </template>
          <template #actions="{ row }">
            <div class="flex items-center gap-2 text-xs">
              <button class="text-brand-600 hover:underline" @click="filesApi.download(row.id, row.name)">دانلود</button>
              <button
                v-if="admin.can('files.manage')"
                class="text-red-500 hover:underline"
                @click="removeFile(row)"
              >حذف</button>
            </div>
          </template>
        </DataTable>
      </div>
    </div>

    <!-- ============ Upload ============ -->
    <Drawer :open="uploadOpen" title="آپلود فایل" width="sm" :busy="uploading" @close="uploadOpen = false">
      <div class="space-y-3">
        <label class="block border-2 border-dashed border-slate-200 rounded-xl p-5 text-center cursor-pointer hover:border-brand-300 transition">
          <input type="file" class="hidden" @change="pickFile" />
          <NavIcon name="upload" :size="24" class="mx-auto text-slate-300 mb-1" />
          <p class="text-sm text-ink">{{ upload.name || "فایل را انتخاب کنید" }}</p>
          <p class="text-[11px] text-slate-400 mt-0.5">
            {{ upload.size ? formatBytes(upload.size) : `حداکثر ${formatBytes(MAX_BYTES)}` }}
          </p>
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">نام نمایشی</span>
          <input v-model="upload.name" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">پوشه</span>
          <select v-model="upload.folder" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
            <option :value="null">— ریشه</option>
            <option v-for="f in folders" :key="f.id" :value="f.id">{{ f.path }}</option>
          </select>
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">دسترسی</span>
          <select v-model="upload.visibility" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
            <option value="private">فقط ادمین‌ها</option>
            <option value="internal">همه کاربران سیستم</option>
          </select>
        </label>
        <p class="text-[11px] text-slate-400">
          آپلود فایلی هم‌نام در همان پوشه، نسخه قبلی را بایگانی می‌کند (حذف نمی‌شود).
        </p>
      </div>
      <template #footer>
        <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="uploadOpen = false">انصراف</button>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          :disabled="uploading || !upload.content"
          @click="submitUpload"
        >{{ uploading ? "در حال آپلود…" : "آپلود" }}</button>
      </template>
    </Drawer>

    <!-- ============ Folder ============ -->
    <Drawer :open="folderOpen" title="پوشه جدید" width="sm" @close="folderOpen = false">
      <div class="space-y-3">
        <label class="block">
          <span class="text-xs text-slate-500">نام پوشه *</span>
          <input v-model="folderForm.name" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">داخل پوشه</span>
          <select v-model="folderForm.parent" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
            <option :value="null">— ریشه</option>
            <option v-for="f in folders" :key="f.id" :value="f.id">{{ f.path }}</option>
          </select>
        </label>
      </div>
      <template #footer>
        <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="folderOpen = false">انصراف</button>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          :disabled="!folderForm.name"
          @click="createFolder"
        >ساخت</button>
      </template>
    </Drawer>

    <!-- ============ Versions ============ -->
    <Drawer
      :open="!!versionsOf"
      :title="`نسخه‌های ${versionsOf?.name ?? ''}`"
      width="sm"
      @close="versionsOf = null"
    >
      <ul class="space-y-2">
        <li
          v-for="v in versions" :key="v.id"
          class="flex items-center justify-between gap-2 p-2.5 rounded-xl bg-slate-50 text-sm"
        >
          <div class="min-w-0">
            <p class="text-ink">
              نسخه {{ faNum(v.version) }}
              <Badge v-if="v.is_current" tone="good">فعلی</Badge>
            </p>
            <p class="text-[11px] text-slate-400">
              {{ formatBytes(v.size_bytes) }} · {{ v.uploaded_by_name }}
            </p>
          </div>
          <button
            class="text-xs text-brand-600 hover:underline shrink-0"
            @click="filesApi.download(v.id, `${v.name}.v${v.version}`)"
          >دانلود</button>
        </li>
      </ul>
    </Drawer>
  </div>
</template>
