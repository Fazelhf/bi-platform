<script setup lang="ts" generic="T extends Record<string, any>">
/**
 * The panel's table. One component covers both modes:
 *
 *  - `client` (default) — the parent hands over every row and the table does
 *    its own search, sort and paging. Right for lists of tens of rows.
 *  - server mode (`:client="false"`) — the table only renders what it is
 *    given and emits `query` whenever search / sort / page changes, so the
 *    parent can refetch. Right for audit logs and other unbounded tables.
 *
 * Selection, bulk actions and export are available in both.
 */
import { computed, ref, watch } from "vue";
import NavIcon from "@/components/NavIcon.vue";
import Skeleton from "@/components/Skeleton.vue";
import { faDate, faDateTime, faNum, formatBytes } from "@/utils/adminFormat";

export interface Column {
  key: string;
  label: string;
  /** How to render the cell. `slot` defers to a `cell-<key>` scoped slot. */
  type?: "text" | "number" | "bool" | "date" | "datetime" | "bytes" | "badge" | "slot";
  sortable?: boolean;
  width?: string;
  align?: "start" | "center" | "end";
  hint?: string;
}

// Generic over the row type so `#cell-*` and `#actions` slots hand callers a
// properly typed row instead of Record<string, any>.
const props = withDefaults(defineProps<{
  columns: Column[];
  rows: T[];
  loading?: boolean;
  /** Server mode: total row count across all pages. */
  total?: number;
  pageSize?: number;
  selectable?: boolean;
  client?: boolean;
  rowKey?: string;
  searchPlaceholder?: string;
  emptyTitle?: string;
  emptyHint?: string;
  /** Show the csv/xlsx/pdf buttons. */
  exportable?: boolean;
  dense?: boolean;
}>(), {
  pageSize: 25,
  client: true,
  rowKey: "id",
  searchPlaceholder: "جستجو…",
  emptyTitle: "موردی یافت نشد",
  emptyHint: "",
});

const emit = defineEmits<{
  (e: "query", value: { search: string; ordering: string; page: number; page_size: number }): void;
  (e: "row", row: T): void;
  (e: "export", fmt: "csv" | "xlsx" | "pdf"): void;
  (e: "refresh"): void;
  (e: "update:selection", ids: number[]): void;
}>();

const search = ref("");
const page = ref(1);
const sortKey = ref("");
const sortDir = ref<1 | -1>(1);
const selected = ref<Set<number>>(new Set());

const ordering = computed(() =>
  sortKey.value ? `${sortDir.value === 1 ? "" : "-"}${sortKey.value}` : "",
);

/** Server mode: debounce so typing does not fire a request per keystroke. */
let debounce: number | undefined;
function pushQuery(immediate = false) {
  if (props.client) return;
  window.clearTimeout(debounce);
  const run = () => emit("query", {
    search: search.value.trim(),
    ordering: ordering.value,
    page: page.value,
    page_size: props.pageSize,
  });
  if (immediate) run();
  else debounce = window.setTimeout(run, 300);
}

watch(search, () => { page.value = 1; pushQuery(); });
watch([ordering, page], () => pushQuery(true));
watch(() => props.rows, () => {
  // Drop selections for rows that are no longer on screen.
  const visible = new Set(props.rows.map((r) => r[props.rowKey]));
  const next = new Set([...selected.value].filter((id) => visible.has(id)));
  if (next.size !== selected.value.size) {
    selected.value = next;
    emit("update:selection", [...next]);
  }
});

// ---- client-side pipeline ----
const filtered = computed(() => {
  if (!props.client) return props.rows;
  let out = props.rows;
  const q = search.value.trim().toLowerCase();
  if (q) {
    out = out.filter((row) =>
      props.columns.some((c) => String(row[c.key] ?? "").toLowerCase().includes(q)),
    );
  }
  if (sortKey.value) {
    const k = sortKey.value;
    out = [...out].sort((a, b) => {
      const av = a[k], bv = b[k];
      const an = Number(av), bn = Number(bv);
      if (av != null && bv != null && !Number.isNaN(an) && !Number.isNaN(bn)) {
        return (an - bn) * sortDir.value;
      }
      return String(av ?? "").localeCompare(String(bv ?? ""), "fa") * sortDir.value;
    });
  }
  return out;
});

