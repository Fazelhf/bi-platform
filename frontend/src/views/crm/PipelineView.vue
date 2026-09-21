<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { crmApi, type Deal, type ForecastBucket, type PipelineColumn } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num, rial } from "@/utils/format";
import CrmFilterBar from "@/components/crm/CrmFilterBar.vue";
import DealForm from "@/components/crm/DealForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import { toast } from "@/composables/useUi";

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
const forecast = ref<ForecastBucket[]>([]);
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
    const res = await crmApi.pipeline({ ...crm.query, search: search.value });
    columns.value = res.columns;
    forecast.value = res.forecast ?? [];
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await crm.loadOptions(); await load(); });
// Something was saved from the global «ثبت جدید» button over the top of this
// page; the list under it is now stale.
watch(() => crm.revision, load);

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

/**
 * Move a card on screen first, then tell the server.
 *
 * The board used to wait for the round trip and then reload every column,
 * so a drop sat for a second with the card back where it started — long
 * enough to look like the drop had failed and be tried again. Now the card
 * lands immediately and only snaps back, with a message, if the server
 * refuses.
 */
function moveLocally(deal: Deal, to: number): () => void {
  const from = columns.value.find((c) => c.deals.some((d) => d.id === deal.id));
  const target = columns.value.find((c) => c.id === to);
  if (!from || !target) return () => {};
  const snapshot = columns.value.map((c) => ({ ...c, deals: [...c.deals] }));

  const amount = Number(deal.amount_rial);
  from.deals = from.deals.filter((d) => d.id !== deal.id);
  from.count -= 1;
  from.amount -= amount;
  from.weighted -= (amount * from.probability_pct) / 100;
  // Won and lost cards leave the board — it only holds open deals.
  if (target.kind === "open") {
    target.deals = [{ ...deal, stage: to, stage_name: target.name_fa }, ...target.deals];
    target.count += 1;
    target.amount += amount;
    target.weighted += (amount * target.probability_pct) / 100;
  }
  return () => { columns.value = snapshot; };
}

async function commitMove(deal: Deal, to: number, extra: Record<string, any> = {}) {
  const undo = moveLocally(deal, to);
  try {
    await crmApi.moveDeal(deal.id, to, extra);
    const target = columns.value.find((c) => c.id === to);
    if (target?.kind === "won") toast.success(`«${deal.title}» موفق ثبت شد`);
    // Totals and the forecast strip are server arithmetic; refresh them
    // quietly rather than re-deriving them here.
    const res = await crmApi.pipeline({ ...crm.query, search: search.value });
    columns.value = res.columns;
    forecast.value = res.forecast ?? [];
  } catch (e: any) {
    undo();
    toast.error(e?.response?.data?.detail ?? "جابه‌جایی انجام نشد.");
  }
}

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
  await commitMove(deal, col.id);
}

async function confirmLost() {
  if (!lostPrompt.value) return;
  const { deal, stage } = lostPrompt.value;
  lostPrompt.value = null;
  await commitMove(deal, stage, {
    lost_reason: lostReason.value || undefined,
    lost_note: lostNote.value,
  });
}

// ---- reading the board ------------------------------------------------------
/** A deal nobody has touched in this many days is flagged on its card. */
const IDLE_WARN = 14;
const IDLE_BAD = 30;

function idleClass(days: number | null | undefined): string {
  if (days == null || days < IDLE_WARN) return "";
  return days >= IDLE_BAD ? "bg-red-100 text-red-600" : "bg-amber-100 text-amber-700";
}

type SortKey = "recent" | "amount" | "idle";
const sortBy = ref<SortKey>("amount");
const SORTS: { key: SortKey; label: string }[] = [
  { key: "amount", label: "بزرگ‌ترین" },
  { key: "idle", label: "راکدترین" },
  { key: "recent", label: "جدیدترین" },
];

function sorted(deals: Deal[]): Deal[] {
  const list = [...deals];
  if (sortBy.value === "amount") return list.sort((a, b) => Number(b.amount_rial) - Number(a.amount_rial));
  if (sortBy.value === "idle") return list.sort((a, b) => (b.idle_days ?? 0) - (a.idle_days ?? 0));
  return list.sort((a, b) => a.age_days - b.age_days);
}

/** Only the open stages carry cards, so only they share the pipeline. */
function share(col: PipelineColumn): number {
  return totals.value.amount ? (col.amount / totals.value.amount) * 100 : 0;
}

const idleCount = computed(() =>
  columns.value.reduce((s, c) => s + c.deals.filter((d) => (d.idle_days ?? 0) >= IDLE_WARN).length, 0),
);

const FORECAST_TONE: Record<string, string> = {
  overdue: "text-red-600", this: "text-emerald-600", next: "text-sky-600",
  later: "text-slate-500", none: "text-slate-400",
};

/** While a card is held, the closing stages are offered as a strip too —
 *  on a wide board they are otherwise a sideways scroll away. */
