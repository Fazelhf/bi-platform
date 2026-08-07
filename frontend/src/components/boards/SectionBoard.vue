<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  dashboardsApi,
  type Board,
  type QueryResult,
} from "@/api/dashboards";
import BoardCanvas from "./BoardCanvas.vue";
import DrillDrawer from "./DrillDrawer.vue";
import { toDraft, type DraftWidget } from "./layout";

/**
 * A section's composed board, rendered *inside* that section's own page.
 *
 * Report and dashboard are one page, which is what they were before this
 * feature existed. Splitting them had given every department two menu rows
 * over the same numbers, and no way to tell from the menu which of the two
 * answered a given question.
 *
 * So the hand-built dashboard stays exactly as it is — it holds things a
 * builder cannot express (the alert list, the channel mix bar, the week
 * strip) — and whatever the CEO composes appears underneath it on the same
 * page. Read-only here: arranging happens in «تنظیمات سایت ← داشبوردها»,
 * because a control only one person may use does not belong on a page the
 * whole department opens.
 *
 * Renders nothing at all when the section has no board or an empty one, so a
 * page that nobody has composed for looks untouched rather than broken.
 */
const props = defineProps<{
  section: string;
  /** The host page's own month selector, so both halves show one period. */
  period?: number | null;
}>();

const board = ref<Board | null>(null);
const widgets = ref<DraftWidget[]>([]);
const results = ref<Record<string, { data?: QueryResult; error?: string }>>({});
const loading = ref(false);
const drill = ref<{ widget: DraftWidget; key: string; label: string } | null>(null);

const show = computed(() => !!board.value && widgets.value.length > 0);

async function load() {
  try {
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

function openDrill(uid: string, key: string, label: string) {
  const widget = widgets.value.find((w) => w.uid === uid);
  if (widget) drill.value = { widget, key, label };
}
</script>

<template>
  <section v-if="show" class="space-y-3 pt-2">
    <div class="flex items-baseline justify-between gap-2 flex-wrap">
      <h3 class="text-sm font-bold text-ink">{{ board!.title }}</h3>
      <p v-if="board!.subtitle" class="text-xs text-slate-400">{{ board!.subtitle }}</p>
    </div>

    <BoardCanvas
      :widgets="widgets"
      :results="results"
      :loading="loading"
      :editing="false"
      @drill="openDrill"
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
