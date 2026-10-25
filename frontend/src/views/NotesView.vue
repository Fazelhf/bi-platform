<script setup lang="ts">
/**
 * یادداشت‌ها — a notes app, not a list of rows.
 *
 * The version this replaces was a single column of text with a delete
 * button. Notes are not used that way: one of them matters more than the
 * rest and should stay at the top, several are colour-coded by what they are
 * about, some are really reminders with a date, and finished ones want
 * filing rather than deleting.
 *
 * A masonry-ish card grid rather than a list, for the reason the iPhone app
 * uses one: notes differ wildly in length, and a list gives a three-word
 * note the same height as a paragraph. Cards let short ones stay short.
 *
 * Editing is in place. A note is a scrap of thought, and a modal asking you
 * to confirm a scrap of thought is why people go back to paper.
 */
import { computed, onMounted, ref } from "vue";
import { socialApi, type Note } from "@/api/social";
import { officeApi, type Person } from "@/api/office";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import PeoplePicker from "@/components/office/PeoplePicker.vue";
import JalaliDateField from "@/components/JalaliDateField.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import NavIcon from "@/components/NavIcon.vue";

type Tab = "all" | "reminders" | "archive";

const notes = ref<Note[]>([]);
const people = ref<Person[]>([]);
const loading = ref(true);
const error = ref("");
const tab = ref<Tab>("all");
const search = ref("");

/** The note currently open for editing. `0` means the new, unsaved one. */
const editingId = ref<number | null>(null);
const draft = ref({
  title: "", body: "", color: "", remind_on: "", people: [] as number[],
});

const PALETTE = ["#f59e0b", "#ef4444", "#8b5cf6", "#10b981",
                 "#0ea5e9", "#3b6fed", "#ec4899", "#64748b"];

async function load() {
  loading.value = true;
  try {
    notes.value = await socialApi.notes();
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  officeApi.people().then((d) => (people.value = d.people)).catch(() => {});
  await load();
});

const shown = computed(() => {
  const q = search.value.trim();
  let rows = notes.value;

  if (tab.value === "archive") rows = rows.filter((n) => n.is_archived);
  else rows = rows.filter((n) => !n.is_archived);

  if (tab.value === "reminders") rows = rows.filter((n) => n.remind_on);
  if (q) {
    rows = rows.filter((n) => n.title.includes(q) || n.body.includes(q));
  }
  // Pinned first — the server orders this way too, but the filters above
  // would otherwise let a client-side sort disagree with it.
  return [...rows].sort((a, b) => {
    if (!!a.pinned_at !== !!b.pinned_at) return a.pinned_at ? -1 : 1;
    return (b.pinned_at ?? b.created_at).localeCompare(a.pinned_at ?? a.created_at);
  });
});

const counts = computed(() => ({
  all: notes.value.filter((n) => !n.is_archived).length,
  reminders: notes.value.filter((n) => !n.is_archived && n.remind_on).length,
  archive: notes.value.filter((n) => n.is_archived).length,
}));

/** Overdue reminders are the only thing on this page that shouts. */
function isDue(n: Note): boolean {
  return !!n.remind_on && new Date(n.remind_on) <= new Date();
}

function startNew() {
  editingId.value = 0;
  draft.value = { title: "", body: "", color: PALETTE[0], remind_on: "", people: [] };
}

function startEdit(n: Note) {
  editingId.value = n.id;
  draft.value = {
    title: n.title, body: n.body, color: n.color,
    remind_on: n.remind_on ?? "", people: [...n.people],
  };
}

async function save() {
  if (!draft.value.title.trim() && !draft.value.body.trim()) {
    editingId.value = null;
    return;
  }
  const payload = { ...draft.value, remind_on: draft.value.remind_on || null };
  try {
    if (editingId.value) await socialApi.updateNote(editingId.value, payload as never);
    else await socialApi.createNote(payload as never);
    editingId.value = null;
    await load();
  } catch (e) {
    error.value = apiError(e);
  }
}

async function togglePin(n: Note) {
  await socialApi.pinNote(n.id, n.is_pinned);
  await load();
}

async function toggleArchive(n: Note) {
  await socialApi.archiveNote(n.id, n.is_archived);
  await load();
}

