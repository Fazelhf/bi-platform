<script setup lang="ts">
/** 5 · System management — settings by category, feature flags, maintenance. */
import { computed, onMounted, ref } from "vue";
import { systemApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { confirm, toast } from "@/composables/useUi";
import { apiError, faDateTime } from "@/utils/adminFormat";
import PageHeader from "@/components/admin/PageHeader.vue";
import Toggle from "@/components/admin/Toggle.vue";
import Badge from "@/components/admin/Badge.vue";
import NavIcon from "@/components/NavIcon.vue";
import type { FeatureFlag, SettingGroup } from "@/types/admin";

const admin = useAdminStore();

const groups = ref<SettingGroup[]>([]);
const flags = ref<FeatureFlag[]>([]);
const maintenance = ref({ enabled: false, message: "" });
const loading = ref(true);
const saving = ref(false);
const activeGroup = ref("");

/** Local edits, keyed by setting key. Saved per tab. */
const draft = ref<Record<string, any>>({});

const current = computed(() => groups.value.find((g) => g.key === activeGroup.value));
const dirty = computed(() => {
  if (!current.value) return false;
  return current.value.settings.some((s) => {
    const value = draft.value[s.key];
    return value !== undefined && String(value) !== String(settingValue(s.key));
  });
});

function settingValue(key: string) {
  for (const group of groups.value) {
    const found = group.settings.find((s) => s.key === key);
    if (found) {
      return found.value_type === "bool"
        ? ["true", "1", "yes", "on"].includes(String(found.value).toLowerCase())
        : found.value;
    }
  }
  return "";
}

async function load() {
  loading.value = true;
  try {
    const [settingGroups, flagList, maint] = await Promise.all([
      systemApi.grouped(),
      systemApi.flags.list({ page_size: 100 }),
      systemApi.maintenance(),
    ]);
    groups.value = settingGroups;
    flags.value = flagList.results;
    maintenance.value = maint;
    if (!activeGroup.value && groups.value.length) activeGroup.value = groups.value[0].key;
    resetDraft();
  } catch (e) {
    toast.error(apiError(e, "بارگذاری تنظیمات ناموفق بود."));
  } finally {
    loading.value = false;
  }
}

function resetDraft() {
  const next: Record<string, any> = {};
  for (const group of groups.value) {
    for (const setting of group.settings) next[setting.key] = settingValue(setting.key);
  }
  draft.value = next;
}

onMounted(load);

async function saveGroup() {
  if (!current.value) return;
  saving.value = true;
  try {
    const values: Record<string, any> = {};
    for (const setting of current.value.settings) {
      const value = draft.value[setting.key];
      // Never post the mask back — the server would treat it as a new secret.
      if (setting.is_secret && value === "••••••••") continue;
      values[setting.key] = setting.value_type === "bool" ? (value ? "true" : "false") : value;
    }
    await systemApi.bulkSet(values);
    toast.success("تنظیمات ذخیره شد.");
    await load();
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    saving.value = false;
  }
}

async function toggleFlag(flag: FeatureFlag) {
  try {
    const updated = await systemApi.toggleFlag(flag.id);
    Object.assign(flag, updated);
    toast.success(`${flag.name_fa} ${updated.is_enabled ? "روشن" : "خاموش"} شد.`);
  } catch (e) { toast.error(apiError(e)); }
}

async function toggleMaintenance() {
  const turningOn = !maintenance.value.enabled;
  if (turningOn && !(await confirm({
    title: "فعال کردن حالت تعمیرات",
    message: "همه کاربران به‌جز ادمین‌ها تا خاموش کردن این حالت به سامانه دسترسی نخواهند داشت.",
    danger: true,
  }))) return;
  try {
    maintenance.value = await systemApi.setMaintenance(turningOn, maintenance.value.message);
    admin.maintenance = maintenance.value.enabled;
    toast.success(turningOn ? "حالت تعمیرات فعال شد." : "سامانه به حالت عادی بازگشت.");
  } catch (e) { toast.error(apiError(e)); }
}

async function saveMaintenanceMessage() {
  try {
    maintenance.value = await systemApi.setMaintenance(
      maintenance.value.enabled, maintenance.value.message,
    );
    toast.success("پیام ذخیره شد.");
  } catch (e) { toast.error(apiError(e)); }
}

const canEdit = computed(() => admin.can("system.manage"));
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="تنظیمات سیستم" description="پیکربندی سراسری، فیچرفلگ‌ها و حالت تعمیرات" />

    <div v-if="loading" class="text-center text-slate-400 py-16 text-sm">در حال بارگذاری…</div>

    <template v-else>
      <!-- Maintenance -->
      <section
        class="rounded-card shadow-soft p-4 border-2 transition"
        :class="maintenance.enabled ? 'bg-amber-50 border-amber-300' : 'bg-surface border-transparent'"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="flex items-start gap-3 min-w-0">
            <span
              class="w-10 h-10 rounded-2xl grid place-items-center shrink-0"
              :class="maintenance.enabled ? 'bg-amber-200 text-amber-800' : 'bg-slate-100 text-slate-500'"
            ><NavIcon name="alert" :size="20" /></span>
            <div class="min-w-0">
              <h2 class="font-semibold text-ink">حالت تعمیرات</h2>
              <p class="text-sm text-slate-500 mt-0.5">
                وقتی روشن باشد، فقط ادمین‌ها می‌توانند از سامانه استفاده کنند؛ بقیه پیام زیر را می‌بینند.
              </p>
            </div>
          </div>
          <Toggle
            :model-value="maintenance.enabled"
            :disabled="!admin.can('system.maintenance')"
            @update:model-value="toggleMaintenance"
          />
        </div>
        <div v-if="admin.can('system.maintenance')" class="mt-3 flex flex-wrap gap-2">
          <input
            v-model="maintenance.message"
            placeholder="پیامی که کاربران می‌بینند…"
            class="flex-1 min-w-[220px] border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface"
          />
          <button
            class="px-3 py-2 text-sm rounded-xl bg-slate-100 hover:bg-slate-200"
            @click="saveMaintenanceMessage"
          >ذخیره پیام</button>
        </div>
      </section>

      <div class="grid lg:grid-cols-3 gap-4">
        <!-- Settings -->
        <section class="lg:col-span-2 bg-surface rounded-card shadow-soft overflow-hidden">
          <div class="flex gap-1 p-2 border-b border-slate-100 overflow-x-auto">
            <button
              v-for="g in groups" :key="g.key"
              class="px-3 py-1.5 text-sm rounded-lg whitespace-nowrap transition shrink-0"
              :class="activeGroup === g.key ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
              @click="activeGroup = g.key"
            >{{ g.label }}</button>
          </div>

          <div v-if="current" class="p-4 space-y-3">
            <div
              v-for="s in current.settings" :key="s.key"
              class="pb-3 border-b border-slate-50 last:border-0"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0 flex-1">
                  <label class="text-sm text-ink block">{{ s.label_fa }}</label>
                  <p v-if="s.description" class="text-[11px] text-slate-400 mt-0.5">{{ s.description }}</p>
                  <p class="text-[10px] text-slate-300 ltr-nums mt-0.5">{{ s.key }}</p>
                </div>

                <div class="w-56 shrink-0">
                  <Toggle
                    v-if="s.value_type === 'bool'"
                    v-model="draft[s.key]"
                    :disabled="!canEdit"
                  />
                  <textarea
                    v-else-if="s.value_type === 'json'"
                    v-model="draft[s.key]"
                    :disabled="!canEdit"
                    rows="3"
                    class="w-full border border-slate-200 rounded-xl px-3 py-2 text-xs bg-surface ltr-nums disabled:opacity-60"
                  ></textarea>
                  <input
                    v-else
                    v-model="draft[s.key]"
                    :type="s.is_secret ? 'password' : s.value_type === 'int' ? 'number' : 'text'"
                    :disabled="!canEdit"
                    class="w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface disabled:opacity-60"
                    :class="{ 'ltr-nums': s.value_type === 'int' || s.is_secret }"
                  />
                </div>
              </div>
              <p v-if="s.updated_by_name" class="text-[10px] text-slate-300 mt-1">
                آخرین تغییر: {{ s.updated_by_name }} · {{ faDateTime(s.updated_at) }}
              </p>
            </div>
          </div>

          <div
            v-if="canEdit && current"
            class="p-3 border-t border-slate-100 flex items-center justify-end gap-2"
          >
            <button class="px-3 py-1.5 text-sm rounded-xl hover:bg-slate-100" @click="resetDraft">بازگردانی</button>
            <button
              class="px-4 py-1.5 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
              :disabled="saving || !dirty"
              @click="saveGroup"
            >{{ saving ? "در حال ذخیره…" : "ذخیره این بخش" }}</button>
          </div>
        </section>

        <!-- Feature flags -->
        <section class="bg-surface rounded-card shadow-soft p-4">
          <h2 class="font-semibold text-ink mb-1">فیچرفلگ‌ها</h2>
          <p class="text-xs text-slate-400 mb-3">قابلیت‌های سامانه را بدون انتشار نسخه جدید روشن/خاموش کنید.</p>
          <ul class="space-y-3">
            <li v-for="f in flags" :key="f.id" class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-sm text-ink">{{ f.name_fa }}</p>
                <p v-if="f.description" class="text-[11px] text-slate-400">{{ f.description }}</p>
                <Badge v-if="f.roles?.length" tone="neutral">
                  فقط: {{ f.roles.join("، ") }}
                </Badge>
              </div>
              <Toggle
                :model-value="f.is_enabled"
                :disabled="!canEdit"
                @update:model-value="toggleFlag(f)"
              />
            </li>
          </ul>
        </section>
      </div>
    </template>
  </div>
</template>
