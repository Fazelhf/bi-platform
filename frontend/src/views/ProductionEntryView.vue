<script setup lang="ts">
import { onMounted, ref, shallowRef, watch } from "vue";
import { AgGridVue } from "ag-grid-vue3";
import type { CellValueChangedEvent, ColDef, GridApi, GridReadyEvent } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import { salesApi } from "@/api/sales";
import { productionApi } from "@/api/production";
import type { Period, ProductionRow } from "@/types";

const periods = ref<Period[]>([]);
const selectedPeriod = ref<number | null>(null);
const rows = shallowRef<ProductionRow[]>([]);
const gridApi = ref<GridApi | null>(null);
const saving = ref("");

const STATUS_FA: Record<string, string> = {
  draft: "پیش‌نویس", submitted: "ارسال‌شده", approved: "تأییدشده", rejected: "ردشده",
  needs_revision: "نیازمند اصلاح",
};

type PField = ColDef<ProductionRow>["field"];
const numCol = (field: PField, header: string): ColDef<ProductionRow> => ({
  field,
  headerName: header,
  editable: (p) => p.data?.status !== "approved",
  type: "numericColumn",
  valueParser: (p) => Number(p.newValue) || 0,
  cellClass: "ltr-nums",
  minWidth: 110,
});

const columnDefs: ColDef<ProductionRow>[] = [
  { field: "machine_name", headerName: "خط تولید", pinned: "right", editable: false, minWidth: 110 },
  numCol("active_shifts", "شیفت فعال"),
  numCol("output_units", "تولید"),
  numCol("waste_pct", "ضایعات ٪"),
  numCol("repair_count", "تعمیری"),
  numCol("downtime_breakdown_shifts", "خواب/خرابی"),
  numCol("downtime_sizechange_shifts", "خواب/تغییر سایز"),
  numCol("downtime_nowork_shifts", "خواب/عدم سفارش"),
  {
    field: "status", headerName: "وضعیت", editable: false, minWidth: 110,
    cellRenderer: (p: { value: string }) => {
      const c: Record<string, string> = {
        draft: "#94a3b8",
        needs_revision: "#d97706", submitted: "#d97706", approved: "#16a34a", rejected: "#dc2626",
      };
      return `<span style="color:${c[p.value] ?? "#64748b"};font-weight:600">${STATUS_FA[p.value] ?? p.value}</span>`;
    },
  },
  {
    headerName: "اقدام", editable: false, minWidth: 170,
    cellRenderer: (p: { data: ProductionRow }) => {
      const s = p.data.status;
      const btn = (a: string, l: string, c: string) =>
        `<button data-action="${a}" style="margin:0 2px;padding:2px 8px;border-radius:6px;border:1px solid ${c};color:${c};background:#fff;cursor:pointer;font-size:12px">${l}</button>`;
      if (s === "draft" || s === "rejected" || s === "needs_revision") return btn("submit", "ارسال", "#2b57d4");
      if (s === "submitted") return btn("approve", "تأیید", "#16a34a") + btn("reject", "رد", "#dc2626");
      return "";
    },
  },
];

const defaultColDef: ColDef = { resizable: true, sortable: true, suppressMovable: true };

function onGridReady(e: GridReadyEvent) { gridApi.value = e.api; }

async function onCellValueChanged(e: CellValueChangedEvent<ProductionRow>) {
  const field = e.colDef.field as keyof ProductionRow;
  saving.value = `در حال ذخیره ${e.data.machine_name}…`;
  try {
    const updated = await productionApi.updateRow(e.data.id, { [field]: e.newValue } as never);
    e.data.status = updated.status;
    gridApi.value?.refreshCells({ rowNodes: [e.node!], force: true });
    saving.value = "ذخیره شد ✓";
  } catch {
    saving.value = "خطا در ذخیره";
  }
}

async function onCellClicked(e: { event: Event; data: ProductionRow }) {
  const action = (e.event.target as HTMLElement)?.dataset?.action as
    | "submit" | "approve" | "reject" | undefined;
  if (!action) return;
  saving.value = "…";
  try {
    const updated = await productionApi.transition(e.data.id, action);
    e.data.status = updated.status;
    gridApi.value?.refreshCells({ force: true });
    saving.value = "انجام شد ✓";
  } catch {
    saving.value = "اجازه دسترسی ندارید یا خطا رخ داد";
  }
}

async function load() {
  if (!selectedPeriod.value) return;
  rows.value = await productionApi.rows(selectedPeriod.value);
}

onMounted(async () => {
  periods.value = await salesApi.periods();
  selectedPeriod.value = periods.value[0]?.id ?? null;
  await load();
});
watch(selectedPeriod, load);
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-ink">ورود اطلاعات تولید</h1>
      <div class="flex items-center gap-3">
        <span class="text-sm text-slate-500">{{ saving }}</span>
        <select v-model.number="selectedPeriod" class="border border-slate-200 rounded-xl px-3 py-1.5 bg-surface text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition">
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <p class="text-sm text-slate-500">
      هر خط تولید یک ردیف است. مقادیر شیفت، تولید، ضایعات و توقفات را وارد کنید؛
      شاخص‌ها پس از تأیید مدیر به‌صورت خودکار محاسبه می‌شوند.
    </p>

    <AgGridVue
      class="ag-theme-quartz"
      style="height: 480px; width: 100%"
      :columnDefs="columnDefs"
      :rowData="rows"
      :defaultColDef="defaultColDef"
      :enableRtl="true"
      :animateRows="true"
      @grid-ready="onGridReady"
      @cell-value-changed="onCellValueChanged"
      @cell-clicked="onCellClicked"
    />
  </div>
</template>
