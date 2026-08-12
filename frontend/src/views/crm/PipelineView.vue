<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { crmApi, type Deal, type PipelineColumn } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num, rial } from "@/utils/format";
import CrmFilterBar from "@/components/crm/CrmFilterBar.vue";
import DealForm from "@/components/crm/DealForm.vue";
import Skeleton from "@/components/Skeleton.vue";

/**
 * مراحل فروش — the kanban board.
 *
 * Cards are draggable between stages; the drop calls /deals/<id>/move/, which
 * is also what writes the stage-event log the funnel and velocity reports are
 * built from. Dragging a card is therefore a reporting act, not just a UI one.
 */
const crm = useCrmStore();
const router = useRouter();

const columns = ref<PipelineColumn[]>([]);
const loading = ref(true);
const search = ref("");
const dragging = ref<Deal | null>(null);
const dragOver = ref<number | null>(null);
const lostPrompt = ref<{ deal: Deal; stage: number } | null>(null);
const lostReason = ref<number | "">("");
const lostNote = ref("");

async function load() {
  loading.value = true;
  try {
    columns.value = (await crmApi.pipeline({ ...crm.query, search: search.value })).columns;
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await crm.loadOptions(); await load(); });
watch(() => crm.query, load, { deep: true });

let searchTimer: number | undefined;
watch(search, () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(load, 350);
});

const totals = computed(() => ({
  count: columns.value.reduce((s, c) => s + c.count, 0),
  amount: columns.value.reduce((s, c) => s + c.amount, 0),
  weighted: columns.value.reduce((s, c) => s + c.weighted, 0),
}));

function onDragStart(deal: Deal) { dragging.value = deal; }
function onDragEnd() { dragging.value = null; dragOver.value = null; }

async function onDrop(col: PipelineColumn) {
  const deal = dragging.value;
  dragOver.value = null;
  dragging.value = null;
  if (!deal || deal.stage === col.id) return;

  // Losing a deal without a reason would quietly poison the "دلایل از دست رفتن"
  // report, so the reason is asked for at the moment of the drop.
  if (col.kind === "lost") {
    lostPrompt.value = { deal, stage: col.id };
    lostReason.value = "";
    lostNote.value = "";
    return;
  }
  await crmApi.moveDeal(deal.id, col.id);
  await load();
}

async function confirmLost() {
  if (!lostPrompt.value) return;
  await crmApi.moveDeal(lostPrompt.value.deal.id, lostPrompt.value.stage, {
    lost_reason: lostReason.value || undefined,
    lost_note: lostNote.value,
  });
  lostPrompt.value = null;
  await load();
}

const stageColor = (kind: string) =>
  kind === "won" ? "#22c55e" : kind === "lost" ? "#ef4444" : "#8b5cf6";

// Adding straight into a column is the natural gesture on a board, so the
// form opens pre-set to that stage.
const newDealStage = ref<number | null>(null);
const showForm = ref(false);

function addTo(stageId: number) {
  newDealStage.value = stageId;
  showForm.value = true;
}
async function onSaved() {
  showForm.value = false;
  await load();
}
</script>

