<script setup lang="ts">
/**
 * مکاتبات — mailboxes, a list, and a reading pane.
 *
 * Three columns on a wide screen, the way every mail client people already
 * know is laid out: folders | letters | the open letter. Reading a letter no
 * longer throws the list away, so working down an inbox is click, read,
 * archive, next — not click, read, back, find your place, next.
 *
 *   • Search runs as you type (debounced); filters apply the moment they
 *     change. There is no «اعمال» button to forget.
 *   • Box, search, filters and the open letter live in the URL, so a view can
 *     be bookmarked, shared, or survive a refresh.
 *   • ↑/↓ move through the list and open as they go; the pane reports back
 *     what changed (read, archived) and the row updates in place.
 *   • Below the wide breakpoint the pane gives way: a tap opens the letter on
 *     its own page, which is the same LetterReader.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { officeApi, type Box, type LetterRow, type LetterTag, type Person } from "@/api/office";
import { apiError, faDate } from "@/utils/adminFormat";
import { num } from "@/utils/format";
import { toast } from "@/composables/useUi";
import LetterForm from "@/components/office/LetterForm.vue";
import LetterReader from "@/components/office/LetterReader.vue";
import JalaliDateField from "@/components/JalaliDateField.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";
import NavIcon from "@/components/NavIcon.vue";

const route = useRoute();
const router = useRouter();

const BOXES: { key: Box; label: string; icon: string; empty: string }[] = [
  { key: "inbox", label: "صندوق ورودی", icon: "inbox", empty: "صندوق ورودی خالی است." },
  { key: "outbox", label: "ارسال‌شده", icon: "send", empty: "هنوز نامه‌ای نفرستاده‌اید." },
  { key: "paraph", label: "پاراف‌های من", icon: "stamp", empty: "نامه‌ای را پاراف نکرده‌اید." },
  { key: "draft", label: "پیش‌نویس‌ها", icon: "pencil", empty: "پیش‌نویسی ندارید." },
  { key: "archive", label: "بایگانی", icon: "archive", empty: "بایگانی خالی است." },
];

// -- state, seeded from the URL ------------------------------------------
const q0 = route.query;
const box = ref<Box>(BOXES.some((b) => b.key === q0.box) ? (q0.box as Box) : "inbox");
const search = ref(String(q0.q ?? ""));
const filters = ref({
  sender: q0.sender ? Number(q0.sender) : ("" as number | ""),
  tag: q0.tag ? Number(q0.tag) : ("" as number | ""),
  read: String(q0.read ?? ""),
  from: String(q0.from ?? ""),
  to: String(q0.to ?? ""),
});
const selectedId = ref<number | null>(q0.id ? Number(q0.id) : null);

const rows = ref<LetterRow[]>([]);
const unread = ref(0);
const total = ref(0);
const people = ref<Person[]>([]);
const tags = ref<LetterTag[]>([]);
const loading = ref(true);
const error = ref("");
const composing = ref(false);
const showFilters = ref(Object.values(filters.value).some((v) => v !== ""));

const activeFilters = computed(
  () => Object.values(filters.value).filter((v) => v !== "").length,
);
const boxMeta = computed(() => BOXES.find((b) => b.key === box.value)!);

// -- wide screen? (the pane exists only from lg up) ---------------------
const wide = ref(true);
let mq: MediaQueryList | null = null;
const onMq = () => (wide.value = !!mq?.matches);

// -- loading ------------------------------------------------------------
let seq = 0;
async function load() {
  const mine = ++seq;
  loading.value = true;
  error.value = "";
  try {
    const data = await officeApi.mailbox(box.value, { q: search.value.trim(), ...filters.value });
    if (mine !== seq) return; // a newer request already answered
    rows.value = data.rows;
    unread.value = data.unread;
    total.value = data.count;
  } catch (e) {
    if (mine === seq) error.value = apiError(e);
  } finally {
    if (mine === seq) loading.value = false;
  }
}

function syncUrl() {
  const query: Record<string, string> = {};
  if (box.value !== "inbox") query.box = box.value;
  if (search.value.trim()) query.q = search.value.trim();
  for (const [k, v] of Object.entries(filters.value)) if (v !== "") query[k] = String(v);
  if (selectedId.value) query.id = String(selectedId.value);
  router.replace({ query });
}

let debounce: number | undefined;
watch(search, () => {
  window.clearTimeout(debounce);
  debounce = window.setTimeout(() => { load(); syncUrl(); }, 300);
});
watch(filters, () => { load(); syncUrl(); }, { deep: true });
watch(box, () => {
  selectedId.value = null;
  // «فقط نخوانده» only means something in the inbox.
  if (box.value !== "inbox") filters.value.read = "";
  load();
  syncUrl();
});
watch(selectedId, syncUrl);
// A «در پاسخ به» link inside the pane navigates with ?id=.
watch(() => route.query.id, (v) => {
  const id = v ? Number(v) : null;
  if (id !== selectedId.value) selectedId.value = id;
});

onMounted(async () => {
  mq = window.matchMedia("(min-width: 1024px)");
  onMq();
  mq.addEventListener("change", onMq);
  officeApi.people().then((d) => {
    people.value = d.people;
    tags.value = d.tags;
  }).catch(() => {});
  await load();
  // Arriving on a phone with ?id= (an old link): open it full-page.
  if (selectedId.value && !wide.value) {
    router.push({ name: "office-letter", params: { id: selectedId.value } });
  }
});
onBeforeUnmount(() => {
  mq?.removeEventListener("change", onMq);
  window.clearTimeout(debounce);
});

// -- opening ------------------------------------------------------------
const editing = ref<number | null>(null);
const editDraft = ref<any>(null);
watch(editing, async (id) => {
  editDraft.value = null;
  if (!id) return;
  try {
    editDraft.value = await officeApi.letter(id);
  } catch (e) {
    editing.value = null;
    toast.error(apiError(e));
  }
});

function open(row: LetterRow) {
  // A draft has nothing to read yet — it reopens in the composer.
  if (row.status === "draft") {
    editing.value = row.id;
    return;
  }
  if (!wide.value) {
    router.push({ name: "office-letter", params: { id: row.id } });
    return;
  }
  selectedId.value = row.id;
}

/** The pane read or archived something; mirror it on the row. */
function onChanged(patch: { id: number; my_read_at?: string | null; my_archived_at?: string | null }) {
  const row = rows.value.find((r) => r.id === patch.id);
  if (!row) return;
  if (patch.my_read_at !== undefined && !row.my_read_at && patch.my_read_at && box.value === "inbox") {
    unread.value = Math.max(0, unread.value - 1);
  }
  if (patch.my_read_at !== undefined) row.my_read_at = patch.my_read_at;
  if (patch.my_archived_at !== undefined) {
    row.my_archived_at = patch.my_archived_at;
    // Filed away from the inbox (or restored from the archive): it no
    // longer belongs in this box. Move on to the next one.
    const leaves = (box.value === "inbox" && patch.my_archived_at)
      || (box.value === "archive" && !patch.my_archived_at);
    if (leaves) {
      const i = rows.value.indexOf(row);
      rows.value.splice(i, 1);
      total.value = Math.max(0, total.value - 1);
      const next = rows.value[i] ?? rows.value[i - 1];
      selectedId.value = next && next.status !== "draft" ? next.id : null;
    }
  }
}

