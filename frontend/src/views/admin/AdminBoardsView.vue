<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { dashboardsApi, type BoardSummary, type Catalog } from "@/api/dashboards";
import { boardRouteFor } from "@/router";
import { confirm, toast } from "@/composables/useUi";

/**
 * Where the CEO manages the report pages — «تنظیمات سایت ← داشبوردها».
 *
 * The layout used to be edited from a button on the board itself, which put a
 * control only one person may use on a page everybody opens. Composing the
 * report is a setting, not a page action: it belongs next to the calendar and
 * the formulas, with the other things the CEO owns and the rest only read.
 *
 * «ویرایش چیدمان» still opens the board — you cannot arrange cards without
 * seeing them — it just starts from here, and lands there already in edit mode.
 */
const catalog = ref<Catalog | null>(null);
const boards = ref<BoardSummary[]>([]);
const loading = ref(true);
const busy = ref(false);
const newTitle = ref<Record<string, string>>({});

const sections = computed(() => catalog.value?.sections ?? []);

function boardsOf(section: string): BoardSummary[] {
  return boards.value.filter((b) => b.section === section);
}

async function load() {
  loading.value = true;
  try {
    if (!catalog.value) catalog.value = await dashboardsApi.catalog();
    boards.value = await dashboardsApi.boards();
  } finally {
    loading.value = false;
  }
}
onMounted(load);

async function act<T>(run: () => Promise<T>, done: string) {
  busy.value = true;
  try {
    await run();
    boards.value = await dashboardsApi.boards();
    toast.success(done);
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || "انجام نشد.");
  } finally {
    busy.value = false;
  }
}

function create(section: string) {
  const title = (newTitle.value[section] || "").trim();
  if (!title) return;
  newTitle.value[section] = "";
  act(
    () => dashboardsApi.createBoard({ section, title, is_default: !boardsOf(section).length }),
    "داشبورد ساخته شد.",
  );
}

async function remove(board: BoardSummary) {
  const ok = await confirm({
    title: "حذف داشبورد",
    message: `«${board.title}» و همه ویجت‌هایش حذف می‌شوند. مطمئنید؟`,
    danger: true,
  });
  if (!ok) return;
  act(() => dashboardsApi.deleteBoard(board.id), "داشبورد حذف شد.");
}

const cell = "bg-surface rounded-card shadow-soft";
</script>

<template>
  <div class="space-y-4">
    <div>
      <h2 class="font-bold text-ink">داشبوردها و گزارش‌ها</h2>
      <p class="text-xs text-slate-400 mt-1 leading-6">
        صفحه گزارش هر بخش را اینجا می‌سازید و می‌چینید. «ویرایش چیدمان» همان صفحه را
        در حالت ویرایش باز می‌کند؛ کارت اضافه می‌کنید، نوع نمودار و منبع داده را
        انتخاب می‌کنید و ذخیره می‌زنید. کارکنان همان صفحه را بدون ابزار ویرایش می‌بینند.
      </p>
    </div>

    <div v-if="loading" class="space-y-3">
      <div v-for="i in 4" :key="i" :class="cell" class="h-24 animate-pulse"></div>
    </div>

    <div v-else-if="!catalog?.can_edit" :class="cell" class="p-6 text-sm text-slate-500">
      چیدمان داشبوردها فقط توسط مدیرعامل یا مدیر سیستم قابل تغییر است.
    </div>

    <template v-else>
      <section v-for="s in sections" :key="s.key" :class="cell" class="p-4">
        <div class="flex items-center justify-between gap-2 flex-wrap mb-3">
          <h3 class="font-semibold text-ink text-sm">{{ s.label }}</h3>
          <RouterLink
            :to="{ name: boardRouteFor(s.key) }"
            class="text-xs text-brand-600 hover:underline"
          >مشاهده صفحه ←</RouterLink>
        </div>

        <div v-if="!boardsOf(s.key).length" class="text-xs text-slate-400 mb-3">
          هنوز داشبوردی برای این بخش ساخته نشده است.
        </div>

        <div
          v-for="b in boardsOf(s.key)" :key="b.id"
          class="flex items-center gap-2 flex-wrap py-2 border-t border-slate-100 first:border-0"
        >
          <div class="min-w-0 flex-1">
            <p class="text-sm text-ink truncate">
              {{ b.title }}
              <span v-if="b.is_default" class="text-[11px] text-amber-600 mr-1">★ پیش‌فرض</span>
              <span v-if="!b.is_published" class="text-[11px] text-slate-400 mr-1">· پیش‌نویس</span>
            </p>
            <p v-if="b.subtitle" class="text-[11px] text-slate-400 truncate">{{ b.subtitle }}</p>
          </div>

          <RouterLink
            :to="{ name: boardRouteFor(s.key), query: { board: b.id, edit: '1' } }"
            class="text-xs bg-panel text-white rounded-xl px-3 py-1.5"
          >ویرایش چیدمان</RouterLink>
          <button
            v-if="!b.is_default" class="board-admin-btn" :disabled="busy"
            @click="act(() => dashboardsApi.makeDefault(b.id), 'پیش‌فرض شد.')"
          >پیش‌فرض کن</button>
          <button
            class="board-admin-btn" :disabled="busy"
            @click="act(() => dashboardsApi.duplicate(b.id), 'رونوشت ساخته شد.')"
          >رونوشت</button>
          <button
            class="board-admin-btn" :disabled="busy"
            @click="act(() => dashboardsApi.updateBoard(b.id, { is_published: !b.is_published }),
                        b.is_published ? 'به پیش‌نویس رفت.' : 'منتشر شد.')"
          >{{ b.is_published ? "پیش‌نویس کن" : "منتشر کن" }}</button>
          <button
            class="board-admin-btn hover:text-red-500" :disabled="busy || boardsOf(s.key).length < 2"
            :title="boardsOf(s.key).length < 2 ? 'تنها داشبورد این بخش حذف نمی‌شود' : ''"
            @click="remove(b)"
          >حذف</button>
        </div>

        <div class="flex items-center gap-2 pt-3 mt-1 border-t border-slate-100">
          <input
            v-model="newTitle[s.key]"
            class="flex-1 bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition"
            placeholder="عنوان داشبورد جدید"
            @keyup.enter="create(s.key)"
          />
          <button class="board-admin-btn" :disabled="busy" @click="create(s.key)">+ بساز</button>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.board-admin-btn {
  @apply text-xs border border-slate-200 text-slate-600 rounded-xl px-3 py-1.5
         hover:bg-slate-50 transition disabled:opacity-40 disabled:cursor-not-allowed;
}
</style>
