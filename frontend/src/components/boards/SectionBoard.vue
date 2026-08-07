<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  dashboardsApi,
  type Board,
  type Catalog,
  type QueryResult,
} from "@/api/dashboards";
import BoardCanvas from "./BoardCanvas.vue";
import DrillDrawer from "./DrillDrawer.vue";
import WidgetEditor from "./WidgetEditor.vue";
import {
  bottomRow, compact, newUid, newWidget, toDraft, type DraftWidget,
} from "./layout";
import { toast } from "@/composables/useUi";

/**
 * A section's composed board, rendered — and edited — inside that section's
 * own page.
 *
 * Report and dashboard are one page, which is what they were before this
 * feature existed. The hand-built dashboard above stays as it is; it holds
 * things a builder cannot express (the alert list, the channel mix bar, the
 * week strip). What the CEO composes appears underneath it.
 *
 * Editing happens *here*, not on a separate screen. Sending the one person
 * who may rearrange a page somewhere else to do it means they never see the
 * page they are rearranging, and everyone else opens a dashboard with no sign
 * that it can be changed at all. «تنظیمات سایت ← داشبوردها» keeps what it is
 * good at — making, naming, duplicating and deleting boards — and the arranging
 * happens where the cards are.
 *
 * Renders nothing when the section has no board and nobody may make one, so a
 * page nobody has composed for looks untouched rather than broken.
 */
const props = defineProps<{
  section: string;
  /** The host page's own month selector, so both halves show one period. */
  period?: number | null;
}>();

const catalog = ref<Catalog | null>(null);
const board = ref<Board | null>(null);
const widgets = ref<DraftWidget[]>([]);
const results = ref<Record<string, { data?: QueryResult; error?: string }>>({});
const loading = ref(false);
const saving = ref(false);
const editing = ref(false);
const showAdd = ref(false);
const editorFor = ref<DraftWidget | null>(null);
const drill = ref<{ widget: DraftWidget; key: string; label: string } | null>(null);

const canEdit = computed(() => !!catalog.value?.can_edit);
// An empty board still shows for an editor — otherwise the one person who
// could fill it is the only one who cannot see that it exists.
const show = computed(
  () => !!board.value && (widgets.value.length > 0 || canEdit.value),
);

/** Taken when edit mode opens, so «انصراف» is exact rather than a reload. */
let snapshot = "";

async function load() {
  editing.value = false;
  try {
    if (!catalog.value) catalog.value = await dashboardsApi.catalog();
    const list = await dashboardsApi.boards(props.section);
    const pick = list.find((b) => b.is_default) ?? list[0];
    if (!pick) {
      board.value = null;
      widgets.value = [];
      return;
    }
    const full = await dashboardsApi.board(pick.id);
    board.value = full;
    widgets.value = toDraft(full.widgets);
    await refresh();
  } catch {
    // A section whose board cannot be read is a section that simply shows its
    // hand-built dashboard — never an error banner on someone else's page.
    board.value = null;
    widgets.value = [];
  }
}

async function refresh() {
  const items = widgets.value
    .filter((w) => w.kind !== "text" && w.kind !== "divider" && w.config?.dataset)
    .map((w) => ({ key: w.uid, config: w.config }));
  if (!items.length) {
    results.value = {};
    return;
  }
  loading.value = true;
  try {
    results.value = await dashboardsApi.queryBatch(items, props.period ?? null);
  } finally {
    loading.value = false;
  }
}

watch(() => props.section, load, { immediate: true });
// The host page owns the month; following it keeps one period on one page.
watch(() => props.period, () => board.value && refresh());

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
  try {
    const saved = await dashboardsApi.saveLayout(board.value.id, widgets.value);
    board.value = saved;
    widgets.value = toDraft(saved.widgets);
    editing.value = false;
    showAdd.value = false;
    await refresh();
    toast.success("چیدمان ذخیره شد.");
  } catch (e: any) {
    toast.error(
      e?.response?.data?.detail || "ذخیره نشد — ویجتی تنظیمات ناقص دارد.",
    );
  } finally {
    saving.value = false;
  }
}

function addWidget(kind: string) {
  const widget = newWidget(kind, widgets.value);
  widgets.value = [...widgets.value, widget];
  showAdd.value = false;
  // Straight into the builder: an empty card says nothing about what it could
  // become.
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

function openDrill(uid: string, key: string, label: string) {
  const widget = widgets.value.find((w) => w.uid === uid);
  if (widget) drill.value = { widget, key, label };
}

const kindGroups = computed(() => [
  ...new Set((catalog.value?.widget_kinds ?? []).map((k) => k.group)),
]);
</script>

<template>
  <section v-if="show" class="space-y-3 pt-2">
    <div class="flex items-center justify-between gap-2 flex-wrap">
      <div class="min-w-0">
        <h3 class="text-sm font-bold text-ink">{{ board!.title }}</h3>
        <p v-if="board!.subtitle" class="text-xs text-slate-400">{{ board!.subtitle }}</p>
      </div>

      <div v-if="canEdit" class="flex items-center gap-2 no-print">
        <template v-if="editing">
          <button
            class="bg-panel text-white rounded-xl px-4 py-1.5 text-sm disabled:opacity-50"
            :disabled="saving" @click="save"
          >{{ saving ? "در حال ذخیره…" : "ذخیره چیدمان" }}</button>
          <button
            class="px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100 rounded-xl"
            @click="cancelEdit"
          >انصراف</button>
        </template>
        <button
          v-else
          class="border border-slate-200 rounded-xl px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50 transition"
          @click="startEdit"
        >ویرایش چیدمان</button>
      </div>
    </div>

    <!-- Edit toolbar -->
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
          <template v-for="group in kindGroups" :key="group">
            <p class="text-[11px] text-slate-300 px-2 pt-2 pb-1">{{ group }}</p>
            <button
              v-for="k in (catalog?.widget_kinds ?? []).filter((x) => x.group === group)"
              :key="k.key"
              class="w-full text-right px-2 py-1.5 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition"
              @click="addWidget(k.key)"
            >{{ k.label }}</button>
          </template>
        </div>
      </div>

      <span class="flex-1"></span>
      <span class="text-xs text-slate-400">
        نوار بالای هر کارت را بکشید تا جابه‌جا شود؛ گوشه پایین برای تغییر اندازه.
      </span>
    </div>

    <BoardCanvas
      :widgets="widgets"
      :results="results"
      :loading="loading"
      :editing="editing"
      @update:widgets="widgets = $event"
      @edit="editWidget"
      @remove="removeWidget"
      @duplicate="duplicateWidget"
      @drill="openDrill"
    />

    <p v-if="editing && !widgets.length" class="text-sm text-slate-400 text-center py-8">
      این بخش هنوز ویجتی ندارد — «افزودن ویجت» را بزنید.
    </p>

    <WidgetEditor
      v-if="editorFor && catalog"
      :key="editorFor.uid"
      :widget="editorFor"
      :catalog="catalog"
      :period="period ?? null"
      @save="applyWidget"
      @close="editorFor = null"
    />

    <DrillDrawer
      v-if="drill"
      :config="drill.widget.config"
      :data-key="drill.key"
      :label="drill.label"
      :title="drill.widget.title"
      :period="period ?? null"
      @close="drill = null"
    />
  </section>
</template>
