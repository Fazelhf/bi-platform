<script setup lang="ts">
/**
 * یک نامه، و هر چه بعد از ارسالش رخ داده.
 *
 * The letter itself is fixed — subject, body, who it went to. Everything
 * below it is the گردش: paraphs, referrals and notes in the order they
 * happened. That chain is why correspondence is kept in a system instead of a
 * chat: «چه کسی این را به چه کسی ارجاع داد و چه نوشت» has an answer here.
 */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { officeApi, type Letter, type Person } from "@/api/office";
import { apiError } from "@/components/crm/formError";
import { faDate } from "@/utils/adminFormat";
import { num } from "@/utils/format";
import LetterForm from "@/components/office/LetterForm.vue";
import PeoplePicker from "@/components/office/PeoplePicker.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";

const route = useRoute();
const router = useRouter();

const letter = ref<Letter | null>(null);
const people = ref<Person[]>([]);
const loading = ref(true);
const error = ref("");
const busy = ref(false);
const replying = ref(false);

/** The one open composer-ish box at a time: paraph note, referral, or note. */
const panel = ref<"" | "paraph" | "refer" | "note">("");
const noteText = ref("");
const referTo = ref<number[]>([]);

async function load() {
  loading.value = true;
  try {
    letter.value = await officeApi.letter(Number(route.params.id));
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

/**
 * Whether *I* have filed this away — not whether anyone has.
 *
 * Archiving is per-person by design, so asking `recipients.some(...)` would
 * label the button from a colleague's desk.
 */
const isArchived = computed(() => !!letter.value?.my_archived_at);

async function run(fn: () => Promise<unknown>) {
  busy.value = true;
  error.value = "";
  try {
    await fn();
    panel.value = "";
    noteText.value = "";
    referTo.value = [];
    await load();
  } catch (e) {
    error.value = apiError(e);
  } finally {
    busy.value = false;
  }
}

/** What «ثبت» does depends on which panel is open. */
function submitPanel() {
  const id = letter.value!.id;
  if (panel.value === "paraph") return run(() => officeApi.paraph(id, noteText.value));
  if (panel.value === "note") return run(() => officeApi.note(id, noteText.value));
  // A referral to three people is three referrals: each gets their own row in
  // the chain, so «به چه کسی ارجاع شد» stays answerable per person.
  return run(() =>
    Promise.all(referTo.value.map((to) => officeApi.refer(id, to, noteText.value))),
  );
}

async function openAttachment(attId: number, name: string) {
  const file = await officeApi.attachment(letter.value!.id, attId);
  // The bytes arrive as a data-URL; hand them to the browser as a download
  // rather than navigating, which would replace the page for a PDF.
  const a = document.createElement("a");
  a.href = file.content;
  a.download = name;
  a.click();
}

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
</script>

<template>
  <div class="space-y-4 max-w-4xl">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-28 rounded-card" />
      <Skeleton class="h-64 rounded-card" />
    </div>

    <p
      v-else-if="error && !letter"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3"
    >{{ error }}</p>

    <template v-else-if="letter">
      <!-- The letter -->
      <div class="bg-surface rounded-card shadow-soft overflow-hidden">
        <div class="px-4 sm:px-5 py-4 border-b border-slate-100">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="min-w-0">
              <h2 class="text-lg font-bold text-ink">{{ letter.subject }}</h2>
              <p class="text-xs text-slate-400 mt-1 ltr-nums">
                {{ letter.number }}
                <span v-if="letter.sent_at"> · {{ faDate(letter.sent_at) }}</span>
              </p>
              <p
                v-if="letter.in_reply_to_detail"
                class="text-xs text-slate-500 mt-1"
              >
                در پاسخ به
                <button
                  class="underline"
                  @click="router.push({ name: 'office-letter', params: { id: letter.in_reply_to_detail.id } })"
                >{{ letter.in_reply_to_detail.number }} — {{ letter.in_reply_to_detail.subject }}</button>
              </p>
            </div>
            <button
              class="text-sm text-slate-500 hover:text-ink px-2 py-2 shrink-0"
              @click="router.push({ name: 'office-letters' })"
            >← بازگشت</button>
          </div>

          <div class="flex flex-wrap items-center gap-3 mt-3">
            <span class="flex items-center gap-2">
              <UserAvatar :user="letter.sender_detail as any" :size="30" />
              <span class="text-sm text-ink">{{ letter.sender_detail.name }}</span>
            </span>
            <span class="text-xs text-slate-400">
              به {{ letter.recipients.filter(r => r.kind === "to").map(r => r.user_detail.name).join("، ") || "—" }}
            </span>
            <span
              v-if="letter.recipients.some(r => r.kind === 'cc')"
              class="text-xs text-slate-400"
            >
              رونوشت {{ letter.recipients.filter(r => r.kind === "cc").map(r => r.user_detail.name).join("، ") }}
            </span>
            <span class="text-xs text-slate-400 ltr-nums">
              {{ num(letter.read_count) }} از {{ num(letter.recipient_count) }} خوانده‌اند
            </span>
            <span
              v-for="t in letter.tags_detail" :key="t.id"
              class="text-[11px] rounded-full px-2 py-0.5 bg-slate-100 text-slate-500"
            >{{ t.name_fa }}</span>
          </div>
        </div>

        <div class="px-4 sm:px-5 py-5 text-sm text-ink whitespace-pre-line leading-7">
          {{ letter.body || "—" }}
        </div>

        <div
          v-if="letter.attachments.length"
          class="px-4 sm:px-5 py-3 border-t border-slate-100 flex flex-wrap gap-2"
        >
          <button
            v-for="a in letter.attachments" :key="a.id"
            class="flex items-center gap-2 bg-slate-100 hover:bg-slate-200 rounded-xl
                   px-3 py-2 text-xs text-slate-600 transition-colors"
            @click="openAttachment(a.id, a.name)"
          >
            📎 {{ a.name }}
            <span class="text-slate-400 ltr-nums">
              {{ Math.max(1, Math.round(a.size_bytes / 1024)) }}KB
            </span>
          </button>
        </div>
      </div>

      <!-- What to do with it -->
      <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap gap-2">
        <button
          class="bg-panel text-white rounded-xl px-4 py-2 text-sm"
          @click="replying = true"
        >پاسخ</button>
        <button
          class="bg-slate-100 hover:bg-slate-200 rounded-xl px-4 py-2 text-sm text-slate-600"
          @click="panel = panel === 'paraph' ? '' : 'paraph'"
        >پاراف</button>
        <button
          class="bg-slate-100 hover:bg-slate-200 rounded-xl px-4 py-2 text-sm text-slate-600"
          @click="panel = panel === 'refer' ? '' : 'refer'"
        >ارجاع</button>
        <button
          class="bg-slate-100 hover:bg-slate-200 rounded-xl px-4 py-2 text-sm text-slate-600"
          @click="panel = panel === 'note' ? '' : 'note'"
        >یادداشت</button>
        <span class="flex-1"></span>
        <button
          class="text-sm text-slate-500 hover:text-ink px-3 py-2"
          :disabled="busy"
          @click="run(() => officeApi.archive(letter!.id, isArchived))"
        >{{ isArchived ? "خروج از بایگانی" : "بایگانی" }}</button>
      </div>

      <div v-if="panel" class="bg-surface rounded-card shadow-soft p-4 space-y-3">
        <PeoplePicker
          v-if="panel === 'refer'"
          v-model="referTo" :people="people" placeholder="ارجاع به…"
        />
        <textarea
          v-model="noteText" :class="inp" rows="3"
          :placeholder="panel === 'paraph' ? 'یادداشت پاراف (اختیاری)…' : 'متن…'"
        ></textarea>
        <div class="flex gap-2">
          <button
            class="bg-panel text-white rounded-xl px-4 py-2 text-sm disabled:opacity-50"
            :disabled="busy || (panel === 'refer' && !referTo.length) || (panel === 'note' && !noteText.trim())"
            @click="submitPanel"
          >ثبت</button>
          <button class="text-sm text-slate-500 px-3 py-2" @click="panel = ''">انصراف</button>
        </div>
        <p v-if="error" class="text-red-600 text-xs">{{ error }}</p>
      </div>

      <!-- The chain -->
      <div class="bg-surface rounded-card shadow-soft overflow-hidden">
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          گردش نامه
        </h3>
        <p v-if="!letter.actions.length" class="px-4 py-6 text-sm text-slate-400 text-center">
          هنوز اقدامی روی این نامه ثبت نشده.
        </p>
        <div v-else class="divide-y divide-slate-100">
          <div
            v-for="a in letter.actions" :key="a.id"
            class="px-4 py-3 flex items-start gap-3"
          >
            <UserAvatar :user="a.actor_detail as any" :size="30" class="shrink-0 mt-0.5" />
            <div class="min-w-0 flex-1">
              <p class="text-sm text-ink">
                <span class="font-medium">{{ a.actor_detail.name }}</span>
                <span class="text-slate-500"> {{ a.kind_label }}</span>
                <span v-if="a.to_user_detail" class="text-slate-500">
                  به {{ a.to_user_detail.name }}
                </span>
              </p>
              <p v-if="a.note" class="text-sm text-slate-600 mt-1 whitespace-pre-line">
                {{ a.note }}
              </p>
            </div>
            <span class="text-xs text-slate-400 shrink-0 ltr-nums">
              {{ faDate(a.created_at) }}
            </span>
          </div>
        </div>
      </div>

      <LetterForm
        v-if="replying"
        :reply-to="letter"
        @close="replying = false"
        @saved="replying = false; load()"
      />
    </template>
  </div>
</template>
