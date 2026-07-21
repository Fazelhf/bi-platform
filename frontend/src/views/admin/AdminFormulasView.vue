<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { formulasApi, kpiApi } from "@/api/platform";
import type { Formula, KpiDefinition } from "@/types";

const domain = ref<"sales" | "production">("sales");
const kpis = ref<KpiDefinition[]>([]);
const selectedKpi = ref<KpiDefinition | null>(null);
const formulas = ref<Formula[]>([]);
const variables = ref<string[]>([]);
const loading = ref(false);
const message = ref<{ kind: "ok" | "err"; text: string } | null>(null);

const SLOTS: Record<string, { key: string; label: string }[]> = {
  sales: [{ key: "actual", label: "واقعی" }],
  production: [
    { key: "actual", label: "واقعی" },
    { key: "target", label: "مطلوب" },
    { key: "ideal", label: "ایده‌آل" },
  ],
};
const slots = computed(() => SLOTS[domain.value]);

// New-version form state, per slot.
const draft = ref<Record<string, { expression: string; note: string; testResult: string }>>({});

function resetDrafts() {
  draft.value = Object.fromEntries(
    slots.value.map((s) => [s.key, { expression: "", note: "", testResult: "" }]),
  );
}

const bySlot = computed(() => {
  const map: Record<string, Formula[]> = {};
  for (const s of slots.value) {
    map[s.key] = formulas.value
      .filter((f) => f.slot === s.key)
      .sort((a, b) => b.version - a.version);
  }
  return map;
});

async function loadKpis() {
  kpis.value = await kpiApi.list(domain.value);
  selectedKpi.value = kpis.value[0] ?? null;
  variables.value = await formulasApi.variables(domain.value);
}

async function loadFormulas() {
  if (!selectedKpi.value) return;
  loading.value = true;
  try {
    formulas.value = await formulasApi.list({ kpi: selectedKpi.value.id });
    resetDrafts();
  } finally {
    loading.value = false;
  }
}

async function testDraft(slot: string) {
  const d = draft.value[slot];
  message.value = null;
  const r = await formulasApi.test(d.expression, domain.value);
  d.testResult = r.ok
    ? `نتیجه با مقادیر نمونه (همه=۱۰۰): ${r.result ?? "تهی"}`
    : `❌ ${r.error}`;
}

async function saveDraft(slot: string) {
  if (!selectedKpi.value) return;
  const d = draft.value[slot];
  message.value = null;
  try {
    await formulasApi.create({
      kpi: selectedKpi.value.id, slot,
      expression: d.expression, note: d.note,
    });
    message.value = { kind: "ok", text: "نسخه جدید ذخیره و فعال شد؛ همه شاخص‌ها بازمحاسبه شدند." };
    await loadFormulas();
  } catch (e: any) {
    message.value = { kind: "err", text: JSON.stringify(e?.response?.data ?? "خطا") };
  }
}

async function rollback(f: Formula) {
  message.value = null;
  await formulasApi.activate(f.id);
  message.value = { kind: "ok", text: `نسخه ${f.version} فعال شد (بازگشت).` };
  await loadFormulas();
}

async function turnOff(f: Formula) {
  await formulasApi.deactivate(f.id);
  message.value = { kind: "ok", text: "فرمول غیرفعال شد — محاسبه داخلی پیش‌فرض استفاده می‌شود." };
  await loadFormulas();
}

