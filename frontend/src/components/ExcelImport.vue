<script setup lang="ts">
/**
 * ورود اکسل — one button, one dialog, for every import in فروش ۲ and مالی:
 * download the sample, choose the file, «بررسی فایل» (nothing saved), then
 * «تأیید و ثبت» for the valid rows. Rows with an error are skipped.
 */
import { computed, ref, watch } from "vue";
import { importsApi, type ImporterInfo, type ImportResult, type ImportStatus } from "@/api/imports";
import { apiError } from "@/components/crm/formError";
import { toast } from "@/composables/useUi";
import { MONTH_NAMES, toJalali } from "@/utils/jalali";

const props = withDefaults(defineProps<{
  importKey: string;
  label?: string;
  year?: number;
  month?: number;
  params?: Record<string, string | number>;
}>(), { label: "ورود از اکسل" });
const emit = defineEmits<{ done: [written: number] }>();

const FA = new Intl.NumberFormat("fa-IR");
const now = toJalali(new Date());
const open = ref(false);
const info = ref<ImporterInfo | null>(null);
const values = ref<Record<string, string | number>>({});
const file = ref<File | null>(null);
const result = ref<ImportResult | null>(null);
const busy = ref(false);
const error = ref("");
const onlyProblems = ref(false);

async function show() {
  open.value = true;
  error.value = "";
  if (!info.value) {
    try { info.value = (await importsApi.list()).find((i) => i.key === props.importKey) ?? null; }
    catch (e) { error.value = apiError(e); }
  }
  values.value = {
    year: props.year ?? now.jy, month: props.month ?? now.jm, ...(props.params ?? {}),
  };
}
function close() {
  open.value = false; file.value = null; result.value = null;
}
watch(file, () => { result.value = null; });

async function run(confirm: boolean) {
  if (!file.value) return;
  busy.value = true; error.value = "";
  try {
    const r = await importsApi.run(props.importKey, file.value, values.value, confirm);
    if (confirm) {
      toast.success(`${FA.format(r.written ?? 0)} ردیف ثبت شد${r.counts.error ? ` · ${FA.format(r.counts.error)} ردیف خطا کنار گذاشته شد` : ""}.`);
      emit("done", r.written ?? 0);
      close();
    } else result.value = r;
  } catch (e) { error.value = apiError(e); }
  finally { busy.value = false; }
}
async function sample() {
  try { await importsApi.template(props.importKey); } catch (e) { error.value = apiError(e); }
}

const STATUS: Record<ImportStatus, { label: string; cls: string }> = {
  new: { label: "جدید", cls: "bg-emerald-100 text-emerald-700" },
  changed: { label: "تغییر", cls: "bg-amber-100 text-amber-700" },
  same: { label: "بدون تغییر", cls: "bg-slate-100 text-slate-500" },
  error: { label: "خطا", cls: "bg-red-100 text-red-700" },
};
const writable = computed(() => (result.value ? result.value.counts.new + result.value.counts.changed : 0));
const shown = computed(() => (result.value?.rows ?? []).filter((r) => !onlyProblems.value || r.status === "error"));
const years = [now.jy - 1, now.jy, now.jy + 1];
function cell(v: unknown) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "بله" : "خیر";
  const s = String(v);
  return /^\d{4,}$/.test(s) ? FA.format(Number(s)) : s;
}
</script>

