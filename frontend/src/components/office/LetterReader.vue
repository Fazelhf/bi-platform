<script setup lang="ts">
/**
 * One letter, and everything that happened to it after it was sent.
 *
 * Shared by the reading pane beside the mailbox and the full-page route a
 * notification opens, so both behave identically. Two zones, kept visibly
 * apart because they mean different things:
 *
 *   • **the document** — subject, number, people, body, attachments. Fixed
 *     once sent, so it is drawn as a sheet of paper;
 *   • **the گردش** — paraphs, referrals and notes, drawn as a timeline. That
 *     is internal workflow, not part of what was written.
 *
 * Actions update the pane in place and tell the parent what changed, so the
 * mailbox row behind it stays in step without a reload.
 */
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { officeApi, type Letter, type LetterAction, type Person } from "@/api/office";
import { apiError, faDate, faDateTime } from "@/utils/adminFormat";
import { num } from "@/utils/format";
import { toast } from "@/composables/useUi";
import { useAuthStore } from "@/stores/auth";
import LetterForm from "@/components/office/LetterForm.vue";
import PeoplePicker from "@/components/office/PeoplePicker.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";
import NavIcon from "@/components/NavIcon.vue";

const props = defineProps<{
  id: number;
  /** In the side pane: show a close button instead of «back». */
  embedded?: boolean;
}>();

const emit = defineEmits<{
  (e: "close"): void;
  /** The caller's own copy changed (read / archived). */
  (e: "changed", patch: { id: number; my_read_at?: string | null; my_archived_at?: string | null }): void;
  (e: "replied"): void;
}>();

const router = useRouter();
const auth = useAuthStore();

const letter = ref<Letter | null>(null);
const people = ref<Person[]>([]);
const loading = ref(true);
const error = ref("");
const busy = ref(false);
const replying = ref(false);

type Panel = "" | "paraph" | "refer" | "note";
const panel = ref<Panel>("");
const noteText = ref("");
const referTo = ref<number[]>([]);
/** Whether people referred to may read the گردش from before they arrived. */
const seesHistory = ref(true);
/** A private entry is addressed: `privateTo` is who may read it. */
const isPrivate = ref(false);
const privateTo = ref<number[]>([]);

let peopleLoaded = false;

async function load() {
  loading.value = true;
  error.value = "";
  panel.value = "";
  try {
    letter.value = await officeApi.letter(props.id);
    // Opening it is what marked it read, server-side.
    emit("changed", { id: props.id, my_read_at: letter.value.my_read_at ?? new Date().toISOString() });
  } catch (e: any) {
    letter.value = null;
    error.value = e?.response?.status === 404
      ? "این نامه پیدا نشد یا به آن دسترسی ندارید."
      : apiError(e);
  } finally {
    loading.value = false;
  }
  if (!peopleLoaded) {
    peopleLoaded = true;
    officeApi.people().then((d) => (people.value = d.people)).catch(() => {});
  }
}

watch(() => props.id, load, { immediate: true });

const isArchived = computed(() => !!letter.value?.my_archived_at);
const toList = computed(() => letter.value?.recipients.filter((r) => r.kind === "to") ?? []);
const ccList = computed(() => letter.value?.recipients.filter((r) => r.kind === "cc") ?? []);
/** Archiving is per-copy: only someone the letter was sent to has one. */
const amRecipient = computed(
  () => !!letter.value?.recipients.some((r) => r.user === auth.me?.id),
);
const withheld = computed(() => letter.value?.recipients.filter((r) => !r.sees_history) ?? []);

function resetPanel() {
  panel.value = "";
  noteText.value = "";
  referTo.value = [];
  isPrivate.value = false;
  privateTo.value = [];
  seesHistory.value = true;
}

function openPanel(p: Panel) {
  const same = panel.value === p;
  resetPanel();
  if (!same) panel.value = p;
}

