<script setup lang="ts">
import { nextTick, ref } from "vue";

/**
 * One table cell that edits in place: click, change, Enter or leave to save,
 * Esc to cancel.
 *
 * The value on screen only changes once the server has said yes. A cell that
 * showed the new value while the save was still out — or after it failed —
 * would tell the user something was recorded that was not, which is exactly
 * how a list of 3,000 customers drifts from what is in the database.
 */
const props = defineProps<{
  value: string | number | null;
  /** What the cell shows when not editing; defaults to the value itself. */
  display?: string;
  options?: { id: string | number; name: string }[];
  disabled?: boolean;
  placeholder?: string;
  save: (value: any) => Promise<void>;
}>();

const editing = ref(false);
const draft = ref<any>(null);
const saving = ref(false);
const failed = ref("");
const input = ref<HTMLInputElement | HTMLSelectElement | null>(null);

async function start() {
  if (props.disabled || saving.value) return;
  draft.value = props.value ?? "";
  failed.value = "";
  editing.value = true;
  await nextTick();
  input.value?.focus();
}

function cancel() {
  editing.value = false;
}

async function commit() {
  if (!editing.value) return;
  const next = props.options ? (draft.value === "" ? null : draft.value) : String(draft.value ?? "").trim();
  if ((next ?? "") === (props.value ?? "")) {
    editing.value = false;
    return;
  }
  saving.value = true;
  try {
    await props.save(next);
    editing.value = false;
    failed.value = "";
  } catch (e: any) {
    const d = e?.response?.data;
    failed.value = d?.detail ?? (d && typeof d === "object" ? String(Object.values(d)[0]) : "") ?? "ذخیره نشد";
    editing.value = false; // back to the stored value; the red mark says why
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <span class="block min-w-[4rem]" @click.stop>
    <template v-if="editing">
      <select
        v-if="options"
        ref="input"
        v-model="draft"
        class="w-full bg-white border border-sky-300 rounded-lg px-2 py-1 text-xs outline-none"
        @change="commit"
        @blur="commit"
        @keydown.esc.prevent="cancel"
      >
        <option value="">—</option>
        <option v-for="o in options" :key="o.id" :value="o.id">{{ o.name }}</option>
      </select>
      <input
        v-else
        ref="input"
        v-model="draft"
        class="w-full bg-white border border-sky-300 rounded-lg px-2 py-1 text-xs outline-none"
        :placeholder="placeholder"
        @keydown.enter.prevent="commit"
        @keydown.esc.prevent="cancel"
        @blur="commit"
      />
    </template>
    <button
      v-else
      type="button"
      class="w-full text-right rounded px-1 -mx-1 py-0.5 transition"
      :class="[
        disabled ? 'cursor-default' : 'hover:bg-sky-50 hover:ring-1 hover:ring-sky-200',
        failed ? 'ring-1 ring-red-300 bg-red-50' : '',
        saving ? 'opacity-50' : '',
      ]"
      :title="failed || (disabled ? '' : 'برای ویرایش کلیک کنید')"
      @click="start"
    >
      <slot>{{ display ?? (value || "—") }}</slot>
    </button>
    <span v-if="failed" class="block text-[10px] text-red-600 leading-4">{{ failed }}</span>
  </span>
</template>
