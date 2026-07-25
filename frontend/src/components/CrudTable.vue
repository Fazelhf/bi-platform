<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { confirm } from "@/composables/useUi";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

export interface CrudColumn {
  key: string;
  label: string;
  type?: "text" | "number" | "select" | "boolean" | "password";
  options?: { value: string | number; label: string }[];
  editable?: boolean; // default true
  showInTable?: boolean; // default true
  required?: boolean;
}

const props = defineProps<{
  title: string;
  columns: CrudColumn[];
  rows: Record<string, any>[];
  loading?: boolean;
  canDelete?: boolean;
}>();
const emit = defineEmits<{
  (e: "create", payload: Record<string, any>): void;
  (e: "update", id: number, payload: Record<string, any>): void;
  (e: "remove", id: number): void;
}>();

const search = ref("");
const page = ref(1);
const pageSize = 10;
const sortKey = ref("");
const sortDir = ref(1);

const tableCols = computed(() => props.columns.filter((c) => c.showInTable !== false));

const filtered = computed(() => {
  let out = props.rows;
  const q = search.value.trim();
  if (q) {
    out = out.filter((r) =>
      tableCols.value.some((c) => String(r[c.key] ?? "").includes(q)),
    );
  }
  if (sortKey.value) {
    const k = sortKey.value;
    out = [...out].sort((a, b) => {
      const av = a[k], bv = b[k];
      const an = Number(av), bn = Number(bv);
      if (!Number.isNaN(an) && !Number.isNaN(bn)) return (an - bn) * sortDir.value;
      return String(av ?? "").localeCompare(String(bv ?? ""), "fa") * sortDir.value;
    });
  }
  return out;
});
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)));
const paged = computed(() =>
  filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize),
);
watch([search, () => props.rows], () => (page.value = 1));

function sortBy(key: string) {
  if (sortKey.value === key) sortDir.value *= -1;
  else { sortKey.value = key; sortDir.value = 1; }
}

// ---- Modal form ----
const showModal = ref(false);
const editingId = ref<number | null>(null);
const form = ref<Record<string, any>>({});

function openCreate() {
  editingId.value = null;
  form.value = Object.fromEntries(
    props.columns.filter((c) => c.editable !== false)
      .map((c) => [c.key, c.type === "boolean" ? true : ""]),
  );
  showModal.value = true;
}
function openEdit(row: Record<string, any>) {
  editingId.value = row.id;
  form.value = Object.fromEntries(
    props.columns.filter((c) => c.editable !== false)
      .map((c) => [c.key, c.type === "password" ? "" : row[c.key]]),
  );
  showModal.value = true;
}
function save() {
  const payload = { ...form.value };
  // Drop empty optional passwords so "keep current password" works.
  for (const c of props.columns) {
    if (c.type === "password" && !payload[c.key]) delete payload[c.key];
    if (c.type === "number" && payload[c.key] !== "" && payload[c.key] != null)
      payload[c.key] = Number(payload[c.key]);
  }
  if (editingId.value == null) emit("create", payload);
  else emit("update", editingId.value, payload);
  showModal.value = false;
}
async function remove(row: Record<string, any>) {
  if (await confirm({ title: "حذف", message: `«${row[tableCols.value[0].key]}» حذف شود؟`, danger: true })) {
    emit("remove", row.id);
  }
}

