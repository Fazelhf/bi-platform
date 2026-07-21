<script setup lang="ts">
import { onMounted, ref, shallowRef, watch } from "vue";
import { AgGridVue } from "ag-grid-vue3";
import type { CellValueChangedEvent, ColDef, GridApi, GridReadyEvent } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import { salesApi } from "@/api/sales";
import type { Period, SalesMonthly } from "@/types";

const props = withDefaults(
  defineProps<{ channel?: string; title?: string }>(),
  { channel: "team", title: "ورود اطلاعات فروش" },
);

const periods = ref<Period[]>([]);
const selectedPeriod = ref<number | null>(null);
const rows = shallowRef<SalesMonthly[]>([]);
const gridApi = ref<GridApi | null>(null);
const saving = ref("");

const STATUS_FA: Record<string, string> = {
  draft: "پیش‌نویس",
  submitted: "ارسال‌شده",
  approved: "تأییدشده",
  rejected: "ردشده",
};

type SalesField = ColDef<SalesMonthly>["field"];

const numCol = (field: SalesField, header: string): ColDef<SalesMonthly> => ({
  field,
  headerName: header,
  editable: (p) => p.data?.status !== "approved",
  type: "numericColumn",
  valueParser: (p) => Number(p.newValue) || 0,
  cellClass: "ltr-nums",
  minWidth: 120,
});

const columnDefs: ColDef<SalesMonthly>[] = [
  { field: "employee_name", headerName: "فروشنده", pinned: "right", editable: false, minWidth: 130 },
  numCol("revenue_rial", "فروش ریالی"),
  numCol("invoice_count", "تعداد فاکتور"),
  numCol("active_customers", "مشتری فعال"),
  numCol("new_customers", "مشتری جدید"),
  numCol("profit_rial", "سود فروش"),
  numCol("cost_rial", "هزینه فروش"),
  numCol("target_rial", "تارگت"),
  numCol("calls", "تعداد تماس"),
  {
    field: "status",
    headerName: "وضعیت",
    editable: false,
    minWidth: 110,
    cellRenderer: (p: { value: string }) => {
      const colors: Record<string, string> = {
        draft: "#94a3b8",
        submitted: "#d97706",
        approved: "#16a34a",
        rejected: "#dc2626",
      };
      return `<span style="color:${colors[p.value] ?? "#64748b"};font-weight:600">${
        STATUS_FA[p.value] ?? p.value
      }</span>`;
    },
  },
  {
    headerName: "اقدام",
    editable: false,
    minWidth: 180,
    cellRenderer: (p: { data: SalesMonthly }) => {
      const s = p.data.status;
      const btn = (a: string, label: string, color: string) =>
        `<button data-action="${a}" style="margin:0 2px;padding:2px 8px;border-radius:6px;border:1px solid ${color};color:${color};background:#fff;cursor:pointer;font-size:12px">${label}</button>`;
      if (s === "draft" || s === "rejected") return btn("submit", "ارسال", "#2b57d4");
      if (s === "submitted")
        return btn("approve", "تأیید", "#16a34a") + btn("reject", "رد", "#dc2626");
      return "";
    },
  },
];

const defaultColDef: ColDef = { resizable: true, sortable: true, suppressMovable: true };

function onGridReady(e: GridReadyEvent) {
  gridApi.value = e.api;
}

async function onCellValueChanged(e: CellValueChangedEvent<SalesMonthly>) {
  const field = e.colDef.field as keyof SalesMonthly;
  saving.value = `در حال ذخیره ${e.data.employee_name}…`;
  try {
    const updated = await salesApi.updateRow(e.data.id, { [field]: e.newValue } as never);
    // Server resets an edited row to draft — reflect that.
    e.data.status = updated.status;
    gridApi.value?.refreshCells({ rowNodes: [e.node!], force: true });
    saving.value = "ذخیره شد ✓";
  } catch {
    saving.value = "خطا در ذخیره";
  }
}

async function onCellClicked(e: {
  event: Event;
  data: SalesMonthly;
  node: unknown;
}) {
  const target = e.event.target as HTMLElement;
  const action = target?.dataset?.action as "submit" | "approve" | "reject" | undefined;
  if (!action) return;
  saving.value = "…";
  try {
    const updated = await salesApi.transition(e.data.id, action);
    e.data.status = updated.status;
    gridApi.value?.refreshCells({ force: true });
    saving.value = "انجام شد ✓";
  } catch {
    saving.value = "اجازه دسترسی ندارید یا خطا رخ داد";
  }
}

async function load() {
  if (!selectedPeriod.value) return;
  rows.value = await salesApi.salesRows(selectedPeriod.value, props.channel);
}

onMounted(async () => {
  periods.value = await salesApi.periods();
  selectedPeriod.value = periods.value[0]?.id ?? null;
  await load();
});

watch([selectedPeriod, () => props.channel], load);
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-slate-800">{{ title }}</h1>
      <div class="flex items-center gap-3">
        <span class="text-sm text-slate-500">{{ saving }}</span>
        <select
          v-model.number="selectedPeriod"
          class="border border-slate-300 rounded-lg px-3 py-1.5 bg-white text-sm"
        >
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <p class="text-sm text-slate-500">
      سلول‌ها را مانند اکسل ویرایش کنید. هر تغییر بلافاصله ذخیره می‌شود و ردیف به
      حالت «پیش‌نویس» بازمی‌گردد تا دوباره ارسال و تأیید شود.
    </p>

    <AgGridVue
      class="ag-theme-quartz"
      style="height: 560px; width: 100%"
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
