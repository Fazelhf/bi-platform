<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { salesApi } from "@/api/sales";
import { salesInputApi, type SalesInput } from "@/api/salesInput";
import { toast, confirm } from "@/composables/useUi";
import { num } from "@/utils/format";
import MoneyInput from "@/components/MoneyInput.vue";
import ExportActions from "@/components/ExportActions.vue";

// Rial money fields get thousands-grouping while typing; counts stay plain.
const isMoney = (field: string) => field.endsWith("_rial");

const props = withDefaults(defineProps<{ channel?: string; title?: string }>(), {
  channel: "team",
  title: "ورود اطلاعات فروش",
});

const periods = ref<{ id: number; label: string }[]>([]);
const selectedPeriod = ref<number | null>(null);
const data = ref<SalesInput | null>(null);
const loading = ref(true);
const saving = ref("");

// ---- Add-salesperson picker (choose an existing person first, else new) ----
const allEmployees = ref<{ id: number; full_name_fa: string; team_name?: string }[]>([]);
const showAdd = ref(false);
const pickId = ref<number | "new" | "">("");
const newName = ref("");
// Names already used as columns in the current table — hide them from the list.
const usedNames = computed(() => new Set((data.value?.columns ?? []).map((c) => String(c.name).trim())));
const pickableEmployees = computed(() =>
  allEmployees.value.filter((e) => !usedNames.value.has(e.full_name_fa.trim())),
);

// Live جمع (sum) per metric row across all salesperson columns.
function rowTotal(field: string): number {
  return (data.value?.columns ?? []).reduce((s, c) => s + Number(c[field] || 0), 0);
}

async function load() {
  if (!selectedPeriod.value) return;
  loading.value = true;
  try {
    data.value = await salesInputApi.get(selectedPeriod.value, props.channel);
  } finally {
    loading.value = false;
  }
}

function openAddPicker() {
  pickId.value = "";
  newName.value = "";
  showAdd.value = true;
}

function addColumn(employeeId: number | null, name: string) {
  const blank: Record<string, any> = { employee_id: employeeId, name: name.trim(), status: "draft" };
  for (const m of data.value!.metric_rows) blank[m.field] = "0";
  data.value!.columns.push(blank);
}

function confirmAdd() {
  if (pickId.value === "new") {
    if (!newName.value.trim()) return;
    addColumn(null, newName.value);
  } else if (typeof pickId.value === "number") {
    const emp = allEmployees.value.find((e) => e.id === pickId.value);
    if (!emp) return;
    addColumn(emp.id, emp.full_name_fa);
  } else {
    return; // nothing chosen
  }
  showAdd.value = false;
}

async function removeSalesperson(i: number) {
  const c = data.value!.columns[i];
  if (await confirm({ title: "حذف فروشنده", message: `ستون «${c.name}» از این دوره حذف شود؟`, danger: true })) {
    data.value!.columns.splice(i, 1);
  }
}

// Province block — add a province row from the catalog.
const usedProvinceIds = computed(() => new Set((data.value?.provinces ?? []).map((p) => p.province_id)));
const addableProvinces = computed(() =>
  (data.value?.all_provinces ?? []).filter((p) => !usedProvinceIds.value.has(p.id)),
);
function addProvince(e: Event) {
  const id = Number((e.target as HTMLSelectElement).value);
  if (!id) return;
  const prov = data.value!.all_provinces.find((p) => p.id === id)!;
  data.value!.provinces.push({ province_id: id, name: prov.name, sales_rial: "0", target_rial: "0" });
  (e.target as HTMLSelectElement).value = "";
}

async function save(submit: boolean) {
  saving.value = submit ? "در حال ارسال…" : "در حال ذخیره…";
  try {
    await salesInputApi.save({
      period: selectedPeriod.value,
      channel: props.channel,
      submit,
      columns: data.value!.columns,
      provinces: data.value!.provinces,
    });
    saving.value = "";
    toast.success(submit ? "برای تایید مدیرعامل ارسال شد." : "پیش‌نویس ذخیره شد.");
    if (submit) await load();
  } catch (e: any) {
    saving.value = "";
    toast.error(e?.response?.status === 403 ? "دسترسی ندارید." : "ذخیره نشد.");
  }
}

