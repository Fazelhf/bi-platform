<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { auditApi } from "@/api/platform";
import type { AuditEntry } from "@/types";

const rows = ref<AuditEntry[]>([]);
const loading = ref(true);
const actionFilter = ref("");

const ACTION_FA: Record<string, string> = {
  create: "ایجاد", update: "ویرایش", delete: "حذف",
  submit: "ارسال", approve: "تایید", reject: "رد",
  revision: "ارسال برای اصلاح", import: "ایمپورت", formula: "تغییر فرمول",
};
const ACTION_COLOR: Record<string, string> = {
  create: "text-sky-600", update: "text-amber-600", delete: "text-red-600",
  submit: "text-indigo-600", approve: "text-green-600", reject: "text-red-500",
  revision: "text-amber-500", formula: "text-purple-600", import: "text-slate-600",
};

async function load() {
  loading.value = true;
  try {
    rows.value = await auditApi.list(
      actionFilter.value ? { action: actionFilter.value } : {},
    );
  } finally {
    loading.value = false;
  }
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString("fa-IR");
}

onMounted(load);
watch(actionFilter, load);
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-slate-800">تاریخچه تغییرات (Audit Log)</h1>
      <select v-model="actionFilter" class="border border-slate-300 rounded-lg px-3 py-1.5 bg-white text-sm">
        <option value="">همه اقدامات</option>
        <option v-for="(label, key) in ACTION_FA" :key="key" :value="key">{{ label }}</option>
      </select>
    </div>

    <div v-if="loading" class="text-slate-500">در حال بارگذاری…</div>

    <div v-else class="bg-white rounded-xl shadow-sm border border-slate-200 divide-y divide-slate-50">
      <div v-if="!rows.length" class="p-6 text-center text-slate-400 text-sm">رکوردی یافت نشد.</div>
      <div v-for="e in rows" :key="e.id" class="p-4 text-sm">
        <div class="flex items-center justify-between">
          <div>
            <span class="font-medium">{{ e.display_name || e.username || "سیستم" }}</span>
            <span class="mx-1 font-semibold" :class="ACTION_COLOR[e.action]">
              {{ ACTION_FA[e.action] ?? e.action }}
            </span>
            <span class="text-slate-600">{{ e.object_repr }}</span>
            <span class="text-xs text-slate-400 ltr-nums mr-2">({{ e.model_label }}#{{ e.object_id }})</span>
          </div>
          <span class="text-xs text-slate-400 whitespace-nowrap">{{ fmtTime(e.created_at) }}</span>
        </div>
        <div v-if="Object.keys(e.changes || {}).length" class="mt-2 bg-slate-50 rounded-lg p-2 space-y-1">
          <div v-for="(c, field) in e.changes" :key="field" class="text-xs flex flex-wrap gap-1 items-center">
            <code class="bg-white rounded px-1.5 py-0.5 border border-slate-200">{{ field }}</code>
            <span class="text-red-500 line-through ltr-nums">{{ c.before ?? "—" }}</span>
            <span class="text-slate-400">←</span>
            <span class="text-green-600 ltr-nums">{{ c.after ?? "—" }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
