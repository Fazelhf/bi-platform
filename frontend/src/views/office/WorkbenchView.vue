<script setup lang="ts">
/**
 * میز کار — «حالا چه کنم», answered above the fold.
 *
 * **The tiles carry meaning, not just counts.** Each has the colour of the
 * section it opens and a line saying what the number is.
 *
 * **Late is the only thing that shouts.** Everything else is quiet on
 * purpose; a page where five numbers are all red has no signal in it.
 *
 * **Every row opens its own record.** A task opens that task, a letter opens
 * that letter in the reading pane — not the list it lives in, which left you
 * to find it again.
 *
 * **Ticking a task off is instant.** The row leaves and the tile counts move
 * at once; a failure puts it back and says so. No reload, no skeleton flash.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { workApi, type Task, type Workbench } from "@/api/officeWork";
import { officeApi, type LetterRow } from "@/api/office";
import { useAuthStore } from "@/stores/auth";
import { apiError, faDate } from "@/utils/adminFormat";
import { num } from "@/utils/format";
import { toast } from "@/composables/useUi";
import { OFFICE_SECTIONS } from "@/components/office/sections";
import TaskForm from "@/components/office/TaskForm.vue";
import NavIcon from "@/components/NavIcon.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";

const router = useRouter();
const auth = useAuthStore();

const data = ref<Workbench | null>(null);
const letters = ref<LetterRow[]>([]);
const loading = ref(true);
const error = ref("");
const creating = ref(false);

const colorOf = (name: string) =>
  OFFICE_SECTIONS.find((s) => s.name === name)?.color ?? "100 116 139";

/** Each tile: where it goes, what it looks like, and what the number means. */
const TILE: Record<string, { to: string; query?: Record<string, string>; icon: string; note: string }> = {
  today: { to: "office-tasks", icon: "check", note: "سررسید امروز یا گذشته" },
  overdue: { to: "office-tasks", query: { box: "today" }, icon: "clock", note: "از مهلتش گذشته" },
  others: { to: "office-tasks", query: { box: "others" }, icon: "team", note: "به دیگران سپرده‌اید" },
  letters: { to: "office-letters", query: { read: "0" }, icon: "inbox", note: "نامه‌ی باز نشده" },
  messages: { to: "chat", icon: "chat", note: "پیام خوانده نشده" },
  reminders: { to: "notes", icon: "bell", note: "یادداشت سررسیددار" },
};

const greeting = computed(() => {
  const h = new Date().getHours();
  if (h < 12) return "صبح بخیر";
  if (h < 17) return "ظهر بخیر";
  return "عصر بخیر";
});

const todayLabel = new Intl.DateTimeFormat("fa-IR", {
  weekday: "long", day: "numeric", month: "long",
}).format(new Date());