onMounted(async () => {
  periods.value = await salesApi.periods();
  selectedPeriod.value = periods.value[0]?.id ?? null;
  await load();
  try {
    allEmployees.value = await salesApi.employees();
  } catch {
    allEmployees.value = [];
  }
});
watch([selectedPeriod, () => props.channel], load);
</script>

<template>
  <div class="space-y-4 pb-8">
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-lg font-bold text-ink">{{ title }}</h2>
        <p class="text-xs text-slate-400 mt-0.5">
          هر فروشنده یک ستون است. می‌توانید فروشنده اضافه یا حذف کنید؛ ستون «جمع» خودکار محاسبه می‌شود.
        </p>
      </div>
      <div class="flex items-center gap-3">
        <span class="text-sm" :class="saving.startsWith('خطا') ? 'text-red-500' : 'text-accent-600'">{{ saving }}</span>
        <ExportActions :excel="false" />
        <select v-model.number="selectedPeriod" class="bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm">
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <div v-if="loading || !data" class="text-slate-400">در حال بارگذاری…</div>

    <template v-else>
      <!-- Main table: metrics as rows, salespeople as columns -->
      <section class="bg-surface rounded-card shadow-soft p-5">
        <div class="flex items-center justify-between mb-4">
          <h3 class="font-bold text-ink">جدول عملکرد فروشندگان</h3>
          <button class="text-sm bg-accent-500 hover:bg-accent-600 text-white rounded-xl px-3 py-1.5 transition-colors" @click="openAddPicker">
            + افزودن فروشنده
          </button>
        </div>
        <div class="overflow-x-auto">
          <table class="text-sm border-separate" style="border-spacing: 0">
            <thead>
              <tr>
                <th class="text-right font-medium text-slate-500 py-2 px-3 sticky right-0 bg-surface z-10 min-w-[150px]">شاخص</th>
                <th v-for="(c, i) in data.columns" :key="i" class="font-medium py-2 px-2 min-w-[130px]">
                  <div class="flex items-center justify-center gap-1">
                    <input
                      v-model="c.name"
                      class="w-24 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1 text-center text-xs outline-none"
                    />
                    <button class="text-red-400 hover:text-red-600 text-xs" title="حذف ستون" @click="removeSalesperson(i)">✕</button>
                  </div>
                </th>
                <th class="font-medium py-2 px-3 text-accent-600 min-w-[130px] sticky left-0 bg-surface z-20 border-r border-slate-100">جمع</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in data.metric_rows" :key="m.field" class="border-t border-slate-50">
                <td class="py-1.5 px-3 font-medium whitespace-nowrap sticky right-0 bg-surface z-10">{{ m.label }}</td>
                <td v-for="(c, i) in data.columns" :key="i" class="py-1 px-1">
                  <MoneyInput
                    v-if="isMoney(m.field)"
                    v-model="c[m.field]"
                    class="w-full bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                  />
                  <input
                    v-else
                    v-model="c[m.field]" type="number" step="any"
                    class="w-full bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                  />
                </td>
                <td class="sum-cell py-1.5 px-3 text-center font-bold ltr-nums sticky left-0 z-20 border-r border-slate-100">
                  {{ num(rowTotal(m.field)) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!data.columns.length" class="text-sm text-slate-400 text-center py-6">
          هنوز فروشنده‌ای اضافه نشده. با دکمه «افزودن فروشنده» شروع کنید.
        </p>
      </section>

      <!-- Province block -->
      <section class="bg-surface rounded-card shadow-soft p-5">
        <div class="flex items-center justify-between mb-1">
          <h3 class="font-bold text-ink">فروش و تارگت به تفکیک استان</h3>
          <select class="bg-slate-50 border border-slate-200 rounded-xl px-3 py-1.5 text-sm" @change="addProvince">
            <option value="">+ افزودن استان</option>
            <option v-for="p in addableProvinces" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </div>
        <p class="text-xs text-slate-400 mb-4">
          برای هر استان، مبلغ فروش محقق‌شده و مبلغ تارگت (هدف) آن استان را به ریال وارد کنید.
          این ارقام فقط مربوط به «{{ title.replace("ورود اطلاعات ", "") }}» است و از استان‌های
          سایر کانال‌های فروش کاملاً جداست.
        </p>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
          <div
            v-for="p in data.provinces"
            :key="p.province_id"
            class="grid grid-cols-[1fr_auto_auto] items-center gap-2"
          >
            <span class="text-sm text-slate-600">{{ p.name }}</span>
            <label class="flex flex-col items-start gap-0.5">
              <span class="text-[11px] text-slate-400">فروش (ریال)</span>
              <MoneyInput v-model="p.sales_rial" placeholder="مبلغ فروش"
                class="w-32 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1.5 text-left ltr-nums outline-none" />
            </label>
            <label class="flex flex-col items-start gap-0.5">
              <span class="text-[11px] text-slate-400">تارگت (ریال)</span>
              <MoneyInput v-model="p.target_rial" placeholder="مبلغ تارگت"
                class="w-32 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1.5 text-left ltr-nums outline-none" />
            </label>
          </div>
        </div>
        <p v-if="!data.provinces.length" class="text-sm text-slate-400 py-3">استانی اضافه نشده.</p>
      </section>

      <!-- Sticky action bar -->
      <div class="sticky bottom-4 bg-panel text-white rounded-card shadow-pop p-3 flex items-center justify-between">
        <span class="text-sm text-white/70 px-2">پس از تکمیل، برای تایید مدیرعامل ارسال کنید.</span>
        <div class="flex gap-2">
          <button class="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/20 text-sm transition-colors" @click="save(false)">ذخیره پیش‌نویس</button>
          <button class="px-5 py-2 rounded-xl bg-accent-500 hover:bg-accent-600 text-sm font-medium transition-colors" @click="save(true)">ذخیره و ارسال برای تایید</button>
        </div>
      </div>
    </template>

    <!-- Add-salesperson picker: choose an existing person first, else add new -->
    <div
      v-if="showAdd"
      class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4"
      @click.self="showAdd = false"
    >
      <div class="bg-surface rounded-card shadow-pop w-full max-w-sm p-6 animate-pop">
        <h3 class="font-bold text-ink mb-4">افزودن فروشنده</h3>

        <label class="block text-xs text-slate-500 mb-1">انتخاب از فروشندگان موجود</label>
        <select
          v-model="pickId"
          class="w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface focus:outline-none focus:ring-2 focus:ring-accent-500/30 transition mb-3"
        >
          <option value="">— یک فروشنده را انتخاب کنید —</option>
          <option v-for="e in pickableEmployees" :key="e.id" :value="e.id">
            {{ e.full_name_fa }}{{ e.team_name ? ` — ${e.team_name}` : "" }}
          </option>
          <option value="new">➕ فروشنده جدید…</option>
        </select>

        <div v-if="pickId === 'new'" class="mb-1">
          <label class="block text-xs text-slate-500 mb-1">نام فروشنده جدید</label>
          <input
            v-model="newName"
            placeholder="نام و نام خانوادگی"
            class="w-full border border-slate-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500/30 transition"
            @keyup.enter="confirmAdd"
          />
        </div>
        <p v-else-if="!pickableEmployees.length" class="text-xs text-slate-400">
          همه‌ی فروشندگان موجود قبلاً در جدول هستند. برای افزودن، «فروشنده جدید» را انتخاب کنید.
        </p>

        <div class="flex justify-end gap-2 pt-5">
          <button class="px-4 py-2 text-sm rounded-lg hover:bg-slate-100 transition-colors" @click="showAdd = false">انصراف</button>
          <button
            class="px-4 py-2 text-sm rounded-lg bg-accent-500 text-white hover:bg-accent-600 disabled:opacity-50 transition-colors"
            :disabled="pickId === '' || (pickId === 'new' && !newName.trim())"
            @click="confirmAdd"
          >افزودن</button>
        </div>
      </div>
    </div>
  </div>
</template>
