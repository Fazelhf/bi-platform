<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import {
  dashboardsApi,
  type Board,
  type BoardSummary,
  type Catalog,
  type QueryResult,
} from "@/api/dashboards";
import BoardCanvas from "@/components/boards/BoardCanvas.vue";
import WidgetEditor from "@/components/boards/WidgetEditor.vue";
import {
  bottomRow, compact, newUid, newWidget, toDraft, type DraftWidget,
} from "@/components/boards/layout";

/**
 * A section's report page — and, for the CEO, the place it is composed.
 *
 * The same component renders both states on purpose. A builder that previews
 * in one layout and publishes in another teaches the manager to distrust it;
 * here «حالت ویرایش» adds handles to the page they were already looking at,
 * and «انصراف» puts it back. Nothing is written until ذخیره.
 */
/** The route supplies this; the param is the fallback for a deep link. */
const props = defineProps<{ section?: string }>();

const route = useRoute();
const section = computed(
  () => props.section || String(route.params.section || "overview"),
);

const catalog = ref<Catalog | null>(null);
const boards = ref<BoardSummary[]>([]);
const board = ref<Board | null>(null);
const widgets = ref<DraftWidget[]>([]);
const results = ref<Record<string, { data?: QueryResult; error?: string }>>({});

const period = ref<number | null>(null);
const loading = ref(true);
const loadingData = ref(false);
const saving = ref(false);
const editing = ref(false);
const error = ref("");

const editorFor = ref<DraftWidget | null>(null);
const showAdd = ref(false);
const showSettings = ref(false);

const canEdit = computed(() => !!catalog.value?.can_edit);
const sectionMeta = computed(
  () => catalog.value?.sections.find((s) => s.key === section.value) ?? null,
);

/** Snapshot taken when edit mode opens, so «انصراف» is exact rather than a reload. */
let snapshot = "";

// ------------------------------------------------------------------ loading
async function loadAll() {
  loading.value = true;
  error.value = "";
  try {
    if (!catalog.value) catalog.value = await dashboardsApi.catalog();
    boards.value = await dashboardsApi.boards(section.value);
    const pick = boards.value.find((b) => b.is_default) ?? boards.value[0] ?? null;
    if (!pick) {
      board.value = null;
      widgets.value = [];
      return;
    }
    await openBoard(pick.id);
  } catch (e: any) {
    error.value = e?.response?.data?.detail || "بارگذاری داشبورد ممکن نشد.";
  } finally {
    loading.value = false;
  }
}

async function openBoard(id: number) {
  const full = await dashboardsApi.board(id);
  board.value = full;
  widgets.value = toDraft(full.widgets);
  // The board knows which month its own figures are in; the picker follows
  // that rather than opening on a month nobody has keyed yet.
  if (period.value === null) {
    period.value = full.default_period ?? catalog.value?.default_period ?? null;
  }
  await refresh();
}

async function refresh() {
  const items = widgets.value
    .filter((w) => w.kind !== "text" && w.kind !== "divider" && w.config?.dataset)
    .map((w) => ({ key: w.uid, config: w.config }));
  if (!items.length) {
    results.value = {};
    return;
  }
  loadingData.value = true;
  try {
    results.value = await dashboardsApi.queryBatch(items, period.value);
  } catch (e: any) {
    error.value = e?.response?.data?.detail || "محاسبه ارقام ممکن نشد.";
  } finally {
    loadingData.value = false;
  }
}

watch(section, () => {
  editing.value = false;
  period.value = null;
  board.value = null;
  loadAll();
}, { immediate: true });

watch(period, (value, old) => {
  if (old !== null && value !== old) refresh();
});

// ------------------------------------------------------------------ editing
function startEdit() {
  snapshot = JSON.stringify(widgets.value);
  editing.value = true;
}

function cancelEdit() {
  widgets.value = JSON.parse(snapshot);
  editing.value = false;
  showAdd.value = false;
  refresh();
}

async function save() {
  if (!board.value) return;
  saving.value = true;
  error.value = "";
  try {
    const saved = await dashboardsApi.saveLayout(board.value.id, widgets.value);
    board.value = saved;
    widgets.value = toDraft(saved.widgets);
    editing.value = false;
    await refresh();
  } catch (e: any) {
    const detail = e?.response?.data;
    error.value =
      typeof detail?.detail === "string"
        ? detail.detail
        : "ذخیره چیدمان ممکن نشد — ویجتی تنظیمات ناقص دارد.";
  } finally {
    saving.value = false;
  }
}