async function load() {
  error.value = "";
  try {
    const [wb, inbox] = await Promise.all([
      workApi.workbench(),
      officeApi.mailbox("inbox", { read: "0" }).catch(() => null),
    ]);
    data.value = wb;
    letters.value = inbox?.rows.slice(0, 6) ?? [];
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function go(key: string) {
  const t = TILE[key];
  if (t) router.push({ name: t.to, query: t.query });
}

function openTask(t: Task) {
  router.push({ name: "office-tasks", query: { task: String(t.id) } });
}

function openLetter(l: LetterRow) {
  router.push({ name: "office-letters", query: { id: String(l.id) } });
}

function bump(key: string, by: number) {
  const tile = data.value?.tiles.find((x) => x.key === key);
  if (tile) tile.value = Math.max(0, tile.value + by);
}

/** Optimistic: the row goes now, comes back if the server says no. */
async function complete(t: Task) {
  if (!data.value) return;
  const list = data.value.my_tasks;
  const at = list.indexOf(t);
  if (at === -1) return;
  list.splice(at, 1);
  const due = t.due_on ? new Date(t.due_on) : null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const isToday = !!due && due <= new Date(today.getTime() + 86_399_999);
  if (isToday) bump("today", -1);
  if (t.is_overdue) bump("overdue", -1);
  try {
    await workApi.toggleTask(t.id);
    toast.success(`«${t.title}» انجام شد.`);
  } catch (e) {
    list.splice(at, 0, t);
    if (isToday) bump("today", 1);
    if (t.is_overdue) bump("overdue", 1);
    toast.error(apiError(e));
  }
}

function tileLoud(key: string, value: number): boolean {
  return key === "overdue" && value > 0;
}

function onCreated() {
  creating.value = false;
  toast.success("وظیفه ثبت شد.");
  load();
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-4">
      <Skeleton class="h-36 rounded-card" />
      <div class="grid lg:grid-cols-2 gap-4">
        <Skeleton class="h-72 rounded-card" />
        <Skeleton class="h-72 rounded-card" />
      </div>
    </div>

    <div v-else-if="error" class="office-card p-6 flex flex-col items-center gap-3 text-center">
      <NavIcon name="alert" :size="24" class="text-red-500" />
      <p class="text-sm text-slate-600">{{ error }}</p>
      <button class="office-btn-subtle" @click="loading = true; load()">
        <NavIcon name="refresh" :size="15" /> تلاش دوباره
      </button>
    </div>

    <template v-else-if="data">
      <!-- Greeting + the numbers -->
      <section class="office-card p-4 sm:p-5">
        <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div>
            <h2 class="text-lg font-bold text-ink">
              {{ greeting }}، {{ auth.me?.display_name_fa || auth.me?.username }}
            </h2>
            <p class="text-xs text-slate-400 mt-0.5">{{ todayLabel }}</p>
          </div>
          <div class="flex gap-2">
            <button class="office-btn-subtle" @click="router.push({ name: 'office-letters' })">
              <NavIcon name="pencil" :size="15" /> نامه
            </button>
            <button class="office-btn" @click="creating = true">
              <NavIcon name="plus" :size="16" /> وظیفه جدید
            </button>
          </div>
        </div>

        <div class="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-2.5">
          <button
            v-for="t in data.tiles" :key="t.key"
            class="group rounded-xl border p-3 text-right transition-colors focus-visible:outline-none
                   focus-visible:ring-2 focus-visible:ring-slate-300"
            :class="tileLoud(t.key, t.value)
              ? 'border-red-200 bg-red-50 hover:bg-red-100/70'
              : 'border-slate-100 hover:border-slate-200 hover:bg-slate-50'"
            @click="go(t.key)"
          >
            <span class="flex items-center justify-between">
              <span
                class="w-8 h-8 rounded-lg grid place-items-center"
                :style="tileLoud(t.key, t.value)
                  ? { background: 'rgb(239 68 68)', color: '#fff' }
                  : {
                    background: `rgb(${colorOf(TILE[t.key]?.to ?? 'office-tasks')} / 0.12)`,
                    color: `rgb(${colorOf(TILE[t.key]?.to ?? 'office-tasks')})`,
                  }"
              ><NavIcon :name="TILE[t.key]?.icon ?? 'check'" :size="16" /></span>
              <span
                class="text-2xl font-bold ltr-nums"
                :class="tileLoud(t.key, t.value) ? 'text-red-600' : t.value ? 'text-ink' : 'text-slate-300'"
              >{{ num(t.value) }}</span>
            </span>
            <span class="block text-xs font-medium text-slate-600 mt-2.5">{{ t.label }}</span>
            <span class="block text-[11px] text-slate-400">{{ TILE[t.key]?.note }}</span>
          </button>
        </div>
      </section>

      <div class="grid lg:grid-cols-2 gap-4">
        <!-- My tasks -->
        <section class="office-card overflow-hidden flex flex-col">
          <div class="office-card-head">
            <NavIcon name="check" :size="16" class="text-slate-400" />
            <h3 class="office-card-title flex-1">کارهای من</h3>
            <button class="office-btn-ghost !h-7 text-xs" @click="router.push({ name: 'office-tasks' })">
              همه <NavIcon name="arrow-left" :size="13" />
            </button>
          </div>

          <div v-if="!data.my_tasks.length" class="flex-1 flex flex-col items-center justify-center gap-2 py-10 text-slate-400">
            <NavIcon name="check-double" :size="26" />
            <p class="text-sm">کار بازی ندارید.</p>
          </div>

          <ul v-else class="divide-y divide-slate-100 overflow-y-auto max-h-[22rem]">
            <li v-for="t in data.my_tasks" :key="t.id" class="office-row flex items-center gap-3 px-4 py-2.5">
              <button
                class="w-[18px] h-[18px] rounded-md border-2 border-slate-300 hover:border-emerald-500
                       hover:bg-emerald-50 shrink-0 transition-colors focus-visible:outline-none
                       focus-visible:ring-2 focus-visible:ring-emerald-300"
                :aria-label="`انجام شد: ${t.title}`"
                title="انجام شد"
                @click="complete(t)"
              ></button>
              <button class="min-w-0 flex-1 text-right" @click="openTask(t)">
                <span class="block text-sm text-ink truncate">{{ t.title }}</span>
                <span v-if="t.project_name || t.creator_detail" class="block text-[11px] text-slate-400 truncate">
                  {{ t.project_name || `از ${t.creator_detail?.name}` }}
                </span>
              </button>
              <span
                v-if="t.priority === 'urgent' || t.priority === 'high'"
                class="w-1.5 h-1.5 rounded-full shrink-0"
                :class="t.priority === 'urgent' ? 'bg-red-500' : 'bg-amber-500'"
                :title="t.priority_label"
              ></span>
              <span
                v-if="t.due_on"
                class="text-[11px] shrink-0 ltr-nums rounded-md px-1.5 py-0.5"
                :class="t.is_overdue ? 'bg-red-50 text-red-600 font-medium' : 'text-slate-400'"
              >{{ faDate(t.due_on) }}</span>
            </li>
          </ul>
        </section>

        <!-- Unread letters -->
        <section class="office-card overflow-hidden flex flex-col">
          <div class="office-card-head">
            <NavIcon name="inbox" :size="16" class="text-slate-400" />
            <h3 class="office-card-title flex-1">نامه‌های نخوانده</h3>
            <button
              class="office-btn-ghost !h-7 text-xs"
              @click="router.push({ name: 'office-letters' })"
            >صندوق ورودی <NavIcon name="arrow-left" :size="13" /></button>
          </div>

          <div v-if="!letters.length" class="flex-1 flex flex-col items-center justify-center gap-2 py-10 text-slate-400">
            <NavIcon name="inbox" :size="26" />
            <p class="text-sm">نامه‌ی نخوانده‌ای ندارید.</p>
          </div>

          <ul v-else class="divide-y divide-slate-100 overflow-y-auto max-h-[22rem]">
            <li v-for="l in letters" :key="l.id">
              <button class="office-row w-full flex items-center gap-3 px-4 py-2.5 text-right" @click="openLetter(l)">
                <UserAvatar :user="l.sender_detail" :size="30" />
                <span class="min-w-0 flex-1">
                  <span class="block text-sm font-semibold text-ink truncate">{{ l.subject }}</span>
                  <span class="block text-[11px] text-slate-400 truncate">{{ l.sender_detail.name }}</span>
                </span>
                <NavIcon v-if="l.attachment_count" name="paperclip" :size="13" class="text-slate-400 shrink-0" />
                <span class="text-[11px] text-slate-400 ltr-nums shrink-0">{{ faDate(l.sent_at) }}</span>
              </button>
            </li>
          </ul>
        </section>

        <!-- Following up -->
        <section class="office-card overflow-hidden flex flex-col">
          <div class="office-card-head">
            <NavIcon name="team" :size="16" class="text-slate-400" />
            <div class="flex-1">
              <h3 class="office-card-title">پیگیری از دیگران</h3>
            </div>
            <span class="text-[11px] text-slate-400">سپرده‌اید و هنوز انجام نشده</span>
          </div>

          <div v-if="!data.following.length" class="flex-1 flex flex-col items-center justify-center gap-2 py-10 text-slate-400">
            <NavIcon name="team" :size="26" />
            <p class="text-sm">چیزی در انتظار دیگران نیست.</p>
          </div>

          <ul v-else class="divide-y divide-slate-100 overflow-y-auto max-h-[22rem]">
            <li v-for="t in data.following" :key="t.id">
              <button class="office-row w-full flex items-center gap-3 px-4 py-2.5 text-right" @click="openTask(t)">
                <UserAvatar :user="t.assignee_detail" :size="28" />
                <span class="min-w-0 flex-1">
                  <span class="block text-sm text-ink truncate">{{ t.title }}</span>
                  <span class="block text-[11px] text-slate-400 truncate">{{ t.assignee_detail?.name }}</span>
                </span>
                <span
                  v-if="t.due_on"
                  class="text-[11px] shrink-0 ltr-nums rounded-md px-1.5 py-0.5"
                  :class="t.is_overdue ? 'bg-red-50 text-red-600 font-medium' : 'text-slate-400'"
                >{{ faDate(t.due_on) }}</span>
              </button>
            </li>
          </ul>
        </section>

        <!-- Reminders -->
        <section class="office-card overflow-hidden flex flex-col">
          <div class="office-card-head">
            <NavIcon name="bell" :size="16" class="text-slate-400" />
            <h3 class="office-card-title flex-1">یادآوری‌های این هفته</h3>
            <button class="office-btn-ghost !h-7 text-xs" @click="router.push({ name: 'notes' })">
              یادداشت‌ها <NavIcon name="arrow-left" :size="13" />
            </button>
          </div>
          <div v-if="!data.reminders.length" class="flex-1 flex flex-col items-center justify-center gap-2 py-10 text-slate-400">
            <NavIcon name="bell" :size="26" />
            <p class="text-sm">یادآوری نزدیکی ندارید.</p>
          </div>
          <ul v-else class="divide-y divide-slate-100">
            <li v-for="r in data.reminders" :key="r.id">
              <button class="office-row w-full flex items-center gap-3 px-4 py-2.5 text-right" @click="router.push({ name: 'notes' })">
                <span
                  class="w-2.5 h-2.5 rounded-full shrink-0"
                  :style="{ background: r.color || 'rgb(var(--c-slate-300))' }"
                ></span>
                <span class="flex-1 text-sm text-ink truncate">{{ r.title }}</span>
                <span
                  class="flex items-center gap-1 text-[11px] ltr-nums shrink-0 rounded-md px-1.5 py-0.5"
                  :class="r.overdue ? 'bg-red-50 text-red-600 font-medium' : 'text-slate-400'"
                ><NavIcon name="clock" :size="11" /> {{ faDate(r.remind_on) }}</span>
              </button>
            </li>
          </ul>
        </section>
      </div>

      <!-- Projects -->
      <section v-if="data.projects.length" class="office-card overflow-hidden">
        <div class="office-card-head">
          <NavIcon name="clipboard" :size="16" class="text-slate-400" />
          <h3 class="office-card-title flex-1">پروژه‌های در جریان</h3>
          <button class="office-btn-ghost !h-7 text-xs" @click="router.push({ name: 'office-projects' })">
            همه <NavIcon name="arrow-left" :size="13" />
          </button>
        </div>
        <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 p-4">
          <button
            v-for="p in data.projects" :key="p.id"
            class="rounded-xl border border-slate-100 hover:border-slate-200 hover:bg-slate-50 p-3 text-right transition-colors"
            @click="router.push({ name: 'office-project', params: { id: p.id } })"
          >
            <span class="flex items-center gap-2">
              <span
                class="w-2.5 h-2.5 rounded-full shrink-0"
                :style="{ background: p.color || `rgb(${colorOf('office-projects')})` }"
              ></span>
              <span class="text-sm font-medium text-ink truncate flex-1">{{ p.name }}</span>
              <span class="text-[11px] text-slate-500 ltr-nums">{{ num(Math.round(p.progress_pct)) }}٪</span>
            </span>
            <span class="block h-1.5 bg-slate-100 rounded-full overflow-hidden mt-2.5">
              <span
                class="block h-full rounded-full"
                :style="{
                  width: `${Math.max(p.progress_pct, 2)}%`,
                  background: p.overdue_count ? '#f59e0b' : `rgb(${colorOf('office-projects')})`,
                }"
              ></span>
            </span>
            <span class="block text-[11px] text-slate-400 mt-1.5 ltr-nums">
              {{ num(p.done_count) }} از {{ num(p.task_count) }} کار
              <template v-if="p.my_open_count"> · {{ num(p.my_open_count) }} کار من</template>
              <span v-if="p.overdue_count" class="text-amber-600"> · {{ num(p.overdue_count) }} عقب‌افتاده</span>
            </span>
          </button>
        </div>
      </section>

      <TaskForm v-if="creating" @close="creating = false" @saved="onCreated" />
    </template>
  </div>
</template>