function onSaved(sent: boolean) {
  composing.value = false;
  editing.value = null;
  toast.success(sent ? "نامه ارسال شد." : "پیش‌نویس ذخیره شد.");
  if (sent && box.value === "draft") box.value = "outbox";
  else load();
}

async function removeDraft(row: LetterRow) {
  try {
    await officeApi.remove(row.id);
    rows.value = rows.value.filter((r) => r.id !== row.id);
    total.value = Math.max(0, total.value - 1);
    toast.success("پیش‌نویس حذف شد.");
  } catch (e) {
    toast.error(apiError(e));
  }
}

function isUnread(row: LetterRow): boolean {
  return box.value === "inbox" && !row.my_read_at;
}

function clearFilters() {
  filters.value = { sender: "", tag: "", read: "", from: "", to: "" };
}

/** Today: the time. Otherwise: the date. */
function stamp(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  return d.toDateString() === now.toDateString()
    ? new Intl.DateTimeFormat("fa-IR", { hour: "2-digit", minute: "2-digit" }).format(d)
    : faDate(iso);
}

// -- keyboard -----------------------------------------------------------
const listEl = ref<HTMLElement | null>(null);
function onListKey(e: KeyboardEvent) {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  e.preventDefault();
  const i = rows.value.findIndex((r) => r.id === selectedId.value);
  const next = rows.value[Math.min(rows.value.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1)))];
  if (!next) return;
  if (next.status === "draft") selectedId.value = null;
  else open(next);
  listEl.value?.querySelector<HTMLElement>(`[data-row="${next.id}"]`)?.focus();
}
</script>

