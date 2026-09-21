<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { crmApi, type CrmToday } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num, rial } from "@/utils/format";
import Skeleton from "@/components/Skeleton.vue";
import ActivityForm from "@/components/crm/ActivityForm.vue";
import TaskForm from "@/components/crm/TaskForm.vue";

/**
 * کارتابل امروز — the one CRM screen that is not a report.
 *
 * Every other screen here answers «چه خبر بوده؟» over a window you pick.
 * This one answers «الان باید چه کار کنم؟». That is why it has no date
 * filter and why nothing on it is merely a figure: each row is a piece of
 * work with the action next to it — زنگ بزن، انجام شد، برو به معامله.
 *
 * The lists are ordered by what it costs to ignore them: a task already past
 * its due date, then a promise of a follow-up nobody kept, then the open
 * deals that have gone quiet, then customers who have not heard from anyone
 * in two months.
 */
const crm = useCrmStore();
const router = useRouter();

const data = ref<CrmToday | null>(null);
const loading = ref(true);

/** Managers may stand in one رep's shoes; a کارشناس only ever sees their own. */
const owner = ref<number | "">("");

async function load() {
  loading.value = true;
  try {
    data.value = await crmApi.today(owner.value ? { owner: owner.value } : {});
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await crm.loadOptions(); await load(); });
watch(owner, load);
watch(() => crm.revision, load);

const t = computed(() => data.value?.thresholds);

/** The strip at the top: what is owed, then what is in flight. */
const tiles = computed(() => {
  const c = data.value?.counters;
  if (!c) return [];
  return [
    { key: "overdue", label: "کار عقب‌افتاده", value: num(c.overdue), tone: c.overdue ? "bad" : "good" },
    { key: "due_today", label: "کار امروز", value: num(c.due_today), tone: c.due_today ? "warn" : "good" },
    { key: "pending_follow_up", label: "پیگیری معلق", value: num(c.pending_follow_up), tone: c.pending_follow_up ? "warn" : "good" },
    { key: "stale_deals", label: `معامله راکد (${num(t.value?.stale_days ?? 0)} روز)`, value: num(c.stale_deals), tone: c.stale_deals ? "warn" : "good" },
    { key: "activities_today", label: "فعالیت ثبت‌شده امروز", value: num(c.activities_today), tone: "none" },
    { key: "open", label: "معاملات باز", value: rial(c.open_amount), sub: `${num(c.open_count)} معامله · وزنی ${rial(c.open_weighted)}`, tone: "none" },
  ];
});

const toneRing: Record<string, string> = {
  good: "border-emerald-200", warn: "border-amber-200", bad: "border-red-200", none: "border-slate-100",
};
const toneText: Record<string, string> = {
  good: "text-emerald-600", warn: "text-amber-600", bad: "text-red-600", none: "text-ink",
};

// ---- acting on a row ------------------------------------------------------
const busyTask = ref<number | null>(null);

async function complete(id: number) {
  busyTask.value = id;
  try {
    await crmApi.completeTask(id);
    await load();
  } finally {
    busyTask.value = null;
  }
}

/** Log a call against a customer without leaving the worklist. */
const logFor = ref<{ customer: number; deal?: number | null; name: string } | null>(null);
const taskFor = ref<{ customer: number | null; deal?: number | null; name: string } | null>(null);

function onSaved() {
  logFor.value = null;
  taskFor.value = null;
  load();
}

function goDeal(id: number) { router.push({ name: "crm-deal", params: { id } }); }
function goCustomer(id: number) { router.push({ name: "crm-customer", params: { id } }); }

/** How late something is, in the words a person would use. */
function lateness(due: string): { text: string; tone: string } {
  const days = Math.floor((Date.now() - new Date(due).getTime()) / 86400000);
  if (days >= 1) return { text: `${num(days)} روز عقب‌افتاده`, tone: "text-red-600" };
  if (days >= 0) return { text: "امروز", tone: "text-amber-600" };
  return { text: `${num(-days)} روز دیگر`, tone: "text-slate-400" };
}

function daysSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
}