function addWidget(kind: string) {
  const widget = newWidget(kind, widgets.value);
  widgets.value = [...widgets.value, widget];
  showAdd.value = false;
  // Straight into the builder: an empty card on the canvas says nothing about
  // what it could become.
  if (kind !== "divider") editorFor.value = widget;
}

function editWidget(uid: string) {
  editorFor.value = widgets.value.find((w) => w.uid === uid) ?? null;
}

function applyWidget(updated: DraftWidget) {
  widgets.value = compact(
    widgets.value.map((w) => (w.uid === updated.uid ? { ...updated } : w)),
    updated.uid,
  );
  editorFor.value = null;
  refresh();
}

function removeWidget(uid: string) {
  widgets.value = compact(widgets.value.filter((w) => w.uid !== uid));
}

function duplicateWidget(uid: string) {
  const source = widgets.value.find((w) => w.uid === uid);
  if (!source) return;
  const copy: DraftWidget = {
    ...JSON.parse(JSON.stringify(source)),
    uid: newUid(),
    id: undefined,
    y: bottomRow(widgets.value),
    x: 0,
  };
  widgets.value = compact([...widgets.value, copy], copy.uid);
  refresh();
}

// ------------------------------------------------------------- board admin
const newTitle = ref("");

async function saveBoardSettings() {
  if (!board.value) return;
  await dashboardsApi.updateBoard(board.value.id, {
    title: board.value.title,
    subtitle: board.value.subtitle,
  });
  showSettings.value = false;
  boards.value = await dashboardsApi.boards(section.value);
}

async function createBoard() {
  if (!newTitle.value.trim()) return;
  const created = await dashboardsApi.createBoard({
    section: section.value,
    title: newTitle.value.trim(),
    is_default: !boards.value.length,
  });
  newTitle.value = "";
  boards.value = await dashboardsApi.boards(section.value);
  await openBoard(created.id);
  startEdit();
}

async function duplicateBoard() {
  if (!board.value) return;
  const copy = await dashboardsApi.duplicate(board.value.id);
  boards.value = await dashboardsApi.boards(section.value);
  await openBoard(copy.id);
}

async function makeDefault() {
  if (!board.value) return;
  await dashboardsApi.makeDefault(board.value.id);
  boards.value = await dashboardsApi.boards(section.value);
  board.value = { ...board.value, is_default: true };
}

async function removeBoard() {
  if (!board.value) return;
  await dashboardsApi.deleteBoard(board.value.id);
  board.value = null;
  await loadAll();
}

const control =
  "bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition";
</script>