<template>
  <div class="flex gap-4 lg:h-[calc(100vh-9rem)]">
    <!-- ============ Folders (xl+) ============ -->
    <aside class="hidden xl:flex flex-col w-56 shrink-0 office-card p-2.5 gap-1">
      <button class="office-btn w-full mb-2" @click="composing = true">
        <NavIcon name="pencil" :size="16" /> نامه جدید
      </button>
      <button
        v-for="b in BOXES" :key="b.key"
        class="office-row flex items-center gap-2.5 rounded-lg px-3 h-9 text-sm text-right"
        :class="box === b.key ? 'is-selected font-semibold text-ink' : 'text-slate-600'"
        @click="box = b.key"
      >
        <NavIcon :name="b.icon" :size="17" />
        <span class="flex-1">{{ b.label }}</span>
        <span v-if="b.key === 'inbox' && unread" class="office-count is-alert ltr-nums">{{ num(unread) }}</span>
      </button>

      <template v-if="tags.length">
        <p class="office-label px-3 mt-4">برچسب‌ها</p>
        <button
          v-for="t in tags" :key="t.id"
          class="office-row flex items-center gap-2.5 rounded-lg px-3 h-8 text-xs text-right"
          :class="filters.tag === t.id ? 'is-selected text-ink font-medium' : 'text-slate-500'"
          @click="filters.tag = filters.tag === t.id ? '' : t.id; showFilters = true"
        >
          <span
            class="w-2.5 h-2.5 rounded-full shrink-0"
            :style="{ background: t.color || 'rgb(var(--c-slate-300))' }"
          ></span>
          <span class="flex-1 truncate">{{ t.name_fa }}</span>
        </button>
      </template>
    </aside>

    <!-- ============ List ============ -->
    <section class="office-card flex flex-col w-full lg:w-[25rem] shrink-0 min-h-[60vh] lg:min-h-0">
      <div class="p-3 space-y-2.5 border-b border-slate-100">
        <!-- Boxes as a strip below xl -->
        <div class="flex xl:hidden items-center gap-2">
          <div class="office-seg overflow-x-auto max-w-full flex-1 no-scrollbar">
            <button
              v-for="b in BOXES" :key="b.key"
              :class="{ 'is-active': box === b.key }"
              @click="box = b.key"
            >
              {{ b.label }}
              <span v-if="b.key === 'inbox' && unread" class="office-count is-alert ltr-nums">{{ num(unread) }}</span>
            </button>
          </div>
          <button class="office-btn !px-3 shrink-0" aria-label="نامه جدید" @click="composing = true">
            <NavIcon name="pencil" :size="16" /><span class="hidden sm:inline">نامه جدید</span>
          </button>
        </div>

        <div class="flex items-center gap-2">
          <label class="office-search flex-1">
            <NavIcon name="search" :size="16" />
            <input v-model="search" class="office-input" placeholder="جستجو در موضوع، متن و شماره…" />
          </label>
          <button
            class="office-icon-btn !w-9 !h-9 relative shrink-0"
            :class="{ 'is-on !bg-slate-100': showFilters || activeFilters }"
            :aria-label="'فیلتر'"
            title="فیلتر"
            @click="showFilters = !showFilters"
          >
            <NavIcon name="filter" :size="17" />
            <span
              v-if="activeFilters"
              class="absolute -top-1 -left-1 office-count is-alert !min-w-[1rem] !leading-4 !text-[10px] ltr-nums"
            >{{ num(activeFilters) }}</span>
          </button>
        </div>

        <div v-if="showFilters" class="grid grid-cols-2 gap-2">
          <select v-model="filters.sender" class="office-select col-span-2 sm:col-span-1">
            <option value="">همه‌ی فرستنده‌ها</option>
            <option v-for="p in people" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
          <select v-model="filters.tag" class="office-select col-span-2 sm:col-span-1">
            <option value="">همه‌ی برچسب‌ها</option>
            <option v-for="t in tags" :key="t.id" :value="t.id">{{ t.name_fa }}</option>
          </select>
          <select v-if="box === 'inbox'" v-model="filters.read" class="office-select col-span-2">
            <option value="">خوانده و نخوانده</option>
            <option value="0">فقط نخوانده</option>
            <option value="1">فقط خوانده</option>
          </select>
          <JalaliDateField v-model="filters.from" placeholder="از تاریخ" />
          <JalaliDateField v-model="filters.to" placeholder="تا تاریخ" />
          <button v-if="activeFilters" class="office-btn-ghost col-span-2 !h-8 text-xs" @click="clearFilters">
            <NavIcon name="close" :size="13" /> پاک کردن فیلترها
          </button>
        </div>

        <p class="text-[11px] text-slate-400 flex items-center gap-1.5">
          <NavIcon :name="boxMeta.icon" :size="12" />
          {{ boxMeta.label }} · <span class="ltr-nums">{{ num(total) }}</span> نامه
          <template v-if="total > rows.length">
            (نمایش <span class="ltr-nums">{{ num(rows.length) }}</span> مورد اخیر)
          </template>
        </p>
      </div>

      <div v-if="error" class="m-3 flex items-center gap-2 bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2.5">
        <NavIcon name="alert" :size="16" class="shrink-0" />
        <span class="flex-1">{{ error }}</span>
        <button class="office-btn-ghost !h-7 text-xs" @click="load">تلاش دوباره</button>
      </div>

      <div v-if="loading && !rows.length" class="p-3 space-y-2">
        <Skeleton v-for="i in 7" :key="i" class="h-[4.5rem] rounded-xl" />
      </div>

      <div
        v-else-if="!rows.length && !error"
        class="flex-1 flex flex-col items-center justify-center gap-3 p-8 text-center text-slate-400"
      >
        <span class="w-14 h-14 rounded-full bg-slate-100 grid place-items-center">
          <NavIcon :name="boxMeta.icon" :size="24" />
        </span>
        <p class="text-sm">{{ search || activeFilters ? "نامه‌ای با این جستجو پیدا نشد." : boxMeta.empty }}</p>
        <button v-if="activeFilters || search" class="office-btn-subtle" @click="clearFilters(); search = ''">
          پاک کردن جستجو و فیلترها
        </button>
      </div>

      <div
        v-else
        ref="listEl"
        class="flex-1 overflow-y-auto divide-y divide-slate-100 transition-opacity"
        :class="loading ? 'opacity-60' : ''"
        @keydown="onListKey"
      >
        <div
          v-for="row in rows" :key="row.id"
          :data-row="row.id"
          tabindex="0"
          role="button"
          class="office-row group/row relative flex gap-3 px-3 py-3 cursor-pointer outline-none"
          :class="{ 'is-selected': selectedId === row.id }"
          @click="open(row)"
          @keydown.enter="open(row)"
        >
          <span
            v-if="isUnread(row)"
            class="absolute right-0 top-3 bottom-3 w-[3px] rounded-l-full office-spine"
          ></span>

          <UserAvatar :user="row.sender_detail" :size="34" class="mt-0.5" />

          <div class="min-w-0 flex-1">
            <div class="flex items-baseline gap-2">
              <span
                class="flex-1 text-[13px] truncate"
                :class="isUnread(row) ? 'font-bold text-ink' : 'text-slate-600'"
              >
                {{ box === "outbox" || box === "draft"
                  ? `به ${row.recipient_names.join("، ") || "—"}`
                  : row.sender_detail.name }}
              </span>
              <span
                class="text-[11px] ltr-nums shrink-0"
                :class="isUnread(row) ? 'text-ink font-semibold' : 'text-slate-400'"
              >{{ row.sent_at ? stamp(row.sent_at) : "پیش‌نویس" }}</span>
            </div>

            <p
              class="text-sm truncate mt-0.5"
              :class="isUnread(row) ? 'font-semibold text-ink' : 'text-ink'"
            >{{ row.subject }}</p>

            <p v-if="row.preview" class="text-xs text-slate-400 truncate mt-0.5">{{ row.preview }}</p>

            <div
              v-if="row.tags_detail.length || row.attachment_count || row.number || box === 'outbox'"
              class="flex flex-wrap items-center gap-1.5 mt-1.5 text-[10px]"
            >
              <span
                v-for="t in row.tags_detail" :key="t.id"
                class="rounded-full px-2 py-0.5"
                :class="t.color ? 'office-tag' : 'bg-slate-100 text-slate-500'"
                :style="t.color ? { '--tag': t.color } : {}"
              >{{ t.name_fa }}</span>
              <span v-if="row.attachment_count" class="flex items-center gap-0.5 text-slate-400 ltr-nums">
                <NavIcon name="paperclip" :size="11" /> {{ num(row.attachment_count) }}
              </span>
              <span
                v-if="box === 'outbox'"
                class="flex items-center gap-0.5 text-slate-400 ltr-nums"
                :title="`${row.read_count} از ${row.recipient_count} نفر خوانده‌اند`"
              >
                <NavIcon name="eye" :size="11" /> {{ num(row.read_count) }}/{{ num(row.recipient_count) }}
              </span>
              <span class="flex-1"></span>
              <span v-if="row.number" class="text-slate-400 ltr-nums">{{ row.number }}</span>
            </div>
          </div>

          <button
            v-if="row.status === 'draft'"
            class="office-icon-btn !w-7 !h-7 self-center opacity-0 group-hover/row:opacity-100 focus:opacity-100"
            aria-label="حذف پیش‌نویس"
            title="حذف پیش‌نویس"
            @click.stop="removeDraft(row)"
          ><NavIcon name="trash" :size="14" /></button>
        </div>
      </div>
    </section>

    <!-- ============ Reading pane (lg+) ============ -->
    <section v-if="wide" class="office-card flex-1 min-w-0 overflow-hidden flex flex-col">
      <LetterReader
        v-if="selectedId"
        :id="selectedId"
        embedded
        @close="selectedId = null"
        @changed="onChanged"
        @replied="box === 'outbox' && load()"
      />
      <div v-else class="flex-1 flex flex-col items-center justify-center gap-3 text-slate-400 p-8 text-center">
        <span class="w-16 h-16 rounded-full bg-slate-100 grid place-items-center">
          <NavIcon name="inbox" :size="28" />
        </span>
        <p class="text-sm">نامه‌ای را از فهرست انتخاب کنید تا اینجا باز شود.</p>
        <p class="text-xs">با کلیدهای ↑ و ↓ بین نامه‌ها جابه‌جا شوید.</p>
      </div>
    </section>

    <LetterForm v-if="composing" @close="composing = false" @saved="onSaved" />
    <LetterForm v-if="editing && editDraft" :draft="editDraft" @close="editing = null" @saved="onSaved" />
  </div>
</template>
