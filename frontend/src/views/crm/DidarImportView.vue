<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { crmApi, type DidarImportResult, type DidarImportRow } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num } from "@/utils/format";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import NavIcon from "@/components/NavIcon.vue";

/**
 * ورود از دیدار — the relationship history, not the sales.
 *
 * دیدار's exports go in together, as many as there are: each file says what
 * it holds (its `_type` column), so their names do not matter and the order
 * they are applied in is worked out on the server. Like ورود از آرپا, picking
 * files runs a preview first, and the same files a second time are reported
 * as already read. No invoice comes from here — sales are آرپا's.
 */
const crm = useCrmStore();

const files = ref<File[]>([]);
const result = ref<DidarImportResult | null>(null);
const busy = ref<"" | "preview" | "commit">("");
const error = ref("");
const dragging = ref(false);
const input = ref<HTMLInputElement | null>(null);

function add(list: FileList | null | undefined) {
  if (!list?.length) return;
  const byName = new Map(files.value.map((f) => [f.name, f]));
  for (const f of Array.from(list)) byName.set(f.name, f);
  files.value = [...byName.values()];
  if (input.value) input.value.value = "";
  runPreview();
}

function remove(name: string) {
  files.value = files.value.filter((f) => f.name !== name);
  if (files.value.length) runPreview();
  else result.value = null;
}

async function runPreview() {
  busy.value = "preview";
  error.value = "";
  result.value = null;
  try {
    result.value = await crmApi.didarImport(files.value, false);
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? "فایل‌ها خوانده نشد.";
  } finally {
    busy.value = "";
  }
}

async function commit() {
  busy.value = "commit";
  error.value = "";
  try {
    result.value = await crmApi.didarImport(files.value, true);
    crm.bump();
    await loadHistory();
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? "ثبت انجام نشد.";
  } finally {
    busy.value = "";
  }
}

function reset() {
  files.value = [];
  result.value = null;
  error.value = "";
}

/** What each chosen file turned out to hold, by name. */
const detected = computed(() => {
  const m = new Map<string, string>();
  for (const f of result.value?.files ?? []) {
    m.set(f.file, f.sheets.map((s) => `${s.label} ${num(s.rows)}`).join(" + "));
  }
  return m;
});

const skippedTotal = (s: Record<string, number>) => Object.values(s).reduce((a, b) => a + b, 0);

const history = ref<DidarImportRow[]>([]);
const loadingHistory = ref(true);
async function loadHistory() {
  try {
    history.value = (await crmApi.didarImports()).imports;
  } finally {
    loadingHistory.value = false;
  }
}
onMounted(loadHistory);

function jdatetime(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" }) : "—";
}

const card = "bg-surface rounded-card shadow-soft p-4 min-w-0";
</script>