<template>
  <div class="space-y-4">
    <!-- ===== header ===== -->
    <div class="flex items-start justify-between flex-wrap gap-2">
      <div class="min-w-0">
        <h2 class="text-lg font-bold text-ink">
          {{ board?.title || sectionMeta?.label || "گزارش و داشبورد" }}
        </h2>
        <p v-if="board?.subtitle" class="text-xs text-slate-400 mt-0.5">{{ board.subtitle }}</p>
      </div>

      <div class="flex items-center gap-2 flex-wrap no-print">
        <select
          v-if="boards.length > 1"
          :value="board?.id ?? ''" :class="control"
          @change="openBoard(Number(($event.target as HTMLSelectElement).value))"
        >
          <option v-for="b in boards" :key="b.id" :value="b.id">
            {{ b.title }}{{ b.is_default ? " ★" : "" }}
          </option>
        </select>

        <select v-model.number="period" :class="control">
          <option v-for="p in catalog?.periods ?? []" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>

        <template v-if="canEdit">
          <template v-if="editing">
            <button
              class="bg-panel text-white rounded-xl px-4 py-1.5 text-sm disabled:opacity-50"
              :disabled="saving" @click="save"
            >{{ saving ? "در حال ذخیره…" : "ذخیره چیدمان" }}</button>
            <button class="px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100 rounded-xl" @click="cancelEdit">
              انصراف
            </button>
          </template>
          <button
            v-else
            class="border border-slate-200 rounded-xl px-4 py-1.5 text-sm text-slate-600 hover:bg-slate-50 transition"
            @click="startEdit"
          >ویرایش چیدمان</button>
        </template>
      </div>
    </div>

    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">{{ error }}</p>

    <!-- ===== edit toolbar ===== -->
    <div
      v-if="editing"
      class="bg-brand-500/5 border border-brand-500/20 rounded-card px-4 py-3 flex flex-wrap items-center gap-2 no-print"
    >
      <div class="relative">
        <button class="bg-brand-500 text-white rounded-xl px-4 py-1.5 text-sm" @click="showAdd = !showAdd">
          + افزودن ویجت
        </button>
        <div
          v-if="showAdd"
          class="absolute z-30 mt-1 w-64 bg-surface rounded-card shadow-pop border border-slate-100 p-2 max-h-[320px] overflow-y-auto"
        >
          <template v-for="group in [...new Set((catalog?.widget_kinds ?? []).map((k) => k.group))]" :key="group">
            <p class="text-[11px] text-slate-300 px-2 pt-2 pb-1">{{ group }}</p>
            <button
              v-for="k in (catalog?.widget_kinds ?? []).filter((x) => x.group === group)" :key="k.key"
              class="w-full text-right px-2 py-1.5 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition"
              @click="addWidget(k.key)"
            >{{ k.label }}</button>
          </template>
        </div>
      </div>

      <button class="px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 rounded-xl" @click="showSettings = true">
        تنظیمات داشبورد
      </button>
      <button class="px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 rounded-xl" @click="duplicateBoard">
        رونوشت این داشبورد
      </button>
      <button
        v-if="board && !board.is_default"
        class="px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 rounded-xl" @click="makeDefault"
      >پیش‌فرض این بخش شود</button>

      <span class="flex-1"></span>
      <span class="text-xs text-slate-400">
        نوار بالای هر کارت را بکشید تا جابه‌جا شود؛ گوشه پایین برای تغییر اندازه.
      </span>
    </div>

    <!-- ===== canvas ===== -->
    <div v-if="loading" class="grid grid-cols-1 md:grid-cols-4 gap-3">
      <div v-for="i in 8" :key="i" class="bg-surface rounded-card shadow-soft h-32 animate-pulse"></div>
    </div>

    <div v-else-if="!board" class="bg-surface rounded-card shadow-soft p-10 text-center">
      <p class="text-sm text-slate-500">برای این بخش هنوز داشبوردی ساخته نشده است.</p>
      <div v-if="canEdit" class="mt-4 flex items-center justify-center gap-2">
        <input v-model="newTitle" :class="control" placeholder="عنوان داشبورد" @keyup.enter="createBoard" />
        <button class="bg-panel text-white rounded-xl px-4 py-1.5 text-sm" @click="createBoard">بساز</button>
      </div>
    </div>

    <template v-else>
      <BoardCanvas
        :widgets="widgets"
        :results="results"
        :loading="loadingData"
        :editing="editing"
        @update:widgets="widgets = $event"
        @edit="editWidget"
        @remove="removeWidget"
        @duplicate="duplicateWidget"
      />
      <p v-if="!widgets.length" class="text-sm text-slate-400 text-center py-10">
        این داشبورد خالی است.
        <template v-if="canEdit">
          «ویرایش چیدمان» را بزنید و اولین ویجت را اضافه کنید.
        </template>
      </p>
    </template>

    <!-- ===== widget builder ===== -->
    <WidgetEditor
      v-if="editorFor && catalog"
      :key="editorFor.uid"
      :widget="editorFor"
      :catalog="catalog"
      :period="period"
      @save="applyWidget"
      @close="editorFor = null"
    />

    <!-- ===== board settings ===== -->
    <Teleport to="body">
      <div
        v-if="showSettings && board"
        class="fixed inset-0 z-[68] bg-black/40 flex items-center justify-center p-4" dir="rtl"
        @click.self="showSettings = false"
      >
        <div class="bg-surface rounded-card shadow-pop w-full max-w-md p-5 space-y-3">
          <h3 class="font-bold text-ink">تنظیمات داشبورد</h3>
          <div>
            <label class="text-xs text-slate-400 mb-1 block">عنوان</label>
            <input v-model="board.title" :class="control" class="w-full" />
          </div>
          <div>
            <label class="text-xs text-slate-400 mb-1 block">زیرعنوان</label>
            <input v-model="board.subtitle" :class="control" class="w-full" />
          </div>
          <div class="flex items-center gap-2 pt-2">
            <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm" @click="saveBoardSettings">ذخیره</button>
            <button class="px-3 py-2 text-sm text-slate-500 hover:bg-slate-100 rounded-xl" @click="showSettings = false">
              انصراف
            </button>
            <span class="flex-1"></span>
            <button
              v-if="boards.length > 1"
              class="text-sm text-red-500 hover:bg-red-50 rounded-xl px-3 py-2" @click="removeBoard"
            >حذف داشبورد</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