const canSubmit = computed(() => {
  if (busy.value) return false;
  if (isPrivate.value && !privateTo.value.length) return false;
  if (panel.value === "refer") return referTo.value.length > 0;
  if (panel.value === "note") return !!noteText.value.trim();
  return true;
});

const PANEL_TEXT: Record<Exclude<Panel, "">, { title: string; done: string; placeholder: string }> = {
  paraph: { title: "پاراف", done: "پاراف ثبت شد.", placeholder: "یادداشت پاراف (اختیاری)…" },
  refer: { title: "ارجاع", done: "ارجاع انجام شد.", placeholder: "دستور یا توضیح ارجاع…" },
  note: { title: "یادداشت", done: "یادداشت ثبت شد.", placeholder: "متن یادداشت…" },
};

async function submitPanel() {
  if (!canSubmit.value || !letter.value || !panel.value) return;
  const id = letter.value.id;
  const secret = isPrivate.value ? privateTo.value[0] : undefined;
  const kind = panel.value;
  busy.value = true;
  try {
    let added: LetterAction[] = [];
    if (kind === "paraph") {
      added = [await officeApi.paraph(id, noteText.value, isPrivate.value, secret)];
    } else if (kind === "note") {
      added = [await officeApi.note(id, noteText.value, isPrivate.value, secret)];
    } else {
      // A referral to three people is three referrals: one row each in the
      // chain, so «به چه کسی ارجاع شد» stays answerable per person.
      added = await Promise.all(
        referTo.value.map((to) => officeApi.refer(id, to, noteText.value, seesHistory.value)),
      );
    }
    letter.value.actions.push(...added);
    toast.success(PANEL_TEXT[kind].done);
    resetPanel();
    // Referral can add recipients — refresh the people strip quietly.
    if (kind === "refer") officeApi.letter(id).then((l) => (letter.value = l)).catch(() => {});
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    busy.value = false;
  }
}

async function toggleArchive() {
  if (!letter.value) return;
  busy.value = true;
  try {
    const { archived_at } = await officeApi.archive(letter.value.id, isArchived.value);
    letter.value.my_archived_at = archived_at;
    emit("changed", { id: letter.value.id, my_archived_at: archived_at });
    toast.success(archived_at ? "به بایگانی رفت." : "از بایگانی خارج شد.");
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    busy.value = false;
  }
}

async function openAttachment(attId: number, name: string) {
  try {
    const file = await officeApi.attachment(letter.value!.id, attId);
    const a = document.createElement("a");
    a.href = file.content;
    a.download = name;
    a.click();
  } catch (e) {
    toast.error(apiError(e, "دریافت فایل انجام نشد."));
  }
}

/** Print just the letter sheet — see `.printing-letter` in office.css. */
function printLetter() {
  document.body.classList.add("printing-letter");
  const done = () => {
    document.body.classList.remove("printing-letter");
    window.removeEventListener("afterprint", done);
  };
  window.addEventListener("afterprint", done);
  window.print();
}

