<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import CrudTable, { type CrudColumn } from "@/components/CrudTable.vue";
import { crudApi } from "@/api/platform";

/**
 * One page manages every dimension table. This is what makes the platform
 * data-driven: add a salesperson or machine here and every grid, dashboard
 * and report picks it up automatically — nothing is hard-coded.
 */
interface Tab {
  key: string;
  label: string;
  endpoint: string;
  columns: CrudColumn[];
}

const teamsOptions = ref<{ value: number; label: string }[]>([]);

const tabs = computed<Tab[]>(() => [
  {
    key: "employees", label: "فروشندگان", endpoint: "/sales/employees/",
    columns: [
      { key: "full_name_fa", label: "نام کامل", required: true },
      { key: "code", label: "کد", required: true },
      { key: "team", label: "تیم", type: "select", options: teamsOptions.value },
      { key: "is_active", label: "فعال", type: "boolean" },
    ],
  },
  {
    key: "teams", label: "تیم‌های فروش", endpoint: "/sales/teams/",
    columns: [
      { key: "name_fa", label: "نام", required: true },
      { key: "name_en", label: "نام انگلیسی" },
      { key: "code", label: "کد", required: true },
    ],
  },
  {
    key: "provinces", label: "استان‌ها", endpoint: "/sales/provinces/",
    columns: [
      { key: "name_fa", label: "نام استان", required: true },
      { key: "code", label: "کد", required: true },
    ],
  },
  {
    key: "banks", label: "بانک‌ها و درگاه‌ها", endpoint: "/sales/banks/",
    columns: [
      { key: "name_fa", label: "نام", required: true },
      { key: "code", label: "کد", required: true },
      {
        key: "kind", label: "نوع", type: "select",
        options: [
          { value: "bank", label: "بانک" },
          { value: "psp", label: "درگاه پرداخت (PSP)" },
        ],
      },
    ],
  },
  {
    key: "machines", label: "خطوط تولید", endpoint: "/production/machines/",
    columns: [
      { key: "name_fa", label: "نام", required: true },
      { key: "code", label: "کد", required: true },
      {
        key: "kind", label: "نوع", type: "select",
        options: [
          { value: "cutting", label: "برش" },
          { value: "print", label: "چاپ" },
        ],
      },
      { key: "is_active", label: "فعال", type: "boolean" },
      { key: "sort_order", label: "ترتیب", type: "number" },
    ],
  },
  {
    key: "products", label: "محصولات", endpoint: "/production/products/",
    columns: [
      { key: "name_fa", label: "نام", required: true },
      { key: "code", label: "کد", required: true },
      { key: "unit", label: "واحد" },
      { key: "piece_rate_rial", label: "اجرت (ریال)", type: "number" },
      { key: "index_factor", label: "ضریب شاخص", type: "number" },
      { key: "sort_order", label: "ترتیب", type: "number" },
    ],
  },
]);

const active = ref("employees");
const rows = ref<Record<string, any>[]>([]);
const loading = ref(true);
const error = ref("");

const tab = computed(() => tabs.value.find((t) => t.key === active.value)!);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    rows.value = await crudApi.list(tab.value.endpoint);
  } finally {
    loading.value = false;
  }
}

async function run(op: () => Promise<unknown>) {
  error.value = "";
  try {
    await op();
    await load();
  } catch (e: any) {
    error.value = JSON.stringify(e?.response?.data ?? "خطا");
  }
}

onMounted(async () => {
  const teams = await crudApi.list("/sales/teams/");
  teamsOptions.value = teams.map((t) => ({ value: t.id, label: t.name_fa }));
  await load();
});
watch(active, load);
</script>

<template>
  <div class="space-y-4">
    <h1 class="text-xl font-bold text-ink">مدیریت داده‌های پایه</h1>

    <div class="flex flex-wrap gap-1">
      <button
        v-for="t in tabs"
        :key="t.key"
        class="px-3 py-1.5 rounded-lg text-sm"
        :class="active === t.key ? 'bg-brand-600 text-white' : 'bg-surface border border-slate-200 hover:bg-slate-50'"
        @click="active = t.key"
      >{{ t.label }}</button>
    </div>

    <p v-if="error" class="text-sm text-red-600 bg-red-50 rounded-lg p-2 ltr-nums">{{ error }}</p>

    <CrudTable
      :key="tab.key"
      :title="tab.label"
      :columns="tab.columns"
      :rows="rows"
      :loading="loading"
      @create="(p) => run(() => crudApi.create(tab.endpoint, p))"
      @update="(id, p) => run(() => crudApi.patch(tab.endpoint, id, p))"
      @remove="(id) => run(() => crudApi.remove(tab.endpoint, id))"
    />

    <p class="text-xs text-slate-400">
      با افزودن فروشنده/دستگاه/محصول جدید، تمام گریدها و داشبوردها خودکار
      به‌روزرسانی می‌شوند. حذف رکوردی که داده تاریخی دارد توسط سیستم مسدود می‌شود.
    </p>
  </div>
</template>
