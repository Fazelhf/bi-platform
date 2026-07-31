<script setup lang="ts">
/**
 * 15 · Content management — announcements, categories, tags, message
 * templates and editable static pages, in one tabbed screen.
 */
import { computed, onMounted, ref } from "vue";
import { contentApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { confirm, toast } from "@/composables/useUi";
import { apiError } from "@/utils/adminFormat";
import DataTable, { type Column } from "@/components/admin/DataTable.vue";
import Drawer from "@/components/admin/Drawer.vue";
import PageHeader from "@/components/admin/PageHeader.vue";
import Badge from "@/components/admin/Badge.vue";
import Toggle from "@/components/admin/Toggle.vue";
import type {
  AnnouncementRow, ContentCategory, ContentTag,
  ContentTemplateRow, StaticPageRow,
} from "@/types/admin";

const admin = useAdminStore();
const canEdit = computed(() => admin.can("content.manage"));

type Tab = "announcements" | "categories" | "tags" | "templates" | "pages";
const tab = ref<Tab>("announcements");
const TABS: [Tab, string][] = [
  ["announcements", "اطلاعیه‌ها"],
  ["categories", "دسته‌ها"],
  ["tags", "برچسب‌ها"],
  ["templates", "قالب‌ها"],
  ["pages", "صفحات ثابت"],
];

const announcements = ref<AnnouncementRow[]>([]);
const categories = ref<ContentCategory[]>([]);
const tags = ref<ContentTag[]>([]);
const templates = ref<ContentTemplateRow[]>([]);
const pages = ref<StaticPageRow[]>([]);
const loading = ref(true);

async function load() {
  loading.value = true;
  try {
    const [a, c, t, tp, p] = await Promise.all([
      contentApi.announcements.list({ page_size: 200 }),
      contentApi.categories.list({ page_size: 200 }),
      contentApi.tags.list({ page_size: 200 }),
      contentApi.templates.list({ page_size: 200 }),
      contentApi.pages.list({ page_size: 200 }),
    ]);
    announcements.value = a.results;
    categories.value = c.results;
    tags.value = t.results;
    templates.value = tp.results;
    pages.value = p.results;
  } catch (e) {
    toast.error(apiError(e, "بارگذاری محتوا ناموفق بود."));
  } finally {
    loading.value = false;
  }
}
onMounted(load);

// ---------------------------------------------------------------- columns
const announcementColumns: Column[] = [
  { key: "title", label: "عنوان" },
  { key: "level", label: "سطح", type: "slot", align: "center" },
  { key: "is_live", label: "نمایش", type: "slot", align: "center" },
  { key: "starts_at", label: "از", type: "date" },
  { key: "ends_at", label: "تا", type: "date" },
  { key: "tag_names", label: "برچسب‌ها", type: "slot", sortable: false },
  { key: "created_by_name", label: "ایجاد توسط" },
];
const categoryColumns: Column[] = [
  { key: "name", label: "دسته" },
  { key: "slug", label: "شناسه" },
  { key: "parent_name", label: "والد" },
  { key: "description", label: "توضیح" },
  { key: "is_active", label: "فعال", type: "bool", align: "center" },
];
const tagColumns: Column[] = [
  { key: "name", label: "برچسب", type: "slot" },
  { key: "usage", label: "کاربرد", type: "number", align: "center" },
  { key: "created_at", label: "ایجاد", type: "date" },
];
const templateColumns: Column[] = [
  { key: "name", label: "قالب" },
  { key: "kind_label", label: "نوع" },
  { key: "subject", label: "موضوع" },
  { key: "is_active", label: "فعال", type: "bool", align: "center" },
];
const pageColumns: Column[] = [
  { key: "title", label: "صفحه" },
  { key: "slug", label: "نشانی" },
  { key: "is_published", label: "منتشرشده", type: "bool", align: "center" },
  { key: "updated_by_name", label: "آخرین ویرایش" },
  { key: "updated_at", label: "زمان", type: "datetime" },
];

const LEVEL_LABEL: Record<string, string> = {
  info: "اطلاع‌رسانی", warning: "هشدار", danger: "بحرانی",
};
const LEVEL_TONE: Record<string, any> = { info: "info", warning: "warn", danger: "bad" };

// ---------------------------------------------------------------- editor
const editorOpen = ref(false);
const editorKind = ref<Tab>("announcements");
const editingId = ref<number | null>(null);
const form = ref<Record<string, any>>({});

const BLANKS: Record<Tab, () => Record<string, any>> = {
  announcements: () => ({
    title: "", body: "", level: "info", is_published: false,
    starts_at: null, ends_at: null, category: null, tags: [],
  }),
  categories: () => ({ name: "", slug: "", parent: null, description: "", is_active: true }),
  tags: () => ({ name: "", color: "#64748b" }),
  templates: () => ({
    name: "", kind: "notification", subject: "", body: "", variables: [], is_active: true,
  }),
  pages: () => ({ slug: "", title: "", body: "", is_published: false }),
};

const TITLES: Record<Tab, string> = {
  announcements: "اطلاعیه", categories: "دسته", tags: "برچسب",
  templates: "قالب", pages: "صفحه",
};

function openCreate() {
  editorKind.value = tab.value;
  editingId.value = null;
  form.value = BLANKS[tab.value]();
  editorOpen.value = true;
}

function openEdit(row: Record<string, any>) {
  editorKind.value = tab.value;
  editingId.value = row.id;
  const blank = BLANKS[tab.value]();
  form.value = Object.fromEntries(Object.keys(blank).map((k) => [k, row[k] ?? blank[k]]));
  editorOpen.value = true;
}

function resourceFor(kind: Tab) {
  return {
    announcements: contentApi.announcements,
    categories: contentApi.categories,
    tags: contentApi.tags,
    templates: contentApi.templates,
    pages: contentApi.pages,
  }[kind];
}

async function save() {
  try {
    const api = resourceFor(editorKind.value);
    const payload = { ...form.value };
    // Empty datetime-local inputs come back as "" — the API wants null.
    for (const key of ["starts_at", "ends_at"]) {
      if (payload[key] === "") payload[key] = null;
    }
    if (editingId.value == null) await api.create(payload);
    else await api.patch(editingId.value, payload);
    toast.success("ذخیره شد.");
    editorOpen.value = false;
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

async function remove(row: Record<string, any>) {
  if (!(await confirm({
    title: `حذف ${TITLES[tab.value]}`,
    message: `«${row.title || row.name}» حذف شود؟`,
    danger: true,
  }))) return;
  try {
    await resourceFor(tab.value).remove(row.id);
    toast.success("حذف شد.");
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

async function togglePublish(row: AnnouncementRow) {
  try {
    await contentApi.publishAnnouncement(row.id);
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

// ---------------------------------------------------------------- preview
const rendered = ref<{ subject: string; body: string } | null>(null);

async function previewTemplate(row: ContentTemplateRow) {
  try {
    const values = Object.fromEntries(
      (row.variables ?? []).map((v) => [v, `«${v}»`]),
    );
    rendered.value = await contentApi.renderTemplate(row.id, values);
  } catch (e) { toast.error(apiError(e)); }
}
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      title="مدیریت محتوا"
      description="اطلاعیه‌ها، دسته‌ها و برچسب‌ها، قالب‌های پیام و صفحات ثابت سامانه"
    >
      <template #actions>
        <div class="flex bg-surface rounded-xl shadow-soft p-1 overflow-x-auto">
          <button
            v-for="[key, label] in TABS" :key="key"
            class="px-3 py-1.5 text-sm rounded-lg transition whitespace-nowrap"
            :class="tab === key ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
            @click="tab = key"
          >{{ label }}</button>
        </div>
        <button
          v-if="canEdit"
          class="text-sm px-3 py-1.5 rounded-xl bg-brand-600 text-white hover:bg-brand-700 transition"
          @click="openCreate"
        >+ {{ TITLES[tab] }} جدید</button>
      </template>
    </PageHeader>

    <!-- Announcements -->
    <DataTable
      v-if="tab === 'announcements'"
      :columns="announcementColumns"
      :rows="announcements"
      :loading="loading"
      exportable
      empty-title="اطلاعیه‌ای ثبت نشده"
      empty-hint="اطلاعیه‌های منتشرشده در برنامه اصلی به کاربران نمایش داده می‌شوند."
      @refresh="load"
      @export="(f) => contentApi.announcements.export(f)"
    >
      <template #cell-level="{ row }">
        <Badge :tone="LEVEL_TONE[row.level] || 'neutral'">{{ LEVEL_LABEL[row.level] || row.level }}</Badge>
      </template>
      <template #cell-is_live="{ row }">
        <Badge :tone="row.is_live ? 'good' : 'neutral'" dot>
          {{ row.is_live ? "در حال نمایش" : row.is_published ? "خارج از بازه" : "پیش‌نویس" }}
        </Badge>
      </template>
      <template #cell-tag_names="{ row }">
        <span v-if="!row.tag_names.length" class="text-slate-300">—</span>
        <div v-else class="flex flex-wrap gap-1">
          <Badge v-for="t in row.tag_names" :key="t" tone="neutral">{{ t }}</Badge>
        </div>
      </template>
      <template #actions="{ row }">
        <div class="flex items-center gap-2 text-xs">
          <button v-if="canEdit" class="text-brand-600 hover:underline" @click="openEdit(row)">ویرایش</button>
          <button v-if="canEdit" class="text-slate-500 hover:text-ink" @click="togglePublish(row)">
            {{ row.is_published ? "لغو انتشار" : "انتشار" }}
          </button>
          <button v-if="canEdit" class="text-red-500 hover:underline" @click="remove(row)">حذف</button>
        </div>
      </template>
    </DataTable>

    <!-- Categories -->
    <DataTable
      v-else-if="tab === 'categories'"
      :columns="categoryColumns"
      :rows="categories"
      :loading="loading"
      empty-title="دسته‌ای تعریف نشده"
      @refresh="load"
    >
      <template #actions="{ row }">
        <div class="flex items-center gap-2 text-xs">
          <button v-if="canEdit" class="text-brand-600 hover:underline" @click="openEdit(row)">ویرایش</button>
          <button v-if="canEdit" class="text-red-500 hover:underline" @click="remove(row)">حذف</button>
        </div>
      </template>
    </DataTable>

    <!-- Tags -->
    <DataTable
      v-else-if="tab === 'tags'"
      :columns="tagColumns"
      :rows="tags"
      :loading="loading"
      empty-title="برچسبی تعریف نشده"
      @refresh="load"
    >
      <template #cell-name="{ row }">
        <span class="inline-flex items-center gap-2">
          <span class="w-2.5 h-2.5 rounded-full" :style="{ background: row.color || '#94a3b8' }"></span>
          {{ row.name }}
        </span>
      </template>
      <template #actions="{ row }">
        <div class="flex items-center gap-2 text-xs">
          <button v-if="canEdit" class="text-brand-600 hover:underline" @click="openEdit(row)">ویرایش</button>
          <button v-if="canEdit" class="text-red-500 hover:underline" @click="remove(row)">حذف</button>
        </div>
      </template>
    </DataTable>

    <!-- Templates -->
    <DataTable
      v-else-if="tab === 'templates'"
      :columns="templateColumns"
      :rows="templates"
      :loading="loading"
      empty-title="قالبی تعریف نشده"
      empty-hint="قالب‌ها متن آماده برای اعلان‌ها و اطلاعیه‌ها هستند؛ جای متغیرها را با {{نام}} بگذارید."
      @refresh="load"
    >
      <template #actions="{ row }">
        <div class="flex items-center gap-2 text-xs">
          <button class="text-slate-500 hover:text-ink" @click="previewTemplate(row)">پیش‌نمایش</button>
          <button v-if="canEdit" class="text-brand-600 hover:underline" @click="openEdit(row)">ویرایش</button>
          <button v-if="canEdit" class="text-red-500 hover:underline" @click="remove(row)">حذف</button>
        </div>
      </template>
    </DataTable>

    <!-- Pages -->
    <DataTable
      v-else
      :columns="pageColumns"
      :rows="pages"
      :loading="loading"
      empty-title="صفحه‌ای تعریف نشده"
      empty-hint="مثلاً «راهنما» یا «تماس با ما» که داخل سامانه نمایش داده می‌شوند."
      @refresh="load"
    >
      <template #actions="{ row }">
        <div class="flex items-center gap-2 text-xs">
          <button v-if="canEdit" class="text-brand-600 hover:underline" @click="openEdit(row)">ویرایش</button>
          <button v-if="canEdit" class="text-red-500 hover:underline" @click="remove(row)">حذف</button>
        </div>
      </template>
    </DataTable>

    <!-- ============ Editor ============ -->
    <Drawer
      :open="editorOpen"
      :title="`${editingId == null ? 'افزودن' : 'ویرایش'} ${TITLES[editorKind]}`"
      width="lg"
      @close="editorOpen = false"
    >
      <!-- Announcement -->
      <div v-if="editorKind === 'announcements'" class="space-y-3">
        <label class="block">
          <span class="text-xs text-slate-500">عنوان *</span>
          <input v-model="form.title" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">متن</span>
          <textarea v-model="form.body" rows="5" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface"></textarea>
        </label>
        <div class="grid sm:grid-cols-2 gap-3">
          <label class="block">
            <span class="text-xs text-slate-500">سطح</span>
            <select v-model="form.level" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
              <option value="info">اطلاع‌رسانی</option>
              <option value="warning">هشدار</option>
              <option value="danger">بحرانی</option>
            </select>
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">دسته</span>
            <select v-model="form.category" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
              <option :value="null">— بدون دسته</option>
              <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">نمایش از</span>
            <input
              v-model="form.starts_at" type="datetime-local"
              class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums"
            />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">نمایش تا</span>
            <input
              v-model="form.ends_at" type="datetime-local"
              class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums"
            />
          </label>
        </div>
        <div v-if="tags.length">
          <span class="text-xs text-slate-500">برچسب‌ها</span>
          <div class="flex flex-wrap gap-1.5 mt-1">
            <label
              v-for="t in tags" :key="t.id"
              class="flex items-center gap-1.5 border border-slate-200 rounded-xl px-2.5 py-1.5 text-xs cursor-pointer hover:bg-slate-50"
              :class="{ 'bg-brand-50 border-brand-200': form.tags?.includes(t.id) }"
            >
              <input v-model="form.tags" type="checkbox" :value="t.id" class="rounded" />
              {{ t.name }}
            </label>
          </div>
        </div>
        <Toggle v-model="form.is_published" label="منتشر شود" hint="در بازه تاریخی بالا به کاربران نمایش داده می‌شود." />
      </div>

      <!-- Category -->
      <div v-else-if="editorKind === 'categories'" class="space-y-3">
        <label class="block">
          <span class="text-xs text-slate-500">نام *</span>
          <input v-model="form.name" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">شناسه (انگلیسی) *</span>
          <input v-model="form.slug" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">دسته والد</span>
          <select v-model="form.parent" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
            <option :value="null">— بدون والد</option>
            <option
              v-for="c in categories.filter((x) => x.id !== editingId)" :key="c.id" :value="c.id"
            >{{ c.name }}</option>
          </select>
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">توضیح</span>
          <input v-model="form.description" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
        </label>
        <Toggle v-model="form.is_active" label="فعال" />
      </div>

      <!-- Tag -->
      <div v-else-if="editorKind === 'tags'" class="space-y-3">
        <label class="block">
          <span class="text-xs text-slate-500">نام برچسب *</span>
          <input v-model="form.name" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">رنگ</span>
          <input v-model="form.color" type="color" class="mt-1 w-full h-10 border border-slate-200 rounded-xl bg-surface" />
        </label>
      </div>

      <!-- Template -->
      <div v-else-if="editorKind === 'templates'" class="space-y-3">
        <div class="grid sm:grid-cols-2 gap-3">
          <label class="block">
            <span class="text-xs text-slate-500">نام قالب *</span>
            <input v-model="form.name" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">نوع</span>
            <select v-model="form.kind" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
              <option value="notification">اعلان</option>
              <option value="email">ایمیل</option>
              <option value="announcement">اطلاعیه</option>
              <option value="report">گزارش</option>
            </select>
          </label>
        </div>
        <label class="block">
          <span class="text-xs text-slate-500">موضوع</span>
          <input v-model="form.subject" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">متن قالب *</span>
          <textarea
            v-model="form.body" rows="6"
            class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface"
          ></textarea>
        </label>
        <p class="text-[11px] text-slate-400">
          برای جای‌گذاری متغیر از الگوی دو آکولاد استفاده کنید — مثلاً نام کاربر یا نام ماه.
        </p>
        <Toggle v-model="form.is_active" label="فعال" />
      </div>

      <!-- Page -->
      <div v-else class="space-y-3">
        <label class="block">
          <span class="text-xs text-slate-500">عنوان *</span>
          <input v-model="form.title" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">نشانی (انگلیسی) *</span>
          <input v-model="form.slug" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">محتوا</span>
          <textarea
            v-model="form.body" rows="10"
            class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface"
          ></textarea>
        </label>
        <Toggle v-model="form.is_published" label="منتشر شود" />
      </div>

      <template #footer>
        <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="editorOpen = false">انصراف</button>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700"
          @click="save"
        >ذخیره</button>
      </template>
    </Drawer>

    <!-- ============ Template preview ============ -->
    <Drawer
      :open="!!rendered"
      title="پیش‌نمایش قالب"
      subtitle="متغیرها با نام خودشان جایگزین شده‌اند"
      width="sm"
      @close="rendered = null"
    >
      <p v-if="rendered?.subject" class="font-semibold text-ink mb-2">{{ rendered.subject }}</p>
      <p class="text-sm text-slate-600 whitespace-pre-wrap">{{ rendered?.body }}</p>
    </Drawer>
  </div>
</template>
