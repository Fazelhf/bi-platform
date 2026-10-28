<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { crmApi, type DidarImportRow, type TeamyarImportResult } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num } from "@/utils/format";
import EmptyState from "@/components/EmptyState.vue";
import NavIcon from "@/components/NavIcon.vue";

/**
 * ورود مشتریان — the customer lists exported from تیم‌یار.
 *
 * A row joins the customer CRM already has through the آرپا/دیدار code its
 * «آخرین توضیحات» carries, or an id nobody else shares; otherwise it is a
 * new customer. A match only fills what is missing. Same preview-then-ثبت
 * flow as the other imports.
 */
const crm = useCrmStore();
const files = ref<File[]>([]);
const result = ref<TeamyarImportResult | null>(null);
const busy = ref<"" | "preview" | "commit">("");
const error = ref("");
const dragging = ref(false);
const input = ref<HTMLInputElement | null>(null);
const history = ref<DidarImportRow[]>([]);

function add(list: FileList | null | undefined) {
  if (!list?.length) return;
  const byName = new Map(files.value.map((f) => [f.name, f]));
  for (const f of Array.from(list)) byName.set(f.name, f);
  files.value = [...byName.values()];
  if (input.value) input.value.value = "";
  go(false);
}

async function go(commit: boolean) {
  busy.value = commit ? "commit" : "preview";
  error.value = "";
  if (!commit) result.value = null;
  try {
    result.value = await crmApi.teamyarImport(files.value, commit);
    if (commit) {
      crm.bump();
      history.value = (await crmApi.teamyarImports()).imports;
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? "فایل‌ها خوانده نشد.";
  } finally {
    busy.value = "";
  }
}

function reset() {
  files.value = [];
  result.value = null;
  error.value = "";
}

const matched = computed(() =>
  Object.values(result.value?.matched_by ?? {}).reduce((a, b) => a + b, 0),
);

onMounted(async () => {
  history.value = (await crmApi.teamyarImports()).imports;
});

function jdatetime(iso: string): string {
  return new Date(iso).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" });
}

const card = "bg-surface rounded-card shadow-soft p-4 min-w-0";
const tile = "bg-slate-50 rounded-xl p-3";
</script>

<template>
  <div class="space-y-4">
    <p class="text-xs text-slate-500 px-1 leading-6">
      فهرست مشتریان تیم‌یار. هر ردیف با <b class="text-slate-600">کد آرپا یا دیدارِ «آخرین توضیحات»</b>
      یا شناسه/کد ملیِ یکتا به مشتری موجود CRM وصل می‌شود و فقط جاهای خالی‌اش پر می‌شود؛ اسم شبیه، تطبیق حساب نمی‌شود.
      «تامین‌کننده»‌ها وارد نمی‌شوند.
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
          <NavIcon name="team" :size="22" />
        </span>
        <p class="mt-3 text-ink font-medium">فایل‌های «Teamyar_Client» را اینجا بکشید — چند فایل با هم</p>
      </div>
      <ul v-if="files.length" class="mt-3 text-sm text-ink space-y-1">
        <li v-for="f in files" :key="f.name" class="flex items-center gap-2" dir="auto">
          <NavIcon name="file" :size="15" class="text-slate-400" /> {{ f.name }}
        </li>
      </ul>
    </div>

    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3">{{ error }}</p>
    <div v-if="busy" :class="card" class="flex items-center gap-3 text-sm text-slate-500">
      <span class="w-4 h-4 rounded-full border-2 border-slate-300 border-t-slate-600 animate-spin"></span>
      {{ busy === "preview" ? "در حال خواندن و تطبیق با مشتریان CRM…" : "در حال ثبت…" }}
    </div>

    <div v-if="result && !busy" :class="card" class="space-y-4">
      <div v-if="result.nothing_new" class="flex items-center gap-3 bg-sky-50 text-sky-800 rounded-xl px-4 py-3 text-sm font-semibold">
        <NavIcon name="check" :size="20" /> همه‌ی ردیف‌ها قبلاً خوانده شده‌اند؛ چیز تازه‌ای نیست.
      </div>
      <div v-else-if="result.committed" class="flex items-center gap-3 bg-emerald-50 text-emerald-800 rounded-xl px-4 py-3 text-sm font-semibold">
        <NavIcon name="check" :size="20" /> ثبت شد: {{ num(result.created) }} مشتری تازه، {{ num(result.updated) }} تکمیل‌شده.
      </div>
      <h3 v-else class="font-bold text-ink">پیش‌نمایش — هنوز چیزی ثبت نشده</h3>

      <div class="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
        <div :class="tile"><p class="text-[11px] text-slate-400">ردیف</p><p class="font-bold text-lg text-ink">{{ num(result.rows) }}</p></div>
        <div :class="tile">
          <p class="text-[11px] text-slate-400">به مشتری موجود وصل شد</p>
          <p class="font-bold text-lg text-emerald-600">{{ num(matched) }}</p>
          <p class="text-[11px] text-slate-400"><span v-for="(n, how) in result.matched_by" :key="how" class="block">{{ how }}: {{ num(n) }}</span></p>
        </div>
        <div :class="tile"><p class="text-[11px] text-slate-400">تکمیل‌شده</p><p class="font-bold text-lg text-sky-600">{{ num(result.updated) }}</p></div>
        <div :class="tile"><p class="text-[11px] text-slate-400">مشتری تازه</p><p class="font-bold text-lg text-ink">{{ num(result.created) }}</p></div>
        <div :class="tile" title="مشتری تازه‌ای که شبیه مشتری موجود بود؛ در «بازبینی تطبیق» تصمیم بگیرید."><p class="text-[11px] text-slate-400">به بازبینی تطبیق</p><p class="font-bold text-lg text-ink">{{ num(result.queued_for_review ?? 0) }}</p></div>
        <div :class="tile">
          <p class="text-[11px] text-slate-400">وارد نشد</p>
          <p class="font-bold text-lg text-amber-600">{{ num(Object.values(result.skipped).reduce((a, b) => a + b, 0)) }}</p>
          <p class="text-[11px] text-slate-400"><span v-for="(n, why) in result.skipped" :key="why" class="block">{{ why }}: {{ num(n) }}</span></p>
        </div>
      </div>

      <div v-if="result.unknown_reps.length" class="text-xs text-slate-500 bg-slate-50 rounded-xl px-4 py-3 leading-6">
        <p class="font-medium text-slate-600">این کارشناس‌ها در فهرست نیستند — مسئول مشتری خالی می‌ماند:</p>
        <span v-for="r in result.unknown_reps" :key="r.name" class="inline-block ml-3">{{ r.name }} ({{ num(r.count) }})</span>
      </div>

      <div class="flex gap-3">
        <button v-if="!result.committed && !result.nothing_new" class="bg-panel text-white rounded-xl px-5 py-2.5 text-sm" @click="go(true)">
          ثبت در سیستم
        </button>
        <button v-if="result.committed || result.nothing_new" class="text-sm text-slate-500 hover:text-ink" @click="reset">فایل‌های دیگر</button>
      </div>
    </div>

    <div :class="card">
      <p class="text-sm font-semibold text-ink mb-3">سابقه‌ی ورود مشتریان</p>
      <EmptyState v-if="!history.length" title="هنوز فایلی وارد نشده" />
      <table v-else class="w-full text-xs">
        <tbody>
          <tr v-for="h in history" :key="h.id" class="border-t border-slate-100">
            <td class="py-2 text-slate-500 whitespace-nowrap">{{ jdatetime(h.at) }}</td>
            <td class="py-2 text-ink truncate max-w-[260px]">{{ h.file_name }}</td>
            <td class="py-2 text-left">{{ num(h.rows) }} ردیف</td>
            <td class="py-2 text-left text-emerald-600">{{ num(h.created) }} تازه</td>
            <td class="py-2 text-left text-sky-600">{{ num(h.updated) }} تکمیل</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