<template>
  <button type="button" class="rounded-xl px-3 py-2 text-sm bg-slate-100 text-slate-700 hover:bg-slate-200" @click="show">{{ label }}</button>

  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 bg-black/40 flex items-start justify-center p-4 overflow-y-auto" dir="rtl" @click.self="close">
      <div class="bg-surface rounded-card shadow-soft w-full max-w-4xl p-4 space-y-3 mt-8">
        <div class="flex items-start gap-3">
          <div class="flex-1">
            <h2 class="text-base font-bold text-ink">{{ info?.title ?? "ورود از اکسل" }}</h2>
            <p v-if="info?.description" class="text-xs text-slate-500 mt-1">{{ info.description }}</p>
          </div>
          <button class="text-slate-400 hover:text-ink text-xl leading-none" @click="close">×</button>
        </div>

        <ol class="text-xs text-slate-500 flex flex-wrap gap-x-4 gap-y-1">
          <li>۱. فایل نمونه را بگیرید و پر کنید</li>
          <li>۲. «بررسی فایل» — چیزی ذخیره نمی‌شود</li>
          <li>۳. «تأیید و ثبت» — فقط ردیف‌های جدید و تغییر</li>
        </ol>

        <div class="flex flex-wrap items-center gap-2">
          <button class="rounded-xl px-3 py-2 text-sm bg-emerald-50 text-emerald-700 hover:bg-emerald-100" @click="sample">⬇ اکسل نمونه</button>
          <template v-for="p in info?.params ?? []" :key="p.name">
            <template v-if="p.kind === 'month'">
              <select v-model.number="values.month" class="bg-slate-100 rounded-xl px-3 py-2 text-sm outline-none" @change="result = null">
                <option v-for="(m, i) in MONTH_NAMES" :key="i" :value="i + 1">{{ m }}</option>
              </select>
              <select v-model.number="values.year" class="bg-slate-100 rounded-xl px-3 py-2 text-sm outline-none" @change="result = null">
                <option v-for="y in years" :key="y" :value="y">{{ FA.format(y).replace(/٬/g, "") }}</option>
              </select>
            </template>
            <select v-else v-model="values[p.name]" class="bg-slate-100 rounded-xl px-3 py-2 text-sm outline-none" @change="result = null">
              <option value="" disabled>{{ p.label }}…</option>
              <option v-for="o in p.options ?? []" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </template>
          <input type="file" accept=".xlsx" class="text-sm flex-1 min-w-[200px]" @change="(e) => { file = (e.target as HTMLInputElement).files?.[0] ?? null; }" />
          <button class="rounded-xl px-4 py-2 text-sm bg-slate-100 text-slate-700" :disabled="!file || busy" @click="run(false)">
            {{ busy && !result ? "در حال بررسی…" : "بررسی فایل" }}
          </button>
        </div>

        <details v-if="info && !result" class="text-xs text-slate-500">
          <summary class="cursor-pointer">ستون‌ها</summary>
          <ul class="mt-1 space-y-0.5">
            <li v-for="c in info.columns" :key="c.name">
              <b :class="c.required ? 'text-red-600' : 'text-ink'">{{ c.name }}</b><span v-if="c.required"> (الزامی)</span>
              <span v-if="c.help"> — {{ c.help }}</span>
              <span v-if="c.choices"> — {{ c.choices.join("، ") }}</span>
            </li>
          </ul>
        </details>

        <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line">{{ error }}</p>

        <template v-if="result">
          <div class="flex flex-wrap items-center gap-2 text-xs">
            <span v-for="(s, k) in STATUS" :key="k" class="rounded-full px-2 py-0.5" :class="s.cls">{{ s.label }}: {{ FA.format(result.counts[k]) }}</span>
            <label v-if="result.counts.error" class="flex items-center gap-1 mr-auto"><input v-model="onlyProblems" type="checkbox" /> فقط خطاها</label>
          </div>
          <div class="max-h-[50vh] overflow-auto border border-slate-100 rounded-xl">
            <table class="w-full text-sm">
              <thead class="sticky top-0 bg-slate-50 text-xs text-slate-400">
                <tr>
                  <th class="px-2 py-1.5 text-right font-medium">ردیف</th>
                  <th v-for="c in result.columns" :key="c" class="px-2 text-right font-medium whitespace-nowrap">{{ c }}</th>
                  <th class="px-2 text-right font-medium">وضعیت</th>
                  <th class="px-2 text-right font-medium">توضیح</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in shown" :key="`${r.sheet}:${r.n}`" class="border-t border-slate-100" :class="r.status === 'error' ? 'bg-red-50/50' : ''">
                  <td class="px-2 py-1 text-xs text-slate-400 whitespace-nowrap">{{ r.sheet ? `${r.sheet} · ` : "" }}{{ FA.format(r.n) }}</td>
                  <td v-for="c in result.columns" :key="c" class="px-2 whitespace-nowrap">{{ cell(r.values[c]) }}</td>
                  <td class="px-2"><span class="text-xs rounded-full px-2 py-0.5 whitespace-nowrap" :class="STATUS[r.status].cls">{{ STATUS[r.status].label }}</span></td>
                  <td class="px-2 text-xs" :class="r.status === 'error' ? 'text-red-600' : 'text-slate-500'">{{ r.message }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="flex items-center gap-2">
            <button class="rounded-xl px-4 py-2 text-sm bg-panel text-white disabled:opacity-50" :disabled="busy || !writable" @click="run(true)">
              تأیید و ثبت {{ FA.format(writable) }} ردیف
            </button>
            <span v-if="result.counts.error" class="text-xs text-red-600">{{ FA.format(result.counts.error) }} ردیف خطا ثبت نمی‌شود — اصلاح کنید و دوباره بررسی کنید.</span>
          </div>
        </template>
      </div>
    </div>
  </Teleport>
</template>
