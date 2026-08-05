<script setup lang="ts">
/**
 * 9 · Notification centre — compose a message, see exactly who will receive
 * it before sending, and keep a history of everything that went out.
 */
import { computed, onMounted, ref, watch } from "vue";
import { broadcastApi, contentApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { confirm, toast } from "@/composables/useUi";
import { apiError, faNum } from "@/utils/adminFormat";
import DataTable, { type Column } from "@/components/admin/DataTable.vue";
import Drawer from "@/components/admin/Drawer.vue";
import PageHeader from "@/components/admin/PageHeader.vue";
import Badge from "@/components/admin/Badge.vue";
import Toggle from "@/components/admin/Toggle.vue";
import type { BroadcastRow, ContentTemplateRow } from "@/types/admin";

const admin = useAdminStore();

const rows = ref<BroadcastRow[]>([]);
const loading = ref(true);
const audiences = ref<Awaited<ReturnType<typeof broadcastApi.audiences>> | null>(null);
const templates = ref<ContentTemplateRow[]>([]);

const columns: Column[] = [
  { key: "created_at", label: "زمان", type: "datetime", width: "150px" },
  { key: "title", label: "عنوان" },
  { key: "level", label: "سطح", type: "slot", align: "center" },
  { key: "audience_label", label: "مخاطب" },
  { key: "recipient_count", label: "گیرندگان", type: "number", align: "center" },
  { key: "sent_by_name", label: "ارسال توسط" },
];

const LEVELS = [
  { value: "info", label: "اطلاع‌رسانی", tone: "info" },
  { value: "success", label: "موفقیت", tone: "good" },
  { value: "warning", label: "هشدار", tone: "warn" },
  { value: "danger", label: "بحرانی", tone: "bad" },
];
const LEVEL_TONE = Object.fromEntries(LEVELS.map((l) => [l.value, l.tone]));
const LEVEL_LABEL = Object.fromEntries(LEVELS.map((l) => [l.value, l.label]));

const AUDIENCES = [
  { value: "all", label: "همه کاربران" },
  { value: "role", label: "بر اساس نقش" },
  { value: "department", label: "بر اساس بخش" },
  { value: "team", label: "بر اساس تیم" },
  { value: "users", label: "کاربران منتخب" },
];

async function load() {
  loading.value = true;
  try {
    const [history, options, templateList] = await Promise.all([
      broadcastApi.list({ page_size: 100 }),
      admin.can("notify.send") ? broadcastApi.audiences() : Promise.resolve(null),
      admin.can("content.view")
        ? contentApi.templates.list({ kind: "notification", page_size: 50 })
        : Promise.resolve({ results: [] as ContentTemplateRow[] }),
    ]);
    rows.value = history.results;
    audiences.value = options;
    templates.value = templateList.results as ContentTemplateRow[];
  } catch (e) {
    toast.error(apiError(e, "بارگذاری اعلان‌ها ناموفق بود."));
  } finally {
    loading.value = false;
  }
}
onMounted(load);

// ---------------------------------------------------------------- compose
const composeOpen = ref(false);
const sending = ref(false);
const form = ref({
  title: "", body: "", level: "info", audience: "all",
  audience_value: [] as (string | number)[], send_email: false,
});
const preview = ref<{ count: number; sample: { id: number; name: string }[] } | null>(null);

const options = computed(() => {
  if (!audiences.value) return [];
  switch (form.value.audience) {
    case "role": return audiences.value.roles;
    case "department": return audiences.value.departments;
    case "team": return audiences.value.teams;
    case "users": return audiences.value.users;
    default: return [];
  }
});

watch(() => form.value.audience, () => {
  form.value.audience_value = [];
  preview.value = null;
});

async function runPreview() {
  try {
    preview.value = await broadcastApi.preview(form.value.audience, form.value.audience_value);
  } catch (e) { toast.error(apiError(e)); }
}
watch(() => form.value.audience_value, runPreview, { deep: true });

function openCompose() {
  form.value = {
    title: "", body: "", level: "info", audience: "all",
    audience_value: [], send_email: false,
  };
  preview.value = null;
  composeOpen.value = true;
  runPreview();
}

function applyTemplate(id: number) {
  const template = templates.value.find((t) => t.id === id);
  if (!template) return;
  form.value.title = template.subject || template.name;
  form.value.body = template.body;
}

async function send() {
  if (!(await confirm({
    title: "ارسال اعلان",
    message: `این پیام برای ${faNum(preview.value?.count ?? 0)} کاربر ارسال می‌شود. ادامه؟`,
  }))) return;
  sending.value = true;
  try {
    const created = await broadcastApi.create(form.value);
    toast.success(`اعلان برای ${faNum(created.recipient_count)} کاربر ارسال شد.`);
    composeOpen.value = false;
    await load();
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    sending.value = false;
  }
}

const detail = ref<BroadcastRow | null>(null);
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      title="مرکز اعلان‌ها"
      description="ارسال پیام و اطلاعیه به کاربران، تیم‌ها یا کل سازمان — همراه با تاریخچه کامل"
    >
      <template #actions>
        <button
          v-if="admin.can('notify.send')"
          class="text-sm px-3 py-1.5 rounded-xl bg-brand-600 text-white hover:bg-brand-700 transition"
          @click="openCompose"
        >+ اعلان جدید</button>
      </template>
    </PageHeader>

    <DataTable
      :columns="columns"
      :rows="rows"
      :loading="loading"
      exportable
      empty-title="هنوز اعلانی ارسال نشده"
      empty-hint="پیام‌های ارسالی در زنگ اعلان کاربران نمایش داده می‌شوند."
      @refresh="load"
      @export="(f) => broadcastApi.export(f)"
    >
      <template #cell-level="{ row }">
        <Badge :tone="(LEVEL_TONE[row.level] as any) || 'neutral'">
          {{ LEVEL_LABEL[row.level] || row.level }}
        </Badge>
      </template>
      <template #actions="{ row }">
        <button class="text-xs text-brand-600 hover:underline" @click="detail = row">مشاهده</button>
      </template>
    </DataTable>

    <!-- ============ Compose ============ -->
    <Drawer
      :open="composeOpen"
      title="اعلان جدید"
      subtitle="پیش از ارسال، تعداد و نمونه گیرندگان را ببینید"
      width="lg"
      :busy="sending"
      @close="composeOpen = false"
    >
      <div class="space-y-4">
        <div v-if="templates.length">
          <label class="text-xs text-slate-500">شروع از یک قالب</label>
          <select
            class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface"
            @change="applyTemplate(Number(($event.target as HTMLSelectElement).value))"
          >
            <option value="">— بدون قالب</option>
            <option v-for="t in templates" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </div>

        <label class="block">
          <span class="text-xs text-slate-500">عنوان *</span>
          <input v-model="form.title" required class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">متن پیام *</span>
          <textarea
            v-model="form.body" rows="4" required
            class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface"
          ></textarea>
        </label>

        <div>
          <span class="text-xs text-slate-500">سطح اهمیت</span>
          <div class="flex gap-1.5 mt-1">
            <button
              v-for="l in LEVELS" :key="l.value"
              class="px-3 py-1.5 text-xs rounded-xl border transition"
              :class="form.level === l.value
                ? 'bg-panel text-white border-panel'
                : 'border-slate-200 text-slate-500 hover:bg-slate-50'"
              @click="form.level = l.value"
            >{{ l.label }}</button>
          </div>
        </div>

        <div>
          <span class="text-xs text-slate-500">مخاطبان</span>
          <select
            v-model="form.audience"
            class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface"
          >
            <option v-for="a in AUDIENCES" :key="a.value" :value="a.value">{{ a.label }}</option>
          </select>

          <div v-if="options.length" class="mt-2 flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
            <label
              v-for="o in options" :key="String(o.value)"
              class="flex items-center gap-1.5 border border-slate-200 rounded-xl px-2.5 py-1.5 text-xs cursor-pointer hover:bg-slate-50"
              :class="{ 'bg-brand-50 border-brand-200 text-brand-700': form.audience_value.includes(o.value) }"
            >
              <input v-model="form.audience_value" type="checkbox" :value="o.value" class="rounded" />
              {{ o.label }}
            </label>
          </div>
        </div>

        <Toggle
          v-model="form.send_email"
          label="ارسال نسخه ایمیلی"
          hint="فقط زمانی کار می‌کند که SMTP در تنظیمات سیستم پیکربندی و فعال شده باشد."
        />

        <div v-if="preview" class="bg-slate-50 rounded-xl p-3">
          <p class="text-sm text-ink">
            <span class="font-semibold ltr-nums">{{ faNum(preview.count) }}</span> گیرنده
          </p>
          <p v-if="preview.sample.length" class="text-[11px] text-slate-400 mt-1">
            {{ preview.sample.map((s) => s.name).join("، ") }}{{ preview.count > preview.sample.length ? " و …" : "" }}
          </p>
        </div>
      </div>

      <template #footer>
        <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="composeOpen = false">انصراف</button>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          :disabled="sending || !form.title || !form.body || !preview?.count"
          @click="send"
        >{{ sending ? "در حال ارسال…" : `ارسال به ${faNum(preview?.count ?? 0)} نفر` }}</button>
      </template>
    </Drawer>

    <!-- ============ Detail ============ -->
    <Drawer
      :open="!!detail"
      :title="detail?.title ?? ''"
      :subtitle="detail ? `${detail.audience_label} · ${faNum(detail.recipient_count)} گیرنده` : ''"
      width="sm"
      @close="detail = null"
    >
      <p class="text-sm text-ink whitespace-pre-wrap">{{ detail?.body }}</p>
      <p class="text-xs text-slate-400 mt-3">ارسال توسط {{ detail?.sent_by_name }}</p>
    </Drawer>
  </div>
</template>