<template>
  <div class="space-y-4">
    <p class="text-xs text-slate-500 px-1 leading-6">
      اشخاص، شرکت‌ها، <b class="text-slate-600">معامله‌های جاری و ناموفق</b>، فعالیت‌ها، یادداشت‌ها و کارت‌ها از دیدار وارد می‌شوند.
      <b class="text-slate-600">فاکتور و معامله‌ی موفق از دیدار خوانده نمی‌شود</b> — هر فاکتور آرپا خودش یک معامله‌ی موفق است.
    </p>

    <div :class="card">
      <div
        class="border-2 border-dashed rounded-2xl px-6 py-8 text-center transition cursor-pointer"
        :class="dragging ? 'border-sky-400 bg-sky-50' : 'border-slate-200 hover:border-slate-300'"
        @click="input?.click()"
        @dragover.prevent="dragging = true"
        @dragleave="dragging = false"
        @drop.prevent="dragging = false; add($event.dataTransfer?.files)"
      >
        <input ref="input" type="file" accept=".xlsx" multiple class="hidden" @change="add(($event.target as HTMLInputElement).files)" />
        <span class="w-12 h-12 rounded-2xl bg-slate-100 text-slate-500 grid place-items-center mx-auto">
          <NavIcon name="upload" :size="22" />
        </span>
        <p class="mt-3 text-ink font-medium">خروجی‌های اکسل دیدار را اینجا بکشید — چند فایل با هم</p>
        <p class="text-xs text-slate-400 mt-1">اسم فایل مهم نیست؛ نوع هر فایل از محتوایش تشخیص داده می‌شود</p>
      </div>

      <ul v-if="files.length" class="mt-4 divide-y divide-slate-100 text-sm">
        <li v-for="f in files" :key="f.name" class="flex items-center gap-3 py-2">
          <NavIcon name="file" :size="16" class="text-slate-400 shrink-0" />
          <span class="text-ink truncate" dir="auto">{{ f.name }}</span>
          <span class="text-xs text-slate-400 truncate">{{ detected.get(f.name) ?? (busy ? "…" : "") }}</span>
          <span class="flex-1"></span>
          <button class="text-slate-400 hover:text-red-500 text-xs" :disabled="!!busy" @click="remove(f.name)">حذف</button>
        </li>
      </ul>
    </div>

    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3">{{ error }}</p>

    <div v-if="busy" :class="card" class="flex items-center gap-3 text-sm text-slate-500">
      <span class="w-4 h-4 rounded-full border-2 border-slate-300 border-t-slate-600 animate-spin"></span>
      {{ busy === "preview" ? "در حال خواندن و مقایسه با CRM… (ممکن است نیم دقیقه طول بکشد)" : "در حال ثبت…" }}
    </div>

    <div v-if="result && !busy" :class="card" class="space-y-4">
      <div v-if="result.nothing_new" class="flex items-start gap-3 bg-sky-50 text-sky-800 rounded-xl px-4 py-3 text-sm">
        <NavIcon name="check" :size="20" />
        <div>
          <p class="font-semibold">همه‌ی ردیف‌های این فایل‌ها قبلاً خوانده شده‌اند؛ چیز تازه‌ای برای ثبت نیست.</p>
          <p v-if="result.previous" class="text-xs">همین فایل‌ها {{ jdatetime(result.previous.at) }} وارد شده بودند.</p>
        </div>
      </div>
      <div v-else-if="result.committed" class="flex items-center gap-3 bg-emerald-50 text-emerald-800 rounded-xl px-4 py-3 text-sm font-semibold">
        <NavIcon name="check" :size="20" />
        ثبت شد: {{ num(result.created) }} مورد جدید، {{ num(result.updated) }} به‌روزشده، {{ num(result.customers_created) }} مشتری تازه.
        <template v-if="result.queued_for_review">{{ num(result.queued_for_review) }} مشتری تازه شبیه مشتری موجود بود و به «بازبینی تطبیق» رفت.</template>
      </div>
      <h3 v-else class="font-bold text-ink">پیش‌نمایش — هنوز چیزی ثبت نشده</h3>

      <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[560px]">
          <thead>
            <tr class="text-xs text-slate-400 border-b border-slate-100">
              <th class="text-right font-medium py-2">نوع</th>
              <th class="text-left font-medium py-2">در فایل</th>
              <th class="text-left font-medium py-2">جدید</th>
              <th class="text-left font-medium py-2">به‌روز</th>
              <th class="text-left font-medium py-2">قبلاً خوانده شده</th>
              <th class="text-right font-medium py-2 pr-4">رد شد</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(k, key) in result.kinds" :key="key" class="border-t border-slate-100">
              <td class="py-2 text-ink">
                {{ k.label }}
                <span v-if="k.merged" class="text-[11px] text-slate-400">· {{ num(k.merged) }} در شرکتشان</span>
              </td>
              <td class="py-2 text-left text-slate-500">{{ num(k.rows) }}</td>
              <td class="py-2 text-left" :class="k.created ? 'text-emerald-600 font-medium' : 'text-slate-400'">{{ num(k.created) }}</td>
              <td class="py-2 text-left" :class="k.updated ? 'text-sky-600' : 'text-slate-400'">{{ num(k.updated) }}</td>
              <td class="py-2 text-left text-slate-400">{{ num(k.unchanged) }}</td>
              <td class="py-2 pr-4 text-xs" :class="skippedTotal(k.skipped) ? 'text-amber-600' : 'text-slate-300'">
                <template v-if="skippedTotal(k.skipped)">
                  <span v-for="(n, why) in k.skipped" :key="why" class="block">{{ num(n) }} — {{ why }}</span>
                </template>
                <template v-else>—</template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="text-[11px] text-slate-400">
        «فعالیت ها» و «یاداشت ها» هر دو همان فعالیت‌ها را دارند؛ تکراری‌ها یک بار ثبت می‌شوند.
      </p>

      <div v-if="result.unknown_reps.length" class="text-xs text-slate-500 bg-slate-50 rounded-xl px-4 py-3 leading-6">
        <p class="font-medium text-slate-600">
          این مسئول‌ها در فهرست کارشناسان نیستند — رکوردهایشان بدون مسئول ثبت می‌شود.
          اگر به فهرست اضافه شوند، ورود دوباره‌ی همین فایل‌ها مسئول خالی را پر می‌کند.
        </p>
        <span v-for="r in result.unknown_reps" :key="r.name" class="inline-block ml-3">{{ r.name }} ({{ num(r.count) }})</span>
      </div>

      <div class="flex flex-wrap items-center gap-3">
        <button
          v-if="!result.committed && !result.nothing_new"
          class="bg-panel text-white rounded-xl px-5 py-2.5 text-sm"
          @click="commit"
        >ثبت {{ num(result.created + result.updated) }} مورد در سیستم</button>
        <button v-if="result.committed || result.nothing_new" class="text-sm text-slate-500 hover:text-ink" @click="reset">فایل‌های دیگر</button>
      </div>
    </div>

    <!-- History -->
    <div :class="card">
      <p class="text-sm font-semibold text-ink mb-3">سابقه‌ی ورود از دیدار</p>
      <div v-if="loadingHistory" class="space-y-2"><Skeleton v-for="i in 3" :key="i" class="h-9 rounded-xl" /></div>
      <EmptyState v-else-if="!history.length" title="هنوز فایلی از دیدار وارد نشده" />
      <div v-else class="overflow-x-auto">
        <table class="w-full text-xs min-w-[640px]">
          <thead>
            <tr class="text-slate-400 border-b border-slate-100">
              <th class="text-right font-medium py-2">زمان</th>
              <th class="text-right font-medium py-2">فایل‌ها</th>
              <th class="text-left font-medium py-2">ردیف</th>
              <th class="text-left font-medium py-2">جدید</th>
              <th class="text-left font-medium py-2">به‌روز</th>
              <th class="text-left font-medium py-2">تکراری</th>
              <th class="text-left font-medium py-2">مشتری تازه</th>
              <th class="text-right font-medium py-2 pr-3">توسط</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="h in history" :key="h.id" class="border-t border-slate-100">
              <td class="py-2 text-slate-500 whitespace-nowrap">{{ jdatetime(h.at) }}</td>
              <td class="py-2 text-ink max-w-[260px] truncate" :title="h.file_name">{{ h.file_name }}</td>
              <td class="py-2 text-left">{{ num(h.rows) }}</td>
              <td class="py-2 text-left" :class="h.created ? 'text-emerald-600' : 'text-slate-400'">{{ num(h.created) }}</td>
              <td class="py-2 text-left" :class="h.updated ? 'text-sky-600' : 'text-slate-400'">{{ num(h.updated) }}</td>
              <td class="py-2 text-left text-slate-400">{{ num(h.unchanged) }}</td>
              <td class="py-2 text-left">{{ num(h.customers_created) }}</td>
              <td class="py-2 pr-3 text-slate-500">{{ h.by || "—" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