function kb(bytes: number): string {
  return bytes > 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

const ACTION_ICON: Record<string, string> = {
  paraph: "stamp", refer: "forward", note: "notes", archive: "archive",
};
</script>

<template>
  <div class="flex flex-col min-h-0 h-full">
    <!-- Loading / error -->
    <div v-if="loading" class="p-5 space-y-3">
      <Skeleton class="h-7 w-2/3 rounded-lg" />
      <Skeleton class="h-4 w-1/3 rounded-lg" />
      <Skeleton class="h-48 rounded-xl mt-4" />
    </div>

    <div v-else-if="error" class="flex-1 flex flex-col items-center justify-center gap-3 p-8 text-center">
      <span class="w-12 h-12 rounded-full bg-red-50 text-red-500 grid place-items-center">
        <NavIcon name="alert" :size="22" />
      </span>
      <p class="text-sm text-slate-600">{{ error }}</p>
      <button class="office-btn-subtle" @click="load"><NavIcon name="refresh" :size="15" /> تلاش دوباره</button>
    </div>

    <template v-else-if="letter">
      <!-- Toolbar -->
      <div class="flex items-center gap-1 px-3 sm:px-4 h-14 border-b border-slate-100 shrink-0">
        <button
          v-if="embedded"
          class="office-icon-btn"
          aria-label="بستن"
          title="بستن"
          @click="emit('close')"
        ><NavIcon name="close" :size="18" /></button>
        <button
          v-else
          class="office-icon-btn"
          aria-label="بازگشت به مکاتبات"
          title="بازگشت"
          @click="router.push({ name: 'office-letters' })"
        ><NavIcon name="arrow-right" :size="18" /></button>

        <span class="flex-1"></span>

        <button class="office-btn" @click="replying = true">
          <NavIcon name="reply" :size="16" /> پاسخ
        </button>
        <button
          class="office-btn-ghost"
          :class="{ '!bg-slate-100 !text-ink': panel === 'refer' }"
          @click="openPanel('refer')"
        ><NavIcon name="forward" :size="16" /> <span class="hidden sm:inline">ارجاع</span></button>
        <button
          class="office-btn-ghost"
          :class="{ '!bg-slate-100 !text-ink': panel === 'paraph' }"
          @click="openPanel('paraph')"
        ><NavIcon name="stamp" :size="16" /> <span class="hidden sm:inline">پاراف</span></button>
        <button
          class="office-btn-ghost"
          :class="{ '!bg-slate-100 !text-ink': panel === 'note' }"
          @click="openPanel('note')"
        ><NavIcon name="notes" :size="16" /> <span class="hidden sm:inline">یادداشت</span></button>
        <button
          v-if="amRecipient"
          class="office-icon-btn"
          :aria-label="isArchived ? 'خروج از بایگانی' : 'بایگانی'"
          :title="isArchived ? 'خروج از بایگانی' : 'بایگانی'"
          :disabled="busy"
          @click="toggleArchive"
        ><NavIcon name="archive" :size="18" /></button>
        <button
          class="office-icon-btn"
          aria-label="چاپ"
          title="چاپ"
          @click="printLetter"
        ><NavIcon name="printer" :size="18" /></button>
      </div>

      <div class="flex-1 overflow-y-auto">
        <!-- Action panel -->
        <div v-if="panel" class="m-3 sm:m-4 rounded-xl border border-slate-200 p-3.5 space-y-3 bg-slate-50/60">
          <p class="text-sm font-bold text-ink flex items-center gap-2">
            <NavIcon :name="ACTION_ICON[panel]" :size="16" /> {{ PANEL_TEXT[panel].title }}
          </p>

          <template v-if="panel === 'refer'">
            <PeoplePicker v-model="referTo" :people="people" placeholder="ارجاع به…" />
            <label class="flex items-start gap-2 text-xs text-slate-600 cursor-pointer">
              <input v-model="seesHistory" type="checkbox" class="mt-0.5" />
              <span>
                گردش قبلی نامه را ببیند
                <span class="block text-slate-400">اگر بردارید، فقط از همین ارجاع به بعد را می‌بیند.</span>
              </span>
            </label>
          </template>

          <textarea
            v-model="noteText"
            class="office-input"
            rows="3"
            :placeholder="PANEL_TEXT[panel].placeholder"
          ></textarea>

          <template v-if="panel !== 'refer'">
            <label class="flex items-center gap-2 text-xs text-slate-600 cursor-pointer">
              <input v-model="isPrivate" type="checkbox" />
              <span>خصوصی — فقط برای یک نفر</span>
            </label>
            <div v-if="isPrivate">
              <PeoplePicker v-model="privateTo" :people="people" placeholder="فقط این شخص ببیند…" />
              <p class="text-[11px] text-slate-400 mt-1">
                بقیه‌ی گیرندگان این را نمی‌بینند، حتی اگر گردش کامل را داشته باشند.
              </p>
            </div>
          </template>

          <div class="flex gap-2">
            <button class="office-btn" :disabled="!canSubmit" @click="submitPanel">
              {{ busy ? "در حال ثبت…" : "ثبت" }}
            </button>
            <button class="office-btn-ghost" @click="resetPanel">انصراف</button>
          </div>
        </div>

        <!-- The document -->
        <article class="letter-sheet m-3 sm:m-4 rounded-xl border border-slate-200 bg-surface">
          <header class="px-5 pt-5 pb-4 border-b border-slate-100">
            <div class="flex flex-wrap items-center gap-2 text-[11px] text-slate-500 mb-2">
              <span v-if="letter.number" class="office-chip rounded-md px-2 py-0.5 ltr-nums font-medium">
                {{ letter.number }}
              </span>
              <span v-if="letter.sent_at" class="flex items-center gap-1 ltr-nums">
                <NavIcon name="calendar" :size="12" /> {{ faDateTime(letter.sent_at) }}
              </span>
              <span
                v-for="t in letter.tags_detail" :key="t.id"
                class="rounded-full px-2 py-0.5"
                :class="t.color ? 'office-tag' : 'bg-slate-100 text-slate-500'"
                :style="t.color ? { '--tag': t.color } : {}"
              >{{ t.name_fa }}</span>
            </div>

            <h2 class="text-lg font-bold text-ink leading-8">{{ letter.subject }}</h2>

            <p v-if="letter.in_reply_to_detail" class="text-xs text-slate-500 mt-1">
              در پاسخ به
              <button
                class="underline underline-offset-2 hover:text-ink"
                @click="router.push({ name: 'office-letters', query: { id: letter.in_reply_to_detail.id } })"
              >{{ letter.in_reply_to_detail.number }} — {{ letter.in_reply_to_detail.subject }}</button>
            </p>

            <dl class="mt-4 grid grid-cols-[3.5rem_1fr] gap-x-3 gap-y-2 text-sm">
              <dt class="text-slate-400 text-xs pt-1">از</dt>
              <dd class="flex items-center gap-2">
                <UserAvatar :user="letter.sender_detail" :size="26" />
                <span class="text-ink font-medium">{{ letter.sender_detail.name }}</span>
                <span v-if="letter.sender_detail.job_title_fa" class="text-xs text-slate-400">
                  {{ letter.sender_detail.job_title_fa }}
                </span>
              </dd>

              <dt class="text-slate-400 text-xs pt-1">به</dt>
              <dd class="flex flex-wrap gap-1.5">
                <span
                  v-for="r in toList" :key="r.id"
                  class="inline-flex items-center gap-1.5 rounded-full bg-slate-100 pl-2.5 pr-0.5 py-0.5 text-xs text-ink"
                  :title="r.read_at ? `خوانده: ${faDateTime(r.read_at)}` : 'هنوز نخوانده'"
                >
                  <UserAvatar :user="r.user_detail" :size="20" />
                  {{ r.user_detail.name }}
                  <NavIcon v-if="r.read_at" name="check" :size="12" class="text-emerald-600" />
                </span>
                <span v-if="!toList.length" class="text-slate-400">—</span>
              </dd>

              <template v-if="ccList.length">
                <dt class="text-slate-400 text-xs pt-1">رونوشت</dt>
                <dd class="flex flex-wrap gap-1.5">
                  <span
                    v-for="r in ccList" :key="r.id"
                    class="inline-flex items-center gap-1.5 rounded-full bg-slate-100 pl-2.5 pr-0.5 py-0.5 text-xs text-slate-600"
                    :title="r.read_at ? `خوانده: ${faDateTime(r.read_at)}` : 'هنوز نخوانده'"
                  >
                    <UserAvatar :user="r.user_detail" :size="20" />
                    {{ r.user_detail.name }}
                    <NavIcon v-if="r.read_at" name="check" :size="12" class="text-emerald-600" />
                  </span>
                </dd>
              </template>
            </dl>

            <div class="flex flex-wrap gap-2 mt-3 text-[11px]">
              <span class="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-slate-500 ltr-nums">
                <NavIcon name="eye" :size="12" />
                {{ num(letter.read_count) }} از {{ num(letter.recipient_count) }} خوانده‌اند
              </span>
              <span
                v-if="withheld.length"
                class="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 text-amber-700"
                :title="withheld.map((r) => r.user_detail.name).join('، ')"
              >
                <NavIcon name="lock" :size="12" />
                {{ num(withheld.length) }} نفر بدون گردش قبلی
              </span>
            </div>
          </header>

          <div class="px-5 py-5 text-[0.9375rem] text-ink whitespace-pre-line leading-8">
            {{ letter.body || "—" }}
          </div>

          <footer v-if="letter.attachments.length" class="px-5 pb-5">
            <p class="office-label flex items-center gap-1">
              <NavIcon name="paperclip" :size="13" /> پیوست‌ها ({{ num(letter.attachments.length) }})
            </p>
            <div class="grid sm:grid-cols-2 gap-2">
              <button
                v-for="a in letter.attachments" :key="a.id"
                class="flex items-center gap-2.5 rounded-xl border border-slate-200 hover:border-slate-300
                       hover:bg-slate-50 px-3 py-2.5 text-right transition-colors"
                @click="openAttachment(a.id, a.name)"
              >
                <span class="w-8 h-8 rounded-lg bg-slate-100 text-slate-500 grid place-items-center shrink-0">
                  <NavIcon name="file" :size="16" />
                </span>
                <span class="min-w-0 flex-1">
                  <span class="block text-xs text-ink truncate">{{ a.name }}</span>
                  <span class="block text-[11px] text-slate-400 ltr-nums">{{ kb(a.size_bytes) }}</span>
                </span>
                <NavIcon name="download" :size="16" class="text-slate-400 shrink-0" />
              </button>
            </div>
          </footer>
        </article>

        <!-- The گردش -->
        <section class="mx-3 sm:mx-4 mb-6">
          <h3 class="office-label flex items-center gap-1.5 !mb-3">
            <NavIcon name="history" :size="14" /> گردش نامه
          </h3>
          <p v-if="!letter.actions.length" class="text-xs text-slate-400 py-3">
            هنوز اقدامی روی این نامه ثبت نشده.
          </p>
          <ol v-else class="relative border-r-2 border-slate-100 mr-3.5 space-y-4">
            <li v-for="a in letter.actions" :key="a.id" class="relative pr-6">
              <span
                class="absolute -right-[15px] top-0 w-7 h-7 rounded-full bg-surface border-2 border-slate-200
                       grid place-items-center text-slate-500"
              ><NavIcon :name="ACTION_ICON[a.kind] ?? 'activity'" :size="13" /></span>
              <div class="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-sm">
                <span class="font-semibold text-ink">{{ a.actor_detail.name }}</span>
                <span class="text-slate-500">{{ a.kind_label }}</span>
                <template v-if="a.to_user_detail">
                  <span class="text-slate-400">به</span>
                  <span class="font-medium text-ink">{{ a.to_user_detail.name }}</span>
                </template>
                <span
                  v-if="a.is_private"
                  class="inline-flex items-center gap-1 text-[10px] rounded-full px-2 py-0.5 bg-amber-100 text-amber-700"
                ><NavIcon name="lock" :size="10" /> خصوصی</span>
                <span class="flex-1"></span>
                <span class="text-[11px] text-slate-400 ltr-nums" :title="faDateTime(a.created_at)">
                  {{ faDate(a.created_at) }}
                </span>
              </div>
              <p
                v-if="a.note"
                class="mt-1.5 text-sm text-slate-600 whitespace-pre-line bg-slate-50 rounded-lg px-3 py-2 leading-7"
              >{{ a.note }}</p>
            </li>
          </ol>
        </section>
      </div>

      <LetterForm
        v-if="replying"
        :reply-to="letter"
        @close="replying = false"
        @saved="replying = false; emit('replied'); toast.success('پاسخ ارسال شد.')"
      />
    </template>
  </div>
</template>