async function remove(n: Note) {
  await socialApi.deleteNote(n.id);
  await load();
}

/** A tinted card that still reads in both skins — never a flat fill. */
function cardStyle(n: Note): Record<string, string> {
  if (!n.color) return {};
  // A real colour, not a 12% wash: a red note should look red from across
  // the room, the way a sticky note does. Mixed over the surface so it still
  // reads in the dark skin.
  return {
    background: `color-mix(in srgb, ${n.color} 42%, rgb(var(--c-surface)))`,
    borderColor: `color-mix(in srgb, ${n.color} 60%, transparent)`,
  };
}

</script>

<template>
  <div class="space-y-4">
    <div class="office-card p-2.5 flex flex-wrap items-center gap-2">
      <div class="office-seg">
        <button
          v-for="t in ([
            { key: 'all', label: 'همه', n: counts.all },
            { key: 'reminders', label: 'یادآوری‌ها', n: counts.reminders },
            { key: 'archive', label: 'بایگانی', n: counts.archive },
          ] as const)"
          :key="t.key"
          :class="{ 'is-active': tab === t.key }"
          @click="tab = t.key"
        >
          {{ t.label }}
          <span v-if="t.n" class="office-count ltr-nums">{{ num(t.n) }}</span>
        </button>
      </div>

      <label class="office-search flex-1 min-w-[10rem]">
        <NavIcon name="search" :size="16" />
        <input v-model="search" class="office-input" placeholder="جستجو در یادداشت‌ها…" />
      </label>
    </div>

    <!-- Keep-style capture: a line that looks like a note waiting to be
         written. One click and you are typing; no «+» to find first. -->
    <button
      v-if="editingId !== 0 && tab !== 'archive'"
      class="w-full max-w-xl mx-auto flex items-center gap-3 office-card px-4 h-12 text-sm text-slate-400
             hover:shadow-pop transition-shadow text-right"
      @click="startNew"
    >
      <span class="flex-1">یادداشت خود را بنویسید…</span>
      <NavIcon name="bell" :size="17" />
      <NavIcon name="pencil" :size="17" />
    </button>

    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3">
      {{ error }}
    </p>

    <div v-if="loading" class="columns-1 sm:columns-2 lg:columns-3 gap-3">
      <Skeleton v-for="i in 6" :key="i" class="h-32 rounded-card mb-3" />
    </div>

    <template v-else>
      <!-- The composer sits where the new note will appear. -->
      <div
        v-if="editingId === 0"
        class="max-w-xl mx-auto bg-surface rounded-card shadow-pop p-4 space-y-3 border-2"
        :style="{ borderColor: draft.color || 'transparent' }"
      >
        <input v-model="draft.title" class="office-input" placeholder="عنوان یادداشت" />
        <textarea v-model="draft.body" class="office-input" rows="4" placeholder="یادداشت خود را بنویسید…"></textarea>

        <div class="flex flex-wrap items-center gap-2">
          <button
            v-for="c in PALETTE" :key="c"
            class="w-6 h-6 rounded-full transition-transform"
            :class="draft.color === c ? 'ring-2 ring-offset-2 ring-slate-400 scale-110' : ''"
            :style="{ background: c }"
            :aria-label="`رنگ ${c}`"
            @click="draft.color = c"
          ></button>
          <span class="flex-1"></span>
          <JalaliDateField v-model="draft.remind_on" class="w-44" placeholder="یادآوری" />
        </div>

        <div>
          <label class="office-label">مربوط به چه کسانی</label>
          <PeoplePicker v-model="draft.people" :people="people" placeholder="افزودن شخص…" />
        </div>

        <div class="flex gap-2">
          <button class="office-btn rounded-xl px-4 py-2 text-sm" @click="save">ذخیره</button>
          <button class="text-sm text-slate-500 px-3 py-2" @click="editingId = null">انصراف</button>
        </div>
      </div>

      <EmptyState
        v-if="!shown.length && editingId !== 0"
        :title="tab === 'archive' ? 'بایگانی خالی است' : 'یادداشتی نیست'"
        hint="با «+ یادداشت» اولین یادداشت را بنویسید."
      />

      <!-- Cards, so a three-word note stays three words tall. -->
      <div v-else class="columns-1 sm:columns-2 lg:columns-3 gap-3">
        <div
          v-for="n in shown" :key="n.id"
          class="group/note break-inside-avoid mb-3 rounded-card shadow-soft border-2 border-transparent
                 bg-surface overflow-hidden hover:shadow-pop transition-shadow"
          :style="cardStyle(n)"
        >
          <!-- Editing happens in the card itself. -->
          <div v-if="editingId === n.id" class="p-4 space-y-3">
            <input v-model="draft.title" class="office-input" placeholder="عنوان" />
            <textarea v-model="draft.body" class="office-input" rows="5"></textarea>
            <div class="flex flex-wrap items-center gap-2">
              <button
                v-for="c in PALETTE" :key="c"
                class="w-5 h-5 rounded-full"
                :class="draft.color === c ? 'ring-2 ring-offset-1 ring-slate-400' : ''"
                :style="{ background: c }"
                @click="draft.color = c"
              ></button>
              <span class="flex-1"></span>
              <JalaliDateField v-model="draft.remind_on" class="w-44" placeholder="یادآوری" />
            </div>
            <PeoplePicker v-model="draft.people" :people="people" placeholder="افزودن شخص…" />
            <div class="flex gap-2">
              <button class="office-btn rounded-xl px-3 py-1.5 text-xs" @click="save">ذخیره</button>
              <button class="text-xs text-slate-500 px-2" @click="editingId = null">انصراف</button>
            </div>
          </div>

          <div v-else class="p-4">
            <div class="flex items-start gap-2">
              <button class="min-w-0 flex-1 text-right" @click="startEdit(n)">
                <p v-if="n.title" class="font-bold text-ink text-sm truncate">{{ n.title }}</p>
                <p class="text-sm text-slate-600 whitespace-pre-line mt-0.5 line-clamp-[12]">
                  {{ n.body }}
                </p>
              </button>
              <button
                class="office-icon-btn !w-7 !h-7 shrink-0"
                :class="n.is_pinned ? '!text-ink' : 'opacity-0 group-hover/note:opacity-100 focus:opacity-100 [@media(hover:none)]:opacity-100'"
                :aria-label="n.is_pinned ? 'برداشتن سنجاق' : 'سنجاق'"
                :title="n.is_pinned ? 'برداشتن سنجاق' : 'سنجاق'"
                @click="togglePin(n)"
              ><NavIcon name="pin" :size="15" /></button>
            </div>

            <div class="flex flex-wrap items-center gap-2 mt-3">
              <span
                v-if="n.remind_on"
                class="inline-flex items-center gap-1 text-[11px] rounded-full px-2 py-0.5 ltr-nums"
                :class="isDue(n) ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-500'"
              ><NavIcon name="clock" :size="11" /> {{ faDate(n.remind_on) }}</span>

              <span v-if="n.people_detail.length" class="flex -space-x-1.5 space-x-reverse">
                <UserAvatar
                  v-for="p in n.people_detail.slice(0, 4)" :key="p.id"
                  :user="p as any" :size="20" :title="p.name"
                  class="ring-2 ring-surface rounded-full"
                />
              </span>

              <span class="flex-1"></span>
              <span class="text-[10px] text-slate-400 ltr-nums">{{ faDate(n.created_at) }}</span>
            </div>

            <!-- Card tools appear when you reach for the card, as in Keep. -->
            <div class="flex items-center gap-1 mt-2 -mb-1 opacity-0 group-hover/note:opacity-100 focus-within:opacity-100 [@media(hover:none)]:opacity-100 transition-opacity">
              <button
                class="office-icon-btn !w-7 !h-7"
                aria-label="ویرایش" title="ویرایش"
                @click="startEdit(n)"
              ><NavIcon name="pencil" :size="14" /></button>
              <button
                class="office-icon-btn !w-7 !h-7"
                :aria-label="n.is_archived ? 'خروج از بایگانی' : 'بایگانی'"
                :title="n.is_archived ? 'خروج از بایگانی' : 'بایگانی'"
                @click="toggleArchive(n)"
              ><NavIcon name="archive" :size="14" /></button>
              <button
                class="office-icon-btn office-btn-danger !w-7 !h-7"
                aria-label="حذف" title="حذف"
                @click="remove(n)"
              ><NavIcon name="trash" :size="14" /></button>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