function display(row: Record<string, any>, col: CrudColumn): string {
  const v = row[col.key];
  if (col.type === "boolean") return v ? "✓" : "—";
  if (col.type === "select")
    return col.options?.find((o) => String(o.value) === String(v))?.label ?? String(v ?? "");
  return String(v ?? "");
}
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft">
    <div class="flex items-center justify-between gap-3 p-4 border-b border-slate-100">
      <h2 class="font-semibold text-ink">{{ title }}</h2>
      <div class="flex items-center gap-2">
        <input
          v-model="search"
          placeholder="جستجو…"
          class="border border-slate-200 rounded-xl px-3 py-1.5 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition"
        />
        <button
          class="bg-brand-600 text-white text-sm rounded-xl px-3 py-1.5 hover:bg-brand-700 transition-colors"
          @click="openCreate"
        >+ افزودن</button>
      </div>
    </div>

    <!-- Loading: skeleton rows -->
    <div v-if="loading" class="p-4 space-y-3">
      <div v-for="i in 6" :key="i" class="flex items-center gap-4">
        <Skeleton class="h-3 flex-1" />
        <Skeleton class="h-3 w-24" />
        <Skeleton class="h-3 w-16" />
      </div>
    </div>

    <!-- Empty: nothing to show at all -->
    <EmptyState
      v-else-if="!filtered.length"
      :icon="search ? '🔍' : '📄'"
      :title="search ? 'نتیجه‌ای یافت نشد' : 'هنوز موردی ثبت نشده'"
      :hint="search ? 'عبارت دیگری را جستجو کنید.' : 'برای افزودن اولین مورد، دکمه‌ی «افزودن» را بزنید.'"
    >
      <template v-if="!search" #action>
        <button
          class="bg-brand-600 text-white text-sm rounded-xl px-4 py-2 hover:bg-brand-700 transition-colors"
          @click="openCreate"
        >+ افزودن</button>
      </template>
    </EmptyState>

    <div v-else class="overflow-x-auto">
      <table class="w-full text-sm min-w-[520px]">
        <thead>
          <tr class="text-slate-400 border-b border-slate-100">
            <th
              v-for="c in tableCols"
              :key="c.key"
              class="text-right font-medium py-2 px-4 cursor-pointer select-none hover:text-slate-600 whitespace-nowrap"
              @click="sortBy(c.key)"
            >
              {{ c.label }}
              <span v-if="sortKey === c.key">{{ sortDir === 1 ? "▲" : "▼" }}</span>
            </th>
            <th class="w-28"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in paged" :key="row.id" class="border-b border-slate-50 hover:bg-slate-50/50 transition-colors">
            <td v-for="c in tableCols" :key="c.key" class="py-2 px-4">
              {{ display(row, c) }}
            </td>
            <td class="py-2 px-4 text-left whitespace-nowrap">
              <button class="text-brand-600 text-xs hover:underline ml-2" @click="openEdit(row)">ویرایش</button>
              <button v-if="canDelete !== false" class="text-red-500 text-xs hover:underline" @click="remove(row)">حذف</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="pageCount > 1" class="flex items-center justify-center gap-2 p-3 border-t border-slate-100 text-sm">
      <button class="px-2 py-1 rounded hover:bg-slate-100 disabled:opacity-40" :disabled="page === 1" @click="page--">قبلی</button>
      <span class="text-slate-500">صفحه {{ page }} از {{ pageCount }}</span>
      <button class="px-2 py-1 rounded hover:bg-slate-100 disabled:opacity-40" :disabled="page === pageCount" @click="page++">بعدی</button>
    </div>

    <!-- Modal -->
    <div v-if="showModal" class="fixed inset-0 bg-black/30 flex items-center justify-center z-50" @click.self="showModal = false">
      <div class="bg-surface rounded-2xl shadow-xl w-full max-w-md p-6">
        <h3 class="font-bold text-ink mb-4">
          {{ editingId == null ? "افزودن" : "ویرایش" }} — {{ title }}
        </h3>
        <form class="space-y-3" @submit.prevent="save">
          <div v-for="c in columns.filter(c => c.editable !== false)" :key="c.key">
            <label class="block text-xs text-slate-500 mb-1">{{ c.label }}</label>
            <select
              v-if="c.type === 'select'"
              v-model="form[c.key]"
              class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm bg-surface"
            >
              <option v-for="o in c.options" :key="String(o.value)" :value="o.value">{{ o.label }}</option>
            </select>
            <label v-else-if="c.type === 'boolean'" class="inline-flex items-center gap-2 text-sm">
              <input v-model="form[c.key]" type="checkbox" class="rounded" /> فعال
            </label>
            <input
              v-else
              v-model="form[c.key]"
              :type="c.type === 'number' ? 'number' : c.type === 'password' ? 'password' : 'text'"
              :required="c.required"
              step="any"
              class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
          </div>
          <div class="flex justify-end gap-2 pt-2">
            <button type="button" class="px-4 py-2 text-sm rounded-lg hover:bg-slate-100" @click="showModal = false">انصراف</button>
            <button type="submit" class="px-4 py-2 text-sm rounded-lg bg-brand-600 text-white hover:bg-brand-700">ذخیره</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
