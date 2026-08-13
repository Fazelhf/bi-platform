<script setup lang="ts">
/**
 * مکاتبات — the five mailboxes, and the list that fills them.
 *
 * The boxes are tabs rather than a sidebar because they are the same set of
 * letters asked five questions, not five places. Switching between them is
 * the most frequent thing anyone does here.
 *
 * A row shows who and what, and one line of the body. Not the whole letter:
 * the point of a list is to decide which one to open.
 */
import { onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { officeApi, type Box, type LetterRow, type Person } from "@/api/office";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import LetterForm from "@/components/office/LetterForm.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

const router = useRouter();

const BOXES: { key: Box; label: string }[] = [
  { key: "inbox", label: "صندوق ورودی" },
  { key: "outbox", label: "صندوق خروجی" },
  { key: "paraph", label: "پاراف‌های من" },
  { key: "archive", label: "بایگانی" },
  { key: "draft", label: "پیش‌نویس‌ها" },
];

const box = ref<Box>("inbox");
const rows = ref<LetterRow[]>([]);
const unread = ref(0);
const total = ref(0);
const people = ref<Person[]>([]);
const loading = ref(true);
const error = ref("");
const composing = ref(false);
const showFilters = ref(false);

const filters = ref({ q: "", sender: "" as number | "", read: "", from: "", to: "" });

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const data = await officeApi.mailbox(box.value, filters.value);
    rows.value = data.rows;
    unread.value = data.unread;
    total.value = data.count;
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

watch(box, load);

function open(row: LetterRow) {
  // A draft has nothing to show yet — it reopens in the composer instead.
  if (row.status === "draft") {
    editing.value = row.id;
    return;
  }
  router.push({ name: "office-letter", params: { id: row.id } });
}

const editing = ref<number | null>(null);
const editDraft = ref<any>(null);

watch(editing, async (id) => {
  editDraft.value = id ? await officeApi.letter(id) : null;
});

function onSaved(sent: boolean) {
  composing.value = false;
  editing.value = null;
  // A sent draft leaves the drafts box, so land where it actually went.
  if (sent && box.value === "draft") box.value = "outbox";
  else load();
}

/** Unread is bold; everything else reads as already handled. */
function rowWeight(row: LetterRow): string {
  return box.value === "inbox" && !row.my_read_at
    ? "font-semibold text-ink"
    : "text-slate-600";
}

const inp =
  "bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
</script>

<template>
  <div class="space-y-4">
    <!-- Boxes -->
    <div class="bg-surface rounded-card shadow-soft p-2 flex flex-wrap gap-1">
      <button
        v-for="b in BOXES" :key="b.key"
        class="px-4 py-2 rounded-xl text-sm transition-colors flex items-center gap-2"
        :class="box === b.key ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
        @click="box = b.key"
      >
        {{ b.label }}
        <span
          v-if="b.key === 'inbox' && unread"
          class="text-[11px] rounded-full px-1.5 py-0.5 ltr-nums"
          :class="box === b.key ? 'bg-white/20' : 'bg-red-500 text-white'"
        >{{ num(unread) }}</span>
      </button>
    </div>

    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <button
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm"
        @click="composing = true"
      >+ نامه جدید</button>

      <input
        v-model="filters.q" :class="inp" placeholder="جستجو در موضوع و متن…"
        class="flex-1 min-w-[12rem]" @keydown.enter="load"
      />

      <button
        class="text-sm text-slate-500 hover:text-ink px-3 py-2"
        @click="showFilters = !showFilters"
      >{{ showFilters ? "بستن فیلتر" : "فیلتر بیشتر" }}</button>

      <span class="text-xs text-slate-400 ltr-nums">{{ num(total) }} نامه</span>
    </div>

    <div v-if="showFilters" class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <select v-model="filters.sender" :class="inp">
        <option value="">همه فرستنده‌ها</option>
        <option v-for="p in people" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
      <select v-model="filters.read" :class="inp">
        <option value="">خوانده و نخوانده</option>
        <option value="0">فقط نخوانده</option>
        <option value="1">فقط خوانده</option>
      </select>
      <input v-model="filters.from" type="date" :class="inp" dir="ltr" />
      <input v-model="filters.to" type="date" :class="inp" dir="ltr" />
      <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm" @click="load">
        اعمال فیلتر
      </button>
    </div>

    <p
      v-if="error"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3 whitespace-pre-line"
    >{{ error }}</p>

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 8" :key="i" class="h-16 rounded-xl" />
    </div>

    <EmptyState
      v-else-if="!rows.length"
      :title="box === 'inbox' ? 'نامه‌ای در صندوق ورودی نیست' : 'چیزی اینجا نیست'"
      hint="با «نامه جدید» اولین نامه را بنویسید."
    />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden divide-y divide-slate-100">
      <button
        v-for="row in rows" :key="row.id"
        class="w-full text-right px-4 py-3 hover:bg-slate-50 flex items-start gap-3 transition-colors"
        @click="open(row)"
      >
        <span
          class="mt-1.5 w-2 h-2 rounded-full shrink-0"
          :class="box === 'inbox' && !row.my_read_at ? 'bg-red-500' : 'bg-transparent'"
        ></span>

        <UserAvatar :user="row.sender_detail as any" :size="34" class="shrink-0 mt-0.5" />

        <span class="min-w-0 flex-1">
          <span class="flex items-baseline gap-2">
            <span class="text-sm truncate" :class="rowWeight(row)">{{ row.subject }}</span>
            <span
              v-for="t in row.tags_detail" :key="t.id"
              class="text-[10px] rounded-full px-2 py-0.5 bg-slate-100 text-slate-500 shrink-0"
            >{{ t.name_fa }}</span>
          </span>
          <span class="block text-xs text-slate-400 truncate mt-0.5">
            {{ box === "outbox" || box === "draft"
              ? `به ${row.recipient_names.join("، ") || "—"}`
              : row.sender_detail.name }}
            <template v-if="row.preview"> · {{ row.preview }}</template>
          </span>
        </span>

        <span class="text-left shrink-0 text-xs">
          <span class="block text-slate-400 ltr-nums">
            {{ row.sent_at ? faDate(row.sent_at) : "پیش‌نویس" }}
          </span>
          <span class="flex items-center justify-end gap-1.5 mt-1 text-slate-400">
            <span v-if="row.attachment_count" class="ltr-nums">
              📎 {{ num(row.attachment_count) }}
            </span>
            <span v-if="box === 'outbox'" class="ltr-nums">
              {{ num(row.read_count) }}/{{ num(row.recipient_count) }} خوانده
            </span>
            <span v-if="row.number" class="ltr-nums">{{ row.number }}</span>
          </span>
        </span>
      </button>
    </div>

    <LetterForm v-if="composing" @close="composing = false" @saved="onSaved" />
    <LetterForm
      v-if="editing && editDraft"
      :draft="editDraft"
      @close="editing = null"
      @saved="onSaved"
    />
  </div>
</template>