const totalRows = computed(() =>
  props.client ? filtered.value.length : (props.total ?? props.rows.length),
);
const pageCount = computed(() => Math.max(1, Math.ceil(totalRows.value / props.pageSize)));
const visibleRows = computed(() =>
  props.client
    ? filtered.value.slice((page.value - 1) * props.pageSize, page.value * props.pageSize)
    : props.rows,
);

function sortBy(column: Column) {
  if (column.sortable === false) return;
  if (sortKey.value === column.key) sortDir.value = sortDir.value === 1 ? -1 : 1;
  else { sortKey.value = column.key; sortDir.value = 1; }
}

// ---- selection ----
const allChecked = computed(() =>
  visibleRows.value.length > 0 &&
  visibleRows.value.every((r) => selected.value.has(r[props.rowKey])),
);
function toggleAll() {
  const next = new Set(selected.value);
  if (allChecked.value) visibleRows.value.forEach((r) => next.delete(r[props.rowKey]));
  else visibleRows.value.forEach((r) => next.add(r[props.rowKey]));
  selected.value = next;
  emit("update:selection", [...next]);
}
function toggleRow(row: T) {
  const next = new Set(selected.value);
  const id = row[props.rowKey];
  next.has(id) ? next.delete(id) : next.add(id);
  selected.value = next;
  emit("update:selection", [...next]);
}
function clearSelection() {
  selected.value = new Set();
  emit("update:selection", []);
}
defineExpose({ clearSelection, selectedIds: selected });