const closingStages = computed(() => columns.value.filter((c) => c.kind !== "open"));

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
      <div v-if="idleCount">
        <p class="text-xs text-slate-400">بدون پیگیری {{ num(IDLE_WARN) }}+ روز</p>
        <p class="text-lg font-bold text-amber-600">{{ num(idleCount) }}</p>
      </div>
      <span class="flex-1"></span>
      <div class="flex rounded-xl bg-slate-100 p-0.5">
        <button
          v-for="s in SORTS" :key="s.key"
          class="text-xs px-3 py-1.5 rounded-lg transition"
          :class="sortBy === s.key ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-400'"
          @click="sortBy = s.key"
        >{{ s.label }}</button>
      </div>
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

    <!-- Forecast: when the weighted value is expected to land -->
    <div v-if="forecast.length && totals.count" class="bg-surface rounded-card shadow-soft p-4">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold text-ink">پیش‌بینی بسته‌شدن</h3>
        <span class="text-[11px] text-slate-400">ارزش وزنی بر اساس تاریخ پیش‌بینی‌شده‌ی هر معامله</span>
      </div>
      <div class="flex h-2.5 rounded-full overflow-hidden bg-slate-100 gap-0.5 mb-3">
        <div
          v-for="b in forecast.filter((x) => x.weighted > 0)" :key="b.key"
          class="h-full"
          :class="{ overdue: 'bg-red-400', this: 'bg-emerald-500', next: 'bg-sky-500', later: 'bg-slate-400', none: 'bg-slate-300' }[b.key]"
          :style="{ width: (b.weighted / (totals.weighted || 1)) * 100 + '%' }"
          :title="b.label"
        ></div>
      </div>
      <div class="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <div v-for="b in forecast" :key="b.key" class="rounded-xl bg-slate-50 px-3 py-2">
          <p class="text-[11px] text-slate-400 truncate">{{ b.label }}</p>
          <p class="text-sm font-bold ltr-nums" :class="FORECAST_TONE[b.key]">{{ rial(b.weighted) }}</p>
          <p class="text-[10px] text-slate-400">{{ num(b.count) }} معامله</p>
        </div>
      </div>
      <p v-if="forecast.find((b) => b.key === 'none')?.count" class="text-[11px] text-amber-600 mt-2">
        {{ num(forecast.find((b) => b.key === "none")!.count) }} معامله تاریخ بسته‌شدن ندارند — پیش‌بینی بدون آن‌ها ناقص است.
      </p>
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
          <div v-if="col.kind === 'open'" class="h-1 rounded-full bg-slate-100 overflow-hidden mt-2" :title="`سهم از کل کاریز`">
            <div class="h-full rounded-full bg-violet-400 transition-all duration-500" :style="{ width: share(col) + '%' }"></div>
          </div>
          <p v-if="col.kind === 'open' && col.weighted" class="text-[10px] text-violet-500 mt-1">وزنی {{ rial(col.weighted) }}</p>
        </header>

        <div class="flex-1 overflow-y-auto p-2 space-y-2">
          <article
            v-for="d in sorted(col.deals)" :key="d.id"
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
              <span v-if="crm.seesAll" class="text-[10px] text-slate-400">{{ d.owner_name }}</span>
            </div>
            <div class="flex items-center gap-1.5 mt-1.5 flex-wrap">
              <span class="text-[10px] text-slate-400" :title="`ایجاد: ${d.opened_jalali}`">{{ num(d.age_days) }} روز عمر</span>
              <span
                v-if="idleClass(d.idle_days)"
                class="text-[10px] rounded-full px-1.5"
                :class="idleClass(d.idle_days)"
                :title="'آخرین فعالیت'"
              >{{ num(d.idle_days ?? 0) }} روز بی‌پیگیری</span>
              <span v-if="d.expected_close_date" class="text-[10px] text-sky-600">· موعد {{ d.expected_close_date }}</span>
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

    <!-- While a card is held: the closing stages, always within reach -->
    <Transition name="fade">
      <div
        v-if="dragging && closingStages.length"
        class="fixed bottom-4 inset-x-4 z-50 flex justify-center gap-3 pointer-events-none"
        dir="rtl"
      >
        <div
          v-for="c in closingStages" :key="`drop-${c.id}`"
          class="pointer-events-auto w-56 rounded-2xl border-2 border-dashed px-4 py-4 text-center text-sm font-semibold shadow-pop transition"
          :class="[
            c.kind === 'won' ? 'bg-emerald-50 border-emerald-400 text-emerald-700' : 'bg-red-50 border-red-400 text-red-600',
            dragOver === c.id ? 'scale-105' : '',
          ]"
          @dragover.prevent="dragOver = c.id"
          @dragleave="dragOver === c.id && (dragOver = null)"
          @drop.prevent="onDrop(c)"
        >
          {{ c.kind === "won" ? "✓" : "✕" }} {{ c.name_fa }}
        </div>
      </div>
    </Transition>

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
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
