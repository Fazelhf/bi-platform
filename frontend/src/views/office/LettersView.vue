<script setup lang="ts">
/**
 * مکاتبات — five mailboxes over the same two tables.
 *
 * The redesign is mostly about weight. The first version gave a read letter,
 * an unread one and a draft the same visual mass, so a full inbox was a wall
 * of grey text. Now:
 *
 * **Unread has a coloured spine and a solid title.** Read letters recede.
 * That single difference is what makes an inbox scannable.
 * **Filters hide until asked for.** Five controls on permanent display taught
 * everyone to ignore the row they sit in.
 * **The tags are on the row**, because «کدام نامه مربوط به گمرک بود» is how
 * people look for letters, and it was already stored and never shown well.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { officeApi, type Box, type LetterRow, type LetterTag, type Person } from "@/api/office";
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
const tags = ref<LetterTag[]>([]);
const loading = ref(true);
const error = ref("");
const composing = ref(false);
const showFilters = ref(false);

const filters = ref({
  q: "", sender: "" as number | "", tag: "" as number | "",
  read: "", from: "", to: "",
});

const activeFilters = computed(
  () => Object.entries(filters.value).filter(([, v]) => v !== "").length,
);

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
  officeApi.people().then((d) => {
    people.value = d.people;
    tags.value = d.tags;
  }).catch(() => {});
  await load();
});

watch(box, load);

const editing = ref<number | null>(null);
const editDraft = ref<any>(null);

watch(editing, async (id) => {
  editDraft.value = id ? await officeApi.letter(id) : null;
});

function open(row: LetterRow) {
  // A draft has nothing to show yet — it reopens in the composer instead.
  if (row.status === "draft") {
    editing.value = row.id;
    return;
  }
  router.push({ name: "office-letter", params: { id: row.id } });
}

function onSaved(sent: boolean) {
  composing.value = false;
  editing.value = null;
  // A sent draft leaves the drafts box, so land where it actually went.
  if (sent && box.value === "draft") box.value = "outbox";
  else load();
}

function isUnread(row: LetterRow): boolean {
  return box.value === "inbox" && !row.my_read_at;
}

function clearFilters() {
  filters.value = { q: "", sender: "", tag: "", read: "", from: "", to: "" };
  load();
}

const inp =
  "bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
</script>

<template>
  <div class="space-y-4">
    <!-- Boxes + compose, one strip -->
    <div class="bg-surface rounded-card shadow-soft p-2 flex flex-wrap items-center gap-1">
      <button
        v-for="b in BOXES" :key="b.key"
        class="office-tab px-3.5 py-2 rounded-xl text-sm flex items-center gap-2"
        :class="box === b.key ? 'is-active' : 'text-slate-500'"
        @click="box = b.key"
      >
        {{ b.label }}
        <span
          v-if="b.key === 'inbox' && unread"
          class="text-[11px] rounded-full px-1.5 py-0.5 ltr-nums"
          :class="box === b.key ? 'bg-white/25' : 'bg-red-500 text-white'"
        >{{ num(unread) }}</span>
      </button>

      <span class="flex-1"></span>

      <button
        class="office-btn rounded-xl px-4 py-2 text-sm"
        @click="composing = true"
      >+ نامه جدید</button>
    </div>

    <!-- Search always; the rest on request -->
    <div class="bg-surface rounded-card shadow-soft p-3 space-y-3">
      <div class="flex flex-wrap items-center gap-2">
        <input
          v-model="filters.q" :class="inp" class="flex-1 min-w-[12rem]"
          placeholder="جستجو در موضوع، متن و شماره…" @keydown.enter="load"
        />
        <button
          class="text-sm px-3 py-2 rounded-xl transition-colors flex items-center gap-1.5"
          :class="showFilters || activeFilters
            ? 'bg-slate-100 text-ink' : 'text-slate-500 hover:bg-slate-100'"
          @click="showFilters = !showFilters"
        >
          فیلتر
          <span
            v-if="activeFilters"
            class="text-[10px] text-white rounded-full px-1.5 ltr-nums"
            :style="{ background: 'var(--sec-solid)' }"
          >{{ num(activeFilters) }}</span>
        </button>
        <span class="text-xs text-slate-400 ltr-nums">{{ num(total) }} نامه</span>
      </div>

      <div v-if="showFilters" class="flex flex-wrap items-center gap-2 pt-1 border-t border-slate-100">
        <select v-model="filters.sender" :class="inp">
          <option value="">همه فرستنده‌ها</option>
          <option v-for="p in people" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <select v-model="filters.tag" :class="inp">
          <option value="">همه برچسب‌ها</option>
          <option v-for="t in tags" :key="t.id" :value="t.id">{{ t.name_fa }}</option>
        </select>
        <select v-model="filters.read" :class="inp">
          <option value="">خوانده و نخوانده</option>
          <option value="0">فقط نخوانده</option>
          <option value="1">فقط خوانده</option>
        </select>
        <input v-model="filters.from" type="date" :class="inp" dir="ltr" />
        <input v-model="filters.to" type="date" :class="inp" dir="ltr" />
        <button
          class="office-btn rounded-xl px-4 py-2 text-sm"
          @click="load"
        >اعمال</button>
        <button
          v-if="activeFilters"
          class="text-sm text-slate-500 hover:text-ink px-3 py-2"
          @click="clearFilters"
        >پاک کردن</button>
      </div>
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
      :hint="activeFilters ? 'شاید فیلترها را پاک کنید.' : 'با «نامه جدید» اولین نامه را بنویسید.'"
    />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden divide-y divide-slate-100">
      <button
        v-for="row in rows" :key="row.id"
        class="w-full text-right flex items-stretch gap-0 hover:bg-slate-50 transition-colors"
        @click="open(row)"
      >
        <!-- Unread gets a spine in the section's colour. -->
        <span
          class="w-1 shrink-0"
          :class="isUnread(row) ? 'office-spine' : ''"
        ></span>

        <span class="flex items-start gap-3 px-3 py-3 flex-1 min-w-0">
          <UserAvatar :user="row.sender_detail as any" :size="36" class="shrink-0 mt-0.5" />

          <span class="min-w-0 flex-1">
            <span class="flex items-baseline gap-2">
              <span
                class="text-sm truncate"
                :class="isUnread(row) ? 'font-bold text-ink' : 'text-slate-600'"
              >{{ row.subject }}</span>
              <span
                v-for="t in row.tags_detail" :key="t.id"
                class="text-[10px] rounded-full px-2 py-0.5 shrink-0"
                :class="t.color ? 'office-tag' : 'bg-slate-100 text-slate-500'"
                :style="t.color ? { '--tag': t.color } : {}"
              >{{ t.name_fa }}</span>
            </span>
            <span class="block text-xs text-slate-400 truncate mt-0.5">
              <span :class="isUnread(row) ? 'text-slate-600' : ''">
                {{ box === "outbox" || box === "draft"
                  ? `به ${row.recipient_names.join("، ") || "—"}`
                  : row.sender_detail.name }}
              </span>
              <template v-if="row.preview"> — {{ row.preview }}</template>
            </span>
          </span>

          <span class="text-left shrink-0 text-xs flex flex-col items-end gap-1">
            <span class="text-slate-400 ltr-nums">
              {{ row.sent_at ? faDate(row.sent_at) : "پیش‌نویس" }}
            </span>
            <span class="flex items-center gap-1.5 text-slate-400">
              <span v-if="row.attachment_count" class="ltr-nums">
                📎 {{ num(row.attachment_count) }}
              </span>
              <span
                v-if="box === 'outbox'"
                class="ltr-nums rounded-full px-1.5 bg-slate-100"
              >{{ num(row.read_count) }}/{{ num(row.recipient_count) }}</span>
              <span v-if="row.number" class="ltr-nums opacity-70">{{ row.number }}</span>
            </span>
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
