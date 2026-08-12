<script setup lang="ts">
import { ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import { foreignApi, type ForeignOrder } from "@/api/commercialForeign";

/**
 * ثبت اقدام.
 *
 * Two different things share this form on purpose: recording progress, and
 * recording that there is none. The second is «علت توقف», and it is the more
 * valuable of the two — a file that is stuck for a known reason is being
 * managed, while one that is stuck for an unknown reason is being forgotten.
 * Either way the file stops counting as راکد, because someone looked at it.
 */
const props = defineProps<{ order: ForeignOrder }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
const lbl = "text-xs text-slate-500 mb-1 block";

// The reasons that come up most, offered as a starting point. The field stays
// free text: «سایر» tells a later reader nothing, and the whole value of علت
// توقف is that it names the actual obstacle.
const BLOCKED = [
  "در انتظار تخصیص ارز",
  "در انتظار پاسخ بانک",
  "در انتظار مجوز",
  "در انتظار فروشنده",
  "مشکل اسناد",
  "مشکل مالی",
].map((r) => ({ value: r, label: r }));

const saving = ref(false);
const error = ref("");
const isBlocked = ref(false);

const form = ref({
  at: new Date().toISOString().slice(0, 10),
  title: "",
  blocked_reason: "",
  note: "",
});

async function save() {
  if (!form.value.title.trim()) {
    error.value = "شرح اقدام الزامی است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await foreignApi.addEvent(props.order.id, {
      ...form.value,
      blocked_reason: isBlocked.value ? form.value.blocked_reason : "",
    });
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <FormModal
    title="ثبت اقدام"
    :subtitle="`${order.file_no} · ${order.pi_no}`"
    :saving="saving"
    :error="error"
    save-label="ثبت"
    @close="emit('close')"
    @save="save"
  >
    <div class="grid sm:grid-cols-3 gap-3">
      <div>
        <label :class="lbl">تاریخ</label>
        <input v-model="form.at" :class="inp" type="date" dir="ltr" />
      </div>
      <div class="sm:col-span-2">
        <label :class="lbl">شرح اقدام *</label>
        <input
          v-model="form.title" :class="inp"
          placeholder="مثلاً پیگیری تلفنی با بانک کارآفرین"
        />
      </div>
    </div>

    <label class="flex items-center gap-2 text-sm text-slate-600">
      <input v-model="isBlocked" type="checkbox" class="rounded" />
      این پرونده متوقف است
    </label>

    <div v-if="isBlocked">
      <label :class="lbl">علت توقف</label>
      <PickerField
        v-model="form.blocked_reason" :options="BLOCKED" creatable
        placeholder="انتخاب کنید یا بنویسید…"
      />
    </div>

    <div>
      <label :class="lbl">توضیحات</label>
      <textarea v-model="form.note" :class="inp" rows="3" />
    </div>

    <p class="text-xs text-slate-400">
      هر اقدامی که ثبت شود، شمارش «روز بدون اقدام» این پرونده را از نو شروع می‌کند.
    </p>
  </FormModal>
</template>