const card = "bg-surface rounded-card shadow-soft";
</script>

<template>
  <div class="space-y-4">
    <!-- Header: no date filter on purpose — this screen is always «now». -->
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h2 class="text-lg font-bold text-ink">کارتابل امروز</h2>
        <p class="text-xs text-slate-400 mt-0.5">
          کارهایی که روی زمین مانده‌اند — {{ data?.as_of }}
        </p>
      </div>
      <select
        v-if="crm.seesAll"
        v-model="owner"
        class="bg-surface border border-slate-200 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300"
      >
        <option value="">همه کارشناسان</option>
        <option v-for="e in crm.options?.employees ?? []" :key="e.id" :value="e.id">{{ e.name }}</option>
      </select>
    </div>

    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-24 rounded-card" />
      <Skeleton class="h-72 rounded-card" />
    </div>

    <template v-else-if="data">
      <!-- Counters -->
      <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <div v-for="tile in tiles" :key="tile.key" :class="[card, toneRing[tile.tone]]" class="p-4 border">
          <p class="text-[11px] text-slate-400 truncate" :title="tile.label">{{ tile.label }}</p>
          <p class="text-xl font-extrabold ltr-nums mt-1 truncate" :class="toneText[tile.tone]">{{ tile.value }}</p>
          <p v-if="tile.sub" class="text-[11px] text-slate-400 mt-0.5 truncate">{{ tile.sub }}</p>
        </div>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <!-- ===== کارها ===== -->
        <section :class="card" class="overflow-hidden">
          <header class="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between">
            <h3 class="font-bold text-ink text-sm">کارهای من</h3>
            <button
              v-if="crm.canEdit"
              class="text-xs rounded-lg px-2.5 py-1 bg-slate-100 text-slate-600 hover:bg-slate-200"
              @click="taskFor = { customer: null, name: '' }"
            >+ کار جدید</button>
          </header>

          <!-- The imported history's old tasks: one line, not four hundred rows. -->
          <RouterLink
            v-if="data.counters.backlog"
            :to="{ name: 'crm-activities', query: { tab: 'tasks' } }"
            class="px-5 py-2.5 flex items-center justify-between text-xs bg-slate-50 border-b border-slate-100 text-slate-500 hover:text-ink"
          >
            <span>{{ num(data.counters.backlog) }} کار قدیمی‌تر از {{ num(t?.backlog_days ?? 0) }} روز هم باز مانده</span>
            <span>بازبینی ←</span>
          </RouterLink>

          <div v-if="!data.overdue.length && !data.due_today.length && !data.upcoming.length"
               class="px-5 py-10 text-center text-sm text-emerald-600">
            ✓ هیچ کار بازی برای این هفته نیست
          </div>

          <ul v-else class="divide-y divide-slate-100 max-h-[460px] overflow-y-auto">
            <li v-for="group in [
                  { rows: data.overdue, label: 'عقب‌افتاده', cls: 'bg-red-500' },
                  { rows: data.due_today, label: 'امروز', cls: 'bg-amber-500' },
                  { rows: data.upcoming, label: 'پیش‌رو', cls: 'bg-slate-300' },
                ]" :key="group.label">
              <template v-if="group.rows.length">
                <p class="px-5 py-2 bg-slate-50 text-[11px] text-slate-400 flex items-center gap-1.5">
                  <span class="w-1.5 h-1.5 rounded-full" :class="group.cls"></span>
                  {{ group.label }} · {{ num(group.rows.length) }}
                </p>
                <div
                  v-for="task in group.rows" :key="task.id"
                  class="px-5 py-3 flex items-start gap-3 hover:bg-slate-50 group"
                >
                  <button
                    v-if="crm.canEdit"
                    class="mt-0.5 w-5 h-5 rounded-md border border-slate-300 hover:border-emerald-500 hover:bg-emerald-50 shrink-0 disabled:opacity-40 transition"
                    :disabled="busyTask === task.id"
                    title="انجام شد"
                    @click="complete(task.id)"
                  >
                    <svg class="w-3.5 h-3.5 mx-auto text-emerald-600 opacity-0 group-hover:opacity-100" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>
                  </button>
                  <div class="min-w-0 flex-1">
                    <p class="text-sm text-ink truncate">{{ task.title }}</p>
                    <p class="text-xs text-slate-400 truncate">
                      <button v-if="task.customer" class="hover:underline" @click="goCustomer(task.customer)">{{ task.customer_name }}</button>
                      <span v-else>بدون مشتری</span>
                      · {{ task.kind_display }}
                      <template v-if="crm.seesAll && task.owner_name"> · {{ task.owner_name }}</template>
                    </p>
                  </div>
                  <span class="text-[11px] shrink-0 ltr-nums" :class="lateness(task.due_at).tone">
                    {{ lateness(task.due_at).text }}
                  </span>
                </div>
              </template>
            </li>
          </ul>
        </section>

        <!-- ===== پیگیری‌های معلق ===== -->
        <section :class="card" class="overflow-hidden">
          <header class="px-5 py-3.5 border-b border-slate-100">
            <h3 class="font-bold text-ink text-sm">قول پیگیری، بدون تماس بعدی</h3>
            <p class="text-[11px] text-slate-400 mt-0.5">تماسی که نتیجه‌اش «نیاز به پیگیری» بود و بعد از آن هیچ تماسی ثبت نشده</p>
          </header>
          <div v-if="!data.pending_follow_up.length" class="px-5 py-10 text-center text-sm text-emerald-600">
            ✓ پیگیری معلقی نمانده است
          </div>
          <ul v-else class="divide-y divide-slate-100 max-h-[460px] overflow-y-auto">
            <li v-for="a in data.pending_follow_up" :key="a.id" class="px-5 py-3 flex items-start gap-3 hover:bg-slate-50">
              <div class="min-w-0 flex-1">
                <button class="text-sm text-ink truncate hover:underline block" @click="goCustomer(a.customer)">{{ a.customer_name }}</button>
                <p class="text-xs text-slate-400 truncate">{{ a.kind_display }} · {{ a.at_jalali }}<template v-if="a.note"> · {{ a.note }}</template></p>
              </div>
              <span class="text-[11px] text-amber-600 shrink-0 ltr-nums">{{ num(daysSince(a.at) ?? 0) }} روز</span>
              <button
                v-if="crm.canEdit"
                class="text-[11px] rounded-lg px-2 py-1 bg-slate-100 text-slate-600 hover:bg-slate-200 shrink-0"
                @click="logFor = { customer: a.customer, deal: a.deal, name: a.customer_name }"
              >ثبت تماس</button>
            </li>
          </ul>
        </section>

        <!-- ===== معاملات راکد ===== -->
        <section :class="card" class="overflow-hidden">
          <header class="px-5 py-3.5 border-b border-slate-100">
            <h3 class="font-bold text-ink text-sm">معاملات باز بدون پیگیری</h3>
            <p class="text-[11px] text-slate-400 mt-0.5">
              بیش از {{ num(t?.stale_days ?? 0) }} روز هیچ فعالیتی روی‌شان ثبت نشده — بزرگ‌ترین‌ها اول
            </p>
          </header>
          <div v-if="!data.stale_deals.length" class="px-5 py-10 text-center text-sm text-emerald-600">
            ✓ همه معاملات باز در جریان‌اند
          </div>
          <ul v-else class="divide-y divide-slate-100 max-h-[460px] overflow-y-auto">
            <li
              v-for="d in data.stale_deals" :key="d.id"
              class="px-5 py-3 flex items-center gap-3 hover:bg-slate-50 cursor-pointer"
              @click="goDeal(d.id)"
            >
              <div class="min-w-0 flex-1">
                <p class="text-sm text-ink truncate">{{ d.title }}</p>
                <p class="text-xs text-slate-400 truncate">
                  {{ d.customer_name }} · {{ d.stage_name }}
                  <template v-if="crm.seesAll && d.owner_name"> · {{ d.owner_name }}</template>
                </p>
              </div>
              <div class="text-left shrink-0">
                <p class="text-sm font-semibold text-ink ltr-nums">{{ rial(d.amount_rial) }}</p>
                <p class="text-[11px] text-amber-600 ltr-nums">{{ num(d.age_days) }} روز از ایجاد</p>
              </div>
            </li>
          </ul>
        </section>

        <!-- ===== مشتریان بی‌تماس + نزدیک به بسته‌شدن ===== -->
        <div class="space-y-4">
          <section v-if="data.closing_soon.length" :class="card" class="overflow-hidden">
            <header class="px-5 py-3.5 border-b border-slate-100">
              <h3 class="font-bold text-ink text-sm">نزدیک به بسته‌شدن</h3>
              <p class="text-[11px] text-slate-400 mt-0.5">تاریخ بسته‌شدن پیش‌بینی‌شده تا {{ num(t?.horizon_days ?? 0) }} روز آینده</p>
            </header>
            <ul class="divide-y divide-slate-100 max-h-[220px] overflow-y-auto">
              <li
                v-for="d in data.closing_soon" :key="d.id"
                class="px-5 py-3 flex items-center gap-3 hover:bg-slate-50 cursor-pointer"
                @click="goDeal(d.id)"
              >
                <div class="min-w-0 flex-1">
                  <p class="text-sm text-ink truncate">{{ d.title }}</p>
                  <p class="text-xs text-slate-400 truncate">{{ d.customer_name }} · {{ d.stage_name }}</p>
                </div>
                <p class="text-sm font-semibold text-ink ltr-nums shrink-0">{{ rial(d.amount_rial) }}</p>
              </li>
            </ul>
          </section>

          <section :class="card" class="overflow-hidden">
            <header class="px-5 py-3.5 border-b border-slate-100">
              <h3 class="font-bold text-ink text-sm">مشتریانی که مدت‌هاست تماسی نداشته‌اند</h3>
              <p class="text-[11px] text-slate-400 mt-0.5">بیش از {{ num(t?.dormant_days ?? 0) }} روز بدون فعالیت</p>
            </header>
            <div v-if="!data.quiet_customers.length" class="px-5 py-10 text-center text-sm text-emerald-600">
              ✓ با همه مشتریان اخیراً در تماس بوده‌اید
            </div>
            <ul v-else class="divide-y divide-slate-100 max-h-[300px] overflow-y-auto">
              <li v-for="c in data.quiet_customers" :key="c.id" class="px-5 py-3 flex items-center gap-3 hover:bg-slate-50">
                <div class="min-w-0 flex-1 cursor-pointer" @click="goCustomer(c.id)">
                  <p class="text-sm text-ink truncate">{{ c.name_fa }}</p>
                  <p class="text-xs text-slate-400 truncate">
                    {{ c.status_display }}<template v-if="c.province_name"> · {{ c.province_name }}</template>
                    <template v-if="crm.seesAll && c.owner_name"> · {{ c.owner_name }}</template>
                  </p>
                </div>
                <span class="text-[11px] text-slate-400 shrink-0 ltr-nums">
                  <template v-if="daysSince(c.last_activity_at) !== null">{{ num(daysSince(c.last_activity_at)!) }} روز</template>
                  <template v-else>بدون سابقه تماس</template>
                </span>
                <button
                  v-if="crm.canEdit"
                  class="text-[11px] rounded-lg px-2 py-1 bg-slate-100 text-slate-600 hover:bg-slate-200 shrink-0"
                  @click="logFor = { customer: c.id, name: c.name_fa }"
                >ثبت تماس</button>
              </li>
            </ul>
          </section>
        </div>
      </div>
    </template>

    <ActivityForm
      v-if="logFor"
      :customer-id="logFor.customer"
      :customer-label="logFor.name"
      :deal-id="logFor.deal ?? null"
      @close="logFor = null"
      @saved="onSaved"
    />
    <TaskForm
      v-if="taskFor"
      :customer-id="taskFor.customer"
      :customer-label="taskFor.name"
      @close="taskFor = null"
      @saved="onSaved"
    />
  </div>
</template>