onMounted(async () => {
  await loadKpis();
  await loadFormulas();
});
watch(domain, async () => {
  await loadKpis();
  await loadFormulas();
});
watch(selectedKpi, loadFormulas);
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-slate-800">مدیریت فرمول‌های BI</h1>
      <div class="flex gap-1">
        <button
          v-for="d in (['sales', 'production'] as const)"
          :key="d"
          class="px-3 py-1.5 rounded-lg text-sm"
          :class="domain === d ? 'bg-brand-600 text-white' : 'bg-white border border-slate-200'"
          @click="domain = d"
        >{{ d === "sales" ? "فروش" : "تولید" }}</button>
      </div>
    </div>

    <p
      v-if="message"
      class="text-sm rounded-lg p-2"
      :class="message.kind === 'ok' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'"
    >{{ message.text }}</p>

    <div class="grid grid-cols-1 lg:grid-cols-4 gap-4">
      <!-- KPI list -->
      <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-3 space-y-1 h-fit">
        <button
          v-for="k in kpis"
          :key="k.id"
          class="w-full text-right px-3 py-2 rounded-lg text-sm"
          :class="selectedKpi?.id === k.id ? 'bg-brand-50 text-brand-700 font-medium' : 'hover:bg-slate-50'"
          @click="selectedKpi = k"
        >
          {{ k.name_fa }}
          <span class="block text-xs text-slate-400">{{ k.code }} · {{ k.unit }}</span>
        </button>
      </div>

      <!-- Formula panels -->
      <div class="lg:col-span-3 space-y-4">
        <!-- Variables vocabulary -->
        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
          <h3 class="text-sm font-semibold text-slate-700 mb-2">متغیرهای مجاز</h3>
          <div class="flex flex-wrap gap-1.5">
            <code
              v-for="v in variables"
              :key="v"
              class="text-xs bg-slate-100 rounded px-2 py-0.5 cursor-pointer hover:bg-brand-50"
              title="کلیک = افزودن به فرمول"
              @click="slots.forEach(s => { draft[s.key].expression += (draft[s.key].expression ? ' ' : '') + v })"
            >{{ v }}</code>
          </div>
          <p class="text-xs text-slate-400 mt-2">
            عملگرهای مجاز: <span class="ltr-nums">+ - * / ( )</span> و توابع
            <span class="ltr-nums">abs, min, max, round</span> · تقسیم بر صفر = تهی (بدون خطا)
          </p>
        </div>

        <div v-if="loading" class="text-slate-400 text-sm">در حال بارگذاری…</div>

        <div
          v-for="s in slots"
          v-show="!loading"
          :key="s.key"
          class="bg-white rounded-xl shadow-sm border border-slate-200 p-4 space-y-3"
        >
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold text-slate-700">
              {{ selectedKpi?.name_fa }} — مقدار «{{ s.label }}»
            </h3>
            <span
              v-if="bySlot[s.key]?.find(f => f.is_active)"
              class="text-xs bg-green-100 text-green-700 rounded-full px-2 py-0.5"
            >فعال: نسخه {{ bySlot[s.key].find(f => f.is_active)!.version }}</span>
            <span v-else class="text-xs bg-slate-100 text-slate-500 rounded-full px-2 py-0.5">
              بدون فرمول — محاسبه داخلی
            </span>
          </div>

          <!-- History -->
          <table v-if="bySlot[s.key]?.length" class="w-full text-sm">
            <thead>
              <tr class="text-slate-400 border-b border-slate-100">
                <th class="text-right font-medium py-1.5 w-16">نسخه</th>
                <th class="text-right font-medium py-1.5">فرمول</th>
                <th class="text-right font-medium py-1.5">یادداشت</th>
                <th class="w-40"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="f in bySlot[s.key]"
                :key="f.id"
                class="border-b border-slate-50"
                :class="f.is_active ? 'bg-green-50/40' : ''"
              >
                <td class="py-1.5">v{{ f.version }} {{ f.is_active ? "✓" : "" }}</td>
                <td class="py-1.5"><code class="text-xs">{{ f.expression }}</code></td>
                <td class="py-1.5 text-xs text-slate-400">{{ f.note }}</td>
                <td class="py-1.5 text-left whitespace-nowrap">
                  <button
                    v-if="!f.is_active"
                    class="text-xs text-brand-600 hover:underline ml-2"
                    @click="rollback(f)"
                  >فعال‌سازی (بازگشت)</button>
                  <button
                    v-else
                    class="text-xs text-amber-600 hover:underline"
                    @click="turnOff(f)"
                  >غیرفعال</button>
                </td>
              </tr>
            </tbody>
          </table>

          <!-- New version -->
          <div class="border-t border-slate-100 pt-3 space-y-2">
            <label class="text-xs text-slate-500">فرمول جدید (نسخه بعدی)</label>
            <textarea
              v-model="draft[s.key].expression"
              dir="rtl"
              rows="2"
              class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm font-mono"
              placeholder="مثال: (سود / فروش) * 100"
            ></textarea>
            <input
              v-model="draft[s.key].note"
              placeholder="یادداشت تغییر (اختیاری)"
              class="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm"
            />
            <div class="flex items-center gap-2">
              <button
                class="px-3 py-1.5 text-sm rounded-lg border border-slate-300 hover:bg-slate-50"
                :disabled="!draft[s.key].expression"
                @click="testDraft(s.key)"
              >آزمایش</button>
              <button
                class="px-3 py-1.5 text-sm rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
                :disabled="!draft[s.key].expression"
                @click="saveDraft(s.key)"
              >ذخیره و فعال‌سازی</button>
              <span class="text-xs" :class="draft[s.key].testResult.startsWith('❌') ? 'text-red-600' : 'text-slate-500'">
                {{ draft[s.key].testResult }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