<template>
  <div class="space-y-4">
    <CrmFilterBar />

    <!-- Board summary -->
    <div class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-center gap-5">
      <div>
        <p class="text-xs text-slate-400">معاملات باز</p>
        <p class="text-lg font-bold text-ink">{{ num(totals.count) }}</p>
      </div>
      <div>
        <p class="text-xs text-slate-400">ارزش معامله‌های باز</p>
        <p class="text-lg font-bold text-ink">{{ rial(totals.amount) }}</p>
      </div>
      <div>
        <p class="text-xs text-slate-400">ارزش وزنی (پیش‌بینی)</p>
        <p class="text-lg font-bold text-violet-600">{{ rial(totals.weighted) }}</p>
      </div>
      <span class="flex-1"></span>
      <input
        v-model="search" placeholder="جستجوی معامله یا مشتری…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 w-56"
      />
      <button
        v-if="crm.canEdit"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm shrink-0"
        @click="addTo(columns.find((c) => c.kind === 'open')?.id ?? 0)"
      >+ معامله جدید</button>
    </div>

    <DealForm
      v-if="showForm" :stage-id="newDealStage"
      @close="showForm = false" @saved="onSaved"
    />

    <!-- Board -->
    <div v-if="loading" class="flex gap-3 overflow-x-auto pb-2">
      <Skeleton v-for="i in 6" :key="i" class="h-96 w-72 shrink-0 rounded-card" />
    </div>

    <div v-else class="flex gap-3 overflow-x-auto pb-3" dir="rtl">
      <section
        v-for="col in columns" :key="col.id"
        class="w-72 shrink-0 bg-surface rounded-card shadow-soft flex flex-col max-h-[70vh] transition"
        :class="dragOver === col.id ? 'ring-2 ring-violet-400' : ''"
        @dragover.prevent="dragOver = col.id"
        @dragleave="dragOver === col.id && (dragOver = null)"
        @drop.prevent="onDrop(col)"
      >
        <header class="p-3 border-b border-slate-100">
          <div class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full shrink-0" :style="{ background: stageColor(col.kind) }"></span>
            <h3 class="text-sm font-semibold text-ink truncate flex-1">{{ col.name_fa }}</h3>
            <span class="text-xs bg-slate-100 text-slate-500 rounded-full px-2 py-0.5">{{ num(col.count) }}</span>
          </div>
          <p class="text-xs text-slate-400 mt-1">
            {{ rial(col.amount) }}
            <span v-if="col.probability_pct" class="text-slate-300">· احتمال {{ num(col.probability_pct) }}٪</span>
          </p>
        </header>

        <div class="flex-1 overflow-y-auto p-2 space-y-2">
          <article
            v-for="d in col.deals" :key="d.id"
            draggable="true"
            class="bg-slate-50 hover:bg-slate-100 rounded-xl p-3 cursor-grab active:cursor-grabbing transition border border-transparent hover:border-slate-200"
            :class="dragging?.id === d.id ? 'opacity-40' : ''"
            @dragstart="onDragStart(d)"
            @dragend="onDragEnd"
            @click="router.push({ name: 'crm-deal', params: { id: d.id } })"
          >
            <p class="text-sm text-ink font-medium leading-5 line-clamp-2">{{ d.title }}</p>
            <p class="text-xs text-slate-400 mt-1 truncate">{{ d.customer_name }}</p>
            <div class="flex items-center justify-between mt-2">
              <span class="text-xs font-semibold text-ink">{{ rial(d.amount_rial) }}</span>
              <span class="text-[10px] text-slate-400">{{ d.owner_name }}</span>
            </div>
            <div class="flex items-center gap-2 mt-1.5">
              <span class="text-[10px] text-slate-400">{{ d.opened_jalali }}</span>
              <span
                v-if="d.age_days > 30"
                class="text-[10px] bg-amber-100 text-amber-700 rounded-full px-1.5"
              >{{ num(d.age_days) }} روز</span>
            </div>
          </article>

          <button
            v-if="crm.canEdit && col.kind === 'open'"
            class="w-full text-xs text-slate-400 hover:text-ink hover:bg-slate-100 rounded-xl py-2 border border-dashed border-slate-200"
            @click="addTo(col.id)"
          >+ معامله</button>

          <p v-if="!col.deals.length" class="text-xs text-slate-300 text-center py-6">
            معامله‌ای در این مرحله نیست
          </p>
        </div>
      </section>
    </div>

    <!-- Lost-reason prompt -->
    <Teleport to="body">
      <div v-if="lostPrompt" class="fixed inset-0 z-[70] bg-black/40 flex items-center justify-center p-4" dir="rtl">
        <div class="bg-surface rounded-card shadow-pop w-full max-w-md p-5">
          <h3 class="font-bold text-ink">ثبت شکست معامله</h3>
          <p class="text-xs text-slate-400 mt-1">{{ lostPrompt.deal.title }}</p>

          <label class="block text-xs text-slate-500 mt-4 mb-1">دلیل از دست رفتن</label>
          <select v-model="lostReason" class="w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
            <option value="">— انتخاب کنید —</option>
            <option v-for="r in crm.options?.reasons" :key="r.id" :value="r.id">{{ r.name_fa }}</option>
          </select>

          <label class="block text-xs text-slate-500 mt-3 mb-1">توضیح (اختیاری)</label>
          <textarea v-model="lostNote" rows="2" class="w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none"></textarea>

          <div class="flex gap-2 mt-4">
            <button
              class="flex-1 bg-red-500 text-white rounded-xl py-2 text-sm disabled:opacity-50"
              :disabled="!lostReason" @click="confirmLost"
            >ثبت شکست</button>
            <button class="px-4 bg-slate-100 text-slate-600 rounded-xl py-2 text-sm" @click="lostPrompt = null">انصراف</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
