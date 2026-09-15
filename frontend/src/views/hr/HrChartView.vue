<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { hrApi, type Chart, type ChartNode, type OrgUnit, type Seat } from "@/api/hr";
import { confirm, toast } from "@/composables/useUi";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import ChartUnit from "@/components/hr/ChartUnit.vue";
import UnitForm from "@/components/hr/UnitForm.vue";
import PositionForm from "@/components/hr/PositionForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * چارت سازمانی — the company as it is, and the source every other list reads.
 *
 * At this company's size (eight departments, one of them ten sections and
 * thirty seats deep) drawing everything at once is a wall: cards of wildly
 * different heights in a grid leave holes, and the eye has nothing to follow.
 * So the page is drawn in two levels:
 *
 *   1. the top of the chart and one row of equal department tiles — head,
 *      headcount, vacancies — which is the whole company at a glance;
 *   2. the one department you open, full width, its sections flowing in
 *      balanced columns.
 *
 * Search opens the department it finds.
 */
const router = useRouter();

const chart = ref<Chart | null>(null);
const loading = ref(true);
const query = ref("");
const importing = ref(false);
const openId = ref<number | null>(null);

async function load() {
  loading.value = true;
  try {
    chart.value = await hrApi.chart();
    if (openId.value === null || !flatUnits.value.some((u) => u.id === openId.value)) {
      openId.value = departments.value[0]?.id ?? null;
    }
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const roots = computed(() => chart.value?.roots ?? []);
const stats = computed(() => chart.value?.stats);

const flatUnits = computed<OrgUnit[]>(() => {
  const out: OrgUnit[] = [];
  const walk = (n: ChartNode) => { out.push(n); n.children.forEach(walk); };
  roots.value.forEach(walk);
  return out;
});

const TOP = new Set(["board", "executive"]);

const topChain = computed<ChartNode[]>(() => {
  const chain: ChartNode[] = [];
  let node: ChartNode | undefined = roots.value.find((r) => TOP.has(r.kind));
  while (node && TOP.has(node.kind)) {
    chain.push(node);
    node = node.children.find((c) => TOP.has(c.kind));
  }
  return chain;
});

const apex = computed(() => topChain.value[topChain.value.length - 1] ?? null);
const staff = computed(() => apex.value?.children.filter((c) => c.kind === "staff") ?? []);
const departments = computed(() => {
  const inChain = new Set(topChain.value.map((n) => n.id));
  const under = apex.value?.children.filter((c) => c.kind !== "staff" && !inChain.has(c.id)) ?? [];
  return [...under, ...roots.value.filter((r) => !inChain.has(r.id))];
});
const opened = computed(() => departments.value.find((d) => d.id === openId.value) ?? null);

// ---- figures per department -----------------------------------------------
function allSeats(n: ChartNode): Seat[] {
  return [...n.positions, ...n.children.flatMap(allSeats)];
}
function tile(n: ChartNode) {
  const seats = allSeats(n);
  return {
    head: n.positions.find((p) => p.is_head) ?? null,
    people: new Set(seats.filter((s) => s.holder).map((s) => s.holder)).size,
    vacant: seats.filter((s) => !s.holder).length,
    sections: n.children.length,
  };
}

// ---- search -----------------------------------------------------------------
function matches(n: ChartNode, q: string): boolean {
  return n.name_fa.includes(q)
    || n.positions.some((p) => `${p.holder_name} ${p.title}`.includes(q))
    || n.children.some((c) => matches(c, q));
}
const q = computed(() => query.value.trim());
const matching = computed(() =>
  q.value ? new Set(departments.value.filter((d) => matches(d, q.value)).map((d) => d.id)) : null,
);
watch(matching, (set) => {
  if (set && set.size && openId.value !== null && !set.has(openId.value)) {
    openId.value = [...set][0];
  }
});
const topHit = (n: ChartNode) => !!q.value && matches({ ...n, children: [] }, q.value);

// ---- forms ------------------------------------------------------------------
const unitForm = ref<{ unit: OrgUnit | null; parentId: number | null } | null>(null);
const seatForm = ref<{ seat: Seat | null; unit: ChartNode } | null>(null);

const editUnit = (node: ChartNode) => { unitForm.value = { unit: node, parentId: node.parent }; };
const addUnit = (parent: ChartNode | null) => { unitForm.value = { unit: null, parentId: parent?.id ?? null }; };
const editSeat = (seat: Seat, unit: ChartNode) => { seatForm.value = { seat, unit }; };
const addSeat = (unit: ChartNode) => { seatForm.value = { seat: null, unit }; };
function afterSave() {
  unitForm.value = null;
  seatForm.value = null;
  load();
}

async function importChart() {
  const ok = await confirm({
    title: "ساخت چارت سازمانی",
    message:
      "چارت سازمانی شرکت با همه واحدها و سمت‌ها ساخته می‌شود. افرادی که قبلا در سامانه بوده‌اند " +
      "با نامشان پیدا و در سمت خود قرار می‌گیرند و بقیه ثبت می‌شوند. کارشناسانی که در چارت نیستند " +
      "از برگه‌های فروش خارج می‌شوند اما آمار گذشته‌شان باقی می‌ماند.",
  });
  if (!ok) return;
  importing.value = true;
  try {
    const res = await hrApi.importChart();
    toast.success(`چارت ساخته شد: ${num(res.units)} واحد، ${num(res.positions)} سمت.`);
    openId.value = null;
    await load();
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    importing.value = false;
  }
}

const initial = (name: string) => (name ? name.trim()[0] : "؟");
const headOf = (n: ChartNode) => n.positions.find((p) => p.is_head) ?? n.positions[0] ?? null;
</script>

<template>
  <div class="space-y-4">
    <!-- Toolbar -->
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <input
        v-model="query" placeholder="جستجوی نام یا سمت…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 flex-1 min-w-[12rem]"
      />
      <div v-if="stats && roots.length" class="flex flex-wrap items-center gap-1.5 text-xs">
        <span class="text-slate-500 px-1">
          <b class="text-ink ltr-nums">{{ num(stats.people) }}</b> نفر ·
          <b class="text-ink ltr-nums">{{ num(stats.positions) }}</b> سمت
        </span>
        <span v-if="stats.vacant" class="bg-amber-50 text-amber-700 rounded-lg px-2 py-1">
          <b class="ltr-nums">{{ num(stats.vacant) }}</b> خالی
        </span>
        <button
          v-if="stats.unplaced"
          class="bg-sky-50 text-sky-700 rounded-lg px-2 py-1 hover:bg-sky-100"
          @click="router.push({ name: 'hr-people', query: { tab: 'unplaced' } })"
        ><b class="ltr-nums">{{ num(stats.unplaced) }}</b> بدون سمت</button>
        <button
          v-if="stats.duplicates"
          class="bg-red-50 text-red-600 rounded-lg px-2 py-1 hover:bg-red-100"
          @click="router.push({ name: 'hr-people', query: { tab: 'duplicates' } })"
        ><b class="ltr-nums">{{ num(stats.duplicates) }}</b> نام تکراری</button>
      </div>
      <button
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm"
        @click="router.push({ name: 'hr-people' })"
      >افراد و بایگانی</button>
    </div>

    <div v-if="loading && !chart" class="space-y-3">
      <Skeleton class="h-28 rounded-card" />
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Skeleton v-for="i in 8" :key="i" class="h-24 rounded-card" />
      </div>
    </div>

    <div v-else-if="!roots.length" class="bg-surface rounded-card shadow-soft p-6 text-center space-y-4">
      <EmptyState
        icon="🏢"
        title="هنوز چارت سازمانی ساخته نشده"
        hint="چارت سازمانی شرکت آماده است؛ با یک کلیک ساخته می‌شود و بعد همین‌جا قابل ویرایش است."
      />
      <div class="flex justify-center gap-2 flex-wrap">
        <button
          class="bg-panel text-white rounded-xl px-5 py-2.5 text-sm disabled:opacity-50"
          :disabled="importing" @click="importChart"
        >{{ importing ? "در حال ساخت…" : "ساخت چارت سازمانی شرکت" }}</button>
        <button
          class="border border-slate-200 rounded-xl px-4 py-2.5 text-sm text-slate-600"
          @click="addUnit(null)"
        >شروع از صفر</button>
      </div>
    </div>

    <template v-else>
      <!-- ===== Level 1: the top of the chart ===== -->
      <section class="bg-surface rounded-card shadow-soft px-4 py-5">
        <div class="flex flex-col items-center">
          <template v-for="(node, i) in topChain" :key="node.id">
            <div v-if="i" class="w-px h-4 bg-slate-200" />
            <button
              type="button"
              class="rounded-xl border px-5 py-2 text-center min-w-[13rem] transition-shadow hover:shadow-soft"
              :class="topHit(node) ? 'ring-2 ring-amber-300' : ''"
              :style="{
                borderColor: `color-mix(in srgb, ${node.color || '#64748b'} 30%, transparent)`,
                background: `color-mix(in srgb, ${node.color || '#64748b'} 6%, transparent)`,
              }"
              @click="headOf(node) ? editSeat(headOf(node)!, node) : addSeat(node)"
            >
              <span class="block text-[11px] text-slate-400">{{ node.name_fa }}</span>
              <span class="flex items-center justify-center gap-2 mt-0.5">
                <span
                  v-if="node.kind === 'executive'"
                  class="w-7 h-7 rounded-lg flex items-center justify-center text-sm font-bold text-white"
                  :style="{ background: node.color || '#2563eb' }"
                >{{ initial(headOf(node)?.holder_name ?? "") }}</span>
                <span class="font-bold" :class="headOf(node)?.holder ? 'text-ink' : 'text-amber-600'">
                  {{ headOf(node)?.holder_name || "نامشخص" }}
                </span>
              </span>
              <span class="block text-[11px] text-slate-400">{{ headOf(node)?.title }}</span>
            </button>
          </template>

          <!-- Staff offices hang off the CEO, left and right -->
          <div v-if="staff.length" class="w-full max-w-2xl mt-3">
            <div class="flex flex-wrap justify-center gap-2">
              <button
                v-for="s in staff" :key="s.id"
                type="button"
                class="rounded-xl border border-dashed border-slate-200 px-3 py-1.5 text-center hover:bg-slate-50"
                :class="topHit(s) ? 'ring-2 ring-amber-300' : ''"
                @click="headOf(s) ? editSeat(headOf(s)!, s) : addSeat(s)"
              >
                <span class="block text-[10px] text-slate-400">{{ s.name_fa }}</span>
                <span class="block text-sm font-medium" :class="headOf(s)?.holder ? 'text-ink' : 'text-amber-600'">
                  {{ headOf(s)?.holder_name || "نامشخص" }}
                </span>
              </button>
            </div>
          </div>

          <div class="w-px h-4 bg-slate-200 mt-3" />
          <div class="flex items-center gap-3 text-xs text-slate-400">
            <span>واحدها</span>
            <button class="hover:text-ink" @click="addUnit(apex)">+ واحد جدید</button>
            <template v-if="apex">
              <button class="hover:text-ink" @click="editUnit(apex)">✎ مدیریت عامل</button>
            </template>
          </div>
        </div>

        <!-- Departments: equal tiles, one row of the company -->
        <div class="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-2 mt-3">
          <button
            v-for="d in departments" :key="d.id"
            type="button"
            class="relative text-right rounded-xl border px-3 pt-3 pb-2.5 transition-all overflow-hidden"
            :class="[
              openId === d.id ? 'shadow-soft' : 'border-slate-100 hover:border-slate-200 hover:shadow-soft',
              matching && !matching.has(d.id) ? 'opacity-30' : '',
              !d.is_active ? 'grayscale' : '',
            ]"
            :style="openId === d.id ? {
              borderColor: d.color || '#64748b',
              background: `color-mix(in srgb, ${d.color || '#64748b'} 7%, transparent)`,
            } : {}"
            @click="openId = d.id"
          >
            <span class="absolute inset-x-0 top-0 h-1" :style="{ background: d.color || '#64748b' }" />
            <span class="block text-sm font-bold truncate" :style="{ color: d.color || undefined }">{{ d.name_fa }}</span>
            <span
              class="block text-xs truncate mt-0.5"
              :class="tile(d).head?.holder ? 'text-ink' : 'text-amber-600'"
            >{{ tile(d).head?.holder_name || "نامشخص" }}</span>
            <span class="flex items-center gap-1.5 text-[10px] text-slate-400 mt-1.5 ltr-nums">
              <span>{{ num(tile(d).people) }} نفر</span>
              <span v-if="tile(d).vacant" class="text-amber-600">· {{ num(tile(d).vacant) }} خالی</span>
            </span>
          </button>
        </div>
      </section>

      <!-- ===== Level 2: the department that is open ===== -->
      <section
        v-if="opened"
        class="bg-surface rounded-card shadow-soft overflow-hidden"
      >
        <header
          class="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-slate-100"
          :style="{ background: `color-mix(in srgb, ${opened.color || '#64748b'} 6%, transparent)` }"
        >
          <span class="w-2 h-8 rounded-full" :style="{ background: opened.color || '#64748b' }" />
          <div class="min-w-0 flex-1">
            <h2 class="font-bold text-ink text-lg leading-tight">{{ opened.name_fa }}</h2>
            <p class="text-xs text-slate-400">
              {{ num(tile(opened).sections) }} زیرواحد ·
              {{ num(tile(opened).people) }} نفر ·
              <span :class="tile(opened).vacant ? 'text-amber-600' : ''">{{ num(tile(opened).vacant) }} سمت خالی</span>
            </p>
          </div>
          <div class="flex flex-wrap gap-1.5 text-xs">
            <button class="border border-slate-200 bg-surface rounded-lg px-2.5 py-1.5 hover:bg-slate-50" @click="addSeat(opened)">+ سمت</button>
            <button class="border border-slate-200 bg-surface rounded-lg px-2.5 py-1.5 hover:bg-slate-50" @click="addUnit(opened)">+ زیرواحد</button>
            <button class="border border-slate-200 bg-surface rounded-lg px-2.5 py-1.5 hover:bg-slate-50" @click="editUnit(opened)">✎ ویرایش واحد</button>
          </div>
        </header>

        <div class="p-4 space-y-4">
          <!-- The department's own seats: its head first, then anyone
               who reports to the department rather than to a section. -->
          <div v-if="opened.positions.length" class="flex flex-wrap gap-2">
            <button
              v-for="seat in [...opened.positions].sort((a, b) => Number(b.is_head) - Number(a.is_head))"
              :key="seat.id"
              type="button"
              class="flex items-center gap-2.5 rounded-xl border px-3 py-2 text-right hover:shadow-soft transition-shadow"
              :class="[
                seat.is_head ? '' : 'border-slate-100',
                q && `${seat.holder_name} ${seat.title}`.includes(q) ? 'ring-2 ring-amber-300' : '',
              ]"
              :style="seat.is_head ? { borderColor: `color-mix(in srgb, ${opened.color || '#64748b'} 40%, transparent)` } : {}"
              @click="editSeat(seat, opened)"
            >
              <span
                class="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold shrink-0"
                :class="seat.holder ? 'text-white' : 'border border-dashed border-amber-300 bg-amber-50 text-amber-600'"
                :style="seat.holder ? { background: opened.color || '#64748b' } : {}"
              >{{ initial(seat.holder_name) }}</span>
              <span class="leading-tight">
                <span class="block text-sm font-medium" :class="seat.holder ? 'text-ink' : 'text-amber-600'">
                  {{ seat.holder_name || "نامشخص" }}
                </span>
                <span class="block text-[11px] text-slate-400">{{ seat.title }}</span>
              </span>
              <span
                v-if="seat.holder"
                class="w-2 h-2 rounded-full"
                :class="seat.holder_user ? 'bg-green-500' : 'bg-slate-300'"
                :title="seat.holder_user ? 'حساب کاربری دارد' : 'حساب کاربری ندارد'"
              />
            </button>
          </div>

          <!-- Sections flow in columns, so a ten-seat section and a one-seat
               one stack without leaving holes. -->
          <div v-if="opened.children.length" class="columns-1 sm:columns-2 lg:columns-3 2xl:columns-4 gap-3">
            <div v-for="section in opened.children" :key="section.id" class="break-inside-avoid mb-3">
              <ChartUnit
                :node="section" :query="query" :color="opened.color"
                @edit-unit="editUnit" @add-unit="addUnit"
                @edit-seat="editSeat" @add-seat="addSeat"
              />
            </div>
          </div>
          <p v-else-if="!opened.positions.length" class="text-sm text-slate-400 text-center py-6">
            این واحد هنوز سمت یا زیرواحدی ندارد.
          </p>
        </div>
      </section>

      <p class="text-xs text-slate-400 text-center">
        روی هر واحد بزنید تا باز شود و روی هر نفر تا متصدی سمت عوض شود.
        <span class="inline-flex items-center gap-1 mr-2"><span class="w-2 h-2 rounded-full bg-green-500" /> حساب کاربری دارد</span>
        <span class="inline-flex items-center gap-1 mr-2"><span class="w-2 h-2 rounded-full bg-slate-300" /> ندارد</span>
      </p>
    </template>

    <UnitForm
      v-if="unitForm"
      :unit="unitForm.unit" :parent-id="unitForm.parentId" :units="flatUnits"
      @close="unitForm = null" @saved="afterSave"
    />
    <PositionForm
      v-if="seatForm"
      :seat="seatForm.seat" :unit="seatForm.unit"
      @close="seatForm = null" @saved="afterSave"
    />
  </div>
</template>
