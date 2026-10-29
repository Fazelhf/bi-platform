<script setup lang="ts">
import { computed, ref } from "vue";
import { crmApi, type MergeExcelResult } from "@/api/crm";
import { num } from "@/utils/format";

/** ادغام از اکسل — upload the marked customers export, see the groups, confirm.
 *  The same file is sent twice: once to preview, once to merge. */
const emit = defineEmits<{ close: []; merged: [] }>();

const file = ref<File | null>(null);
const busy = ref(false);
const error = ref("");
const res = ref<MergeExcelResult | null>(null);

const bad = computed(() => res.value?.groups.filter((g) => g.error) ?? []);
const good = computed(() => res.value?.groups.filter((g) => !g.error) ?? []);

async function send(commit: boolean) {
  if (!file.value) return;
  busy.value = true;
  error.value = "";
  try {
    res.value = await crmApi.mergeExcel(file.value, commit);
    if (commit) emit("merged");
  } catch (e: any) {
    res.value = null;
    error.value = e?.response?.data?.detail ?? "فایل خوانده نشد.";
  } finally {
    busy.value = false;
  }
}

function pick(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0] ?? null;
  res.value = null;
  if (file.value) send(false);
}
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4 text-sm space-y-3">
    <div class="flex items-start gap-2">
      <div class="flex-1 space-y-1">
        <p class="font-semibold text-ink">ادغام از اکسل</p>
        <p class="text-xs text-slate-500 leading-6">
          خروجی اکسل مشتریان را بگیرید. در ستون «ادغام» کنار ردیف‌هایی که یک مشتری‌اند یک عدد مشترک بنویسید
          (مثلاً هر دو ۱، جفت بعدی هر دو ۲). اگر می‌خواهید خودتان ماندنی را تعیین کنید، کنار آن ستاره بگذارید (۱*)؛
          وگرنه ردیفی که فاکتور و معامله‌ی بیشتری دارد می‌ماند. فایل را این‌جا بفرستید؛ اول فقط پیش‌نمایش می‌بینید.
        </p>
      </div>
      <button class="text-slate-400 px-2" aria-label="بستن" @click="emit('close')">✕</button>
    </div>

    <input type="file" accept=".xlsx" class="text-xs" :disabled="busy" @change="pick" />
    <p v-if="busy" class="text-xs text-slate-400">در حال خواندن…</p>
    <p v-if="error" class="text-red-600 text-xs">{{ error }}</p>

    <template v-if="res">
      <p v-if="res.committed" class="text-emerald-600">{{ num(res.merged) }} مشتری ادغام شد.</p>
      <p v-else class="text-ink">
        {{ num(res.ready) }} گروه آماده‌ی ادغام ({{ num(res.rows) }} ردیف در ردیف ماندنی ادغام می‌شود).
      </p>

      <ul v-if="good.length" class="max-h-72 overflow-auto divide-y divide-slate-100 text-xs">
        <li v-for="g in good" :key="g.mark" class="py-1.5 flex flex-wrap gap-x-2">
          <span class="text-slate-400 w-8">{{ g.mark }}</span>
          <span class="text-emerald-700">می‌ماند: {{ g.keep?.name_fa }} <span class="text-slate-400">({{ g.keep?.code }})</span></span>
          <span class="text-slate-500">
            ← {{ g.absorb.map((a) => `${a.name_fa} (${a.code})`).join("، ") }}
          </span>
        </li>
      </ul>

      <ul v-if="bad.length || res.problems.length" class="space-y-0.5 text-xs text-red-600">
        <li v-for="g in bad" :key="`b-${g.mark}`">
          علامت {{ g.mark }}<span v-if="g.names?.length"> ({{ g.names.join("، ") }})</span>: {{ g.error }}
        </li>
        <li v-for="(p, i) in res.problems" :key="`p-${i}`">{{ p }}</li>
      </ul>

      <button
        v-if="!res.committed && res.ready"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm disabled:opacity-50"
        :disabled="busy"
        @click="send(true)"
      >ادغام {{ num(res.ready) }} گروه</button>
    </template>
  </div>
</template>
