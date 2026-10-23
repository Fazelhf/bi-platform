<script setup lang="ts">
/**
 * نوشتن نامه — compose, or edit a draft.
 *
 * Two buttons, deliberately. «ذخیره پیش‌نویس» keeps it private and unnumbered;
 * «ارسال» posts it and closes it to further editing. A single Save that
 * silently decided which one you meant is how half-written letters get sent.
 */
import { computed, onMounted, ref } from "vue";
import { officeApi, type Letter, type LetterTag, type Person } from "@/api/office";
import { apiError } from "@/components/crm/formError";
import FormModal from "@/components/crm/FormModal.vue";
import PeoplePicker from "@/components/office/PeoplePicker.vue";
import NavIcon from "@/components/NavIcon.vue";

const props = defineProps<{
  /** Editing an existing draft, or replying to a letter. */
  draft?: Letter | null;
  replyTo?: Letter | null;
}>();

const emit = defineEmits<{ (e: "close"): void; (e: "saved", sent: boolean): void }>();

const people = ref<Person[]>([]);
const tags = ref<LetterTag[]>([]);
const loading = ref(true);
const saving = ref(false);
const error = ref("");

const form = ref({
  subject: "",
  body: "",
  to: [] as number[],
  cc: [] as number[],
  tags: [] as number[],
});

const files = ref<{ name: string; mime: string; content: string; size: number }[]>([]);
const MAX_BYTES = 5 * 1024 * 1024;

const isEdit = computed(() => !!props.draft);

onMounted(async () => {
  try {
    const data = await officeApi.people();
    people.value = data.people;
    tags.value = data.tags;

    if (props.draft) {
      form.value = {
        subject: props.draft.subject,
        body: props.draft.body,
        to: props.draft.recipients.filter((r) => r.kind === "to").map((r) => r.user),
        cc: props.draft.recipients.filter((r) => r.kind === "cc").map((r) => r.user),
        tags: props.draft.tags_detail.map((t) => t.id),
      };
    } else if (props.replyTo) {
      // Reply goes back to whoever wrote it, with the subject carried over so
      // the thread reads as a thread in a list sorted by date.
      form.value.subject = props.replyTo.subject.startsWith("پاسخ:")
        ? props.replyTo.subject
        : `پاسخ: ${props.replyTo.subject}`;
      form.value.to = [props.replyTo.sender];
    }
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
});

function pickFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  error.value = "";
  for (const file of Array.from(input.files ?? [])) {
    if (file.size > MAX_BYTES) {
      error.value = `حجم «${file.name}» بیش از ۵ مگابایت است.`;
      continue;
    }
    const reader = new FileReader();
    reader.onload = () => {
      files.value.push({
        name: file.name,
        mime: file.type,
        content: String(reader.result),
        size: file.size,
      });
    };
    reader.readAsDataURL(file);
  }
  input.value = "";
}

async function save(send: boolean) {
  if (!form.value.subject.trim()) {
    error.value = "موضوع نامه را بنویسید.";
    return;
  }
  if (send && !form.value.to.length && !form.value.cc.length) {
    error.value = "برای ارسال، دست‌کم یک گیرنده لازم است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const payload = {
      ...form.value,
      send,
      in_reply_to: props.replyTo?.id ?? props.draft?.in_reply_to ?? null,
      attachments: files.value.map(({ name, mime, content }) => ({ name, mime, content })),
    };
    if (isEdit.value) await officeApi.update(props.draft!.id, payload);
    else await officeApi.create(payload);
    emit("saved", send);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

/** Files dropped on the attachment zone go through the same checks. */
const dragging = ref(false);
function onDrop(event: DragEvent) {
  dragging.value = false;
  const list = event.dataTransfer?.files;
  if (list?.length) pickFiles({ target: { files: list, value: "" } } as unknown as Event);
}

function kb(bytes: number): string {
  return bytes > 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} مگابایت`
    : `${Math.max(1, Math.round(bytes / 1024))} کیلوبایت`;
}
</script>

<template>
  <FormModal
    :title="isEdit ? 'ویرایش پیش‌نویس' : replyTo ? 'پاسخ نامه' : 'نامه جدید'"
    :subtitle="replyTo ? `در پاسخ به ${replyTo.number} — ${replyTo.subject}` : ''"
    :saving="saving"
    :error="error"
    wide
    save-label="ارسال"
    @close="emit('close')"
    @save="save(true)"
  >
    <div v-if="loading" class="text-sm text-slate-400 py-6 text-center">
      در حال بارگذاری…
    </div>

    <div v-else class="space-y-4">
      <div>
        <label class="office-label">موضوع</label>
        <input v-model="form.subject" class="office-input" placeholder="موضوع نامه" />
      </div>

      <div>
        <label class="office-label">به</label>
        <PeoplePicker v-model="form.to" :people="people" :taken="form.cc" />
      </div>

      <div>
        <label class="office-label">رونوشت</label>
        <PeoplePicker
          v-model="form.cc" :people="people" :taken="form.to"
          placeholder="اختیاری…"
        />
      </div>

      <div>
        <label class="office-label">متن</label>
        <textarea v-model="form.body" class="office-input" rows="10" placeholder="متن نامه…"></textarea>
      </div>

      <div v-if="tags.length">
        <label class="office-label">برچسب‌ها</label>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="t in tags" :key="t.id"
            type="button"
            class="text-xs rounded-full px-3 h-7 border transition-colors"
            :class="form.tags.includes(t.id)
              ? 'bg-panel text-white border-transparent'
              : 'border-slate-200 text-slate-600 hover:bg-slate-50'"
            @click="form.tags.includes(t.id)
              ? form.tags = form.tags.filter((x) => x !== t.id)
              : form.tags.push(t.id)"
          >{{ t.name_fa }}</button>
        </div>
      </div>

      <div>
        <label class="office-label">پیوست‌ها</label>
        <label
          class="flex flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed
                 px-4 py-4 text-center cursor-pointer transition-colors"
          :class="dragging ? 'border-[var(--sec-solid)] bg-[var(--sec-soft)]' : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'"
          @dragover.prevent="dragging = true"
          @dragleave.prevent="dragging = false"
          @drop.prevent="onDrop"
        >
          <NavIcon name="upload" :size="20" class="text-slate-400" />
          <span class="text-sm text-slate-600">فایل را اینجا رها کنید یا <span class="underline">انتخاب کنید</span></span>
          <span class="text-[11px] text-slate-400">حداکثر ۵ مگابایت برای هر فایل</span>
          <input type="file" multiple class="hidden" @change="pickFiles" />
        </label>

        <ul v-if="files.length" class="mt-2 space-y-1.5">
          <li
            v-for="(f, i) in files" :key="i"
            class="flex items-center gap-2.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
          >
            <NavIcon name="file" :size="16" class="text-slate-400 shrink-0" />
            <span class="flex-1 text-ink truncate">{{ f.name }}</span>
            <span class="text-slate-400 ltr-nums shrink-0">{{ kb(f.size) }}</span>
            <button
              class="office-icon-btn !w-6 !h-6 shrink-0"
              :aria-label="`حذف ${f.name}`"
              @click="files.splice(i, 1)"
            ><NavIcon name="close" :size="13" /></button>
          </li>
        </ul>
      </div>
    </div>

    <template #actions>
      <button
        class="office-btn-ghost"
        :disabled="saving"
        @click="save(false)"
      >ذخیره پیش‌نویس</button>
    </template>
  </FormModal>
</template>