// ---- rendering ----
function display(row: T, column: Column): string {
  const value = row[column.key];
  if (value === null || value === undefined || value === "") return "—";
  switch (column.type) {
    case "bool": return value ? "بله" : "خیر";
    case "number": return faNum(value);
    case "bytes": return formatBytes(Number(value));
    case "date": return faDate(value);
    case "datetime": return faDateTime(value);
    default: return String(value);
  }
}
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft overflow-hidden">
    <!-- Toolbar -->
    <div class="flex flex-wrap items-center gap-2 p-3 border-b border-slate-100">
      <div class="flex items-center gap-2 bg-slate-100 rounded-xl px-3 py-1.5 flex-1 min-w-[180px] max-w-sm">
        <NavIcon name="search" :size="16" class="text-slate-400 shrink-0" />
        <input
          v-model="search"
          :placeholder="searchPlaceholder"
          class="bg-transparent outline-none text-sm text-ink w-full"
        />
        <button
          v-if="search"
          class="text-slate-400 hover:text-ink shrink-0"
          aria-label="پاک کردن جستجو"
          @click="search = ''"
        ><NavIcon name="close" :size="14" /></button>
      </div>

      <div class="flex items-center gap-1.5 flex-wrap">
        <slot name="toolbar" />
        <button
          class="p-1.5 rounded-lg text-slate-400 hover:text-ink hover:bg-slate-100 transition"
          title="بارگذاری مجدد"
          @click="emit('refresh')"
        ><NavIcon name="refresh" :size="16" /></button>
        <template v-if="exportable">
          <div class="w-px h-5 bg-slate-200 mx-1"></div>
          <button
            v-for="f in (['xlsx', 'csv', 'pdf'] as const)"
            :key="f"
            class="text-xs px-2 py-1.5 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-ink transition uppercase"
            :title="f === 'pdf' ? 'نسخه چاپی / PDF' : `خروجی ${f}`"
            @click="emit('export', f)"
          >{{ f }}</button>
        </template>
      </div>
    </div>

    <!-- Bulk bar -->
    <div
      v-if="selectable && selected.size"
      class="flex flex-wrap items-center gap-2 px-3 py-2 bg-brand-50 border-b border-slate-100 text-sm"
    >
      <span class="text-brand-700 font-medium">{{ selected.size }} مورد انتخاب شده</span>
      <div class="flex-1"></div>
      <slot name="bulk" :ids="[...selected]" :clear="clearSelection" />
      <button class="text-xs text-slate-500 hover:text-ink" @click="clearSelection">لغو انتخاب</button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="p-4 space-y-3">
      <div v-for="i in 6" :key="i" class="flex items-center gap-4">
        <Skeleton class="h-3 flex-1" />
        <Skeleton class="h-3 w-28" />
        <Skeleton class="h-3 w-16" />
      </div>
    </div>

    <!-- Empty -->
    <div v-else-if="!visibleRows.length" class="p-12 text-center">
      <p class="text-3xl mb-2">{{ search ? "🔍" : "📄" }}</p>
      <p class="font-medium text-ink">{{ search ? "نتیجه‌ای برای جستجوی شما نبود" : emptyTitle }}</p>
      <p v-if="emptyHint && !search" class="text-sm text-slate-400 mt-1">{{ emptyHint }}</p>
      <div class="mt-4"><slot name="empty-action" /></div>
    </div>

    <!-- Table -->
    <div v-else class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-slate-400 border-b border-slate-100 bg-slate-50/60">
            <th v-if="selectable" class="w-10 px-3">
              <input type="checkbox" :checked="allChecked" class="rounded" @change="toggleAll" />
            </th>
            <th
              v-for="c in columns"
              :key="c.key"
              class="font-medium py-2.5 px-3 whitespace-nowrap select-none"
              :class="[
                c.sortable === false ? '' : 'cursor-pointer hover:text-slate-600',
                c.align === 'center' ? 'text-center' : c.align === 'end' ? 'text-left' : 'text-right',
              ]"
              :style="c.width ? { width: c.width } : undefined"
              :title="c.hint"
              @click="sortBy(c)"
            >
              {{ c.label }}
              <span v-if="sortKey === c.key" class="text-brand-600">{{ sortDir === 1 ? "▲" : "▼" }}</span>
            </th>
            <th v-if="$slots.actions" class="w-px px-3"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in visibleRows"
            :key="row[rowKey]"
            class="border-b border-slate-50 last:border-0 hover:bg-slate-50/60 transition-colors"
            :class="{ 'bg-brand-50/40': selectable && selected.has(row[rowKey]) }"
          >
            <td v-if="selectable" class="px-3">
              <input
                type="checkbox"
                class="rounded"
                :checked="selected.has(row[rowKey])"
                @change="toggleRow(row)"
              />
            </td>
            <td
              v-for="c in columns"
              :key="c.key"
              class="px-3"
              :class="[
                dense ? 'py-1.5' : 'py-2.5',
                c.align === 'center' ? 'text-center' : c.align === 'end' ? 'text-left' : 'text-right',
                c.type === 'number' || c.type === 'bytes' ? 'ltr-nums' : '',
              ]"
              @click="emit('row', row)"
            >
              <slot :name="`cell-${c.key}`" :row="row" :value="row[c.key]">
                {{ display(row, c) }}
              </slot>
            </td>
            <td v-if="$slots.actions" class="px-3 text-left whitespace-nowrap">
              <slot name="actions" :row="row" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pager -->
    <div
      v-if="!loading && totalRows > 0"
      class="flex items-center justify-between gap-3 px-3 py-2.5 border-t border-slate-100 text-xs text-slate-500"
    >
      <span class="ltr-nums">{{ faNum(totalRows) }} ردیف</span>
      <div v-if="pageCount > 1" class="flex items-center gap-1">
        <button
          class="px-2 py-1 rounded-lg hover:bg-slate-100 disabled:opacity-40"
          :disabled="page === 1"
          @click="page = 1"
        >«</button>
        <button
          class="px-2 py-1 rounded-lg hover:bg-slate-100 disabled:opacity-40"
          :disabled="page === 1"
          @click="page--"
        >قبلی</button>
        <span class="px-2">{{ page }} / {{ pageCount }}</span>
        <button
          class="px-2 py-1 rounded-lg hover:bg-slate-100 disabled:opacity-40"
          :disabled="page >= pageCount"
          @click="page++"
        >بعدی</button>
        <button
          class="px-2 py-1 rounded-lg hover:bg-slate-100 disabled:opacity-40"
          :disabled="page >= pageCount"
          @click="page = pageCount"
        >»</button>
      </div>
    </div>
  </div>
</template>
