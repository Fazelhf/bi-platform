<script setup lang="ts">
/**
 * Pick several people — the «به» and «رونوشت» fields of a letter.
 *
 * PickerField next door is single-select and stays that way; a letter goes to
 * a list, and forcing that through one-at-a-time selection is the difference
 * between addressing a memo and filling in a form eight times.
 *
 * Selected people are chips above the input, each removable, so the answer to
 * «به چه کسانی می‌رود» is readable without opening anything.
 */
import { computed, ref } from "vue";
import type { Person } from "@/api/office";
import { normalise } from "@/components/picker";
import UserAvatar from "@/components/UserAvatar.vue";

const props = withDefaults(defineProps<{
  modelValue: number[];
  people: Person[];
  placeholder?: string;
  /** Ids already chosen in the sibling field, greyed out here. */
  taken?: number[];
}>(), { placeholder: "جستجوی نام…", taken: () => [] });

const emit = defineEmits<{ (e: "update:modelValue", value: number[]): void }>();

const query = ref("");
const open = ref(false);

const byId = computed(() => new Map(props.people.map((p) => [p.id, p])));
const chosen = computed(() =>
  props.modelValue.map((id) => byId.value.get(id)).filter(Boolean) as Person[],
);

const matches = computed(() => {
  // `normalise` is the picker module's own folding — ی/ي, ک/ك, Persian and
  // Arabic digits, ZWNJ. Re-deriving it here is how «هانيه» stops matching
  // «هانیه» in one field and keeps matching in the next.
  const q = normalise(query.value.trim());
  return props.people
    .filter((p) => !props.modelValue.includes(p.id))
    .filter((p) => !q
      || normalise(p.name).includes(q)
      || normalise(p.job_title_fa).includes(q))
    .slice(0, 40);
});

function add(p: Person) {
  if (props.modelValue.includes(p.id)) return;
  emit("update:modelValue", [...props.modelValue, p.id]);
  query.value = "";
}

function remove(id: number) {
  emit("update:modelValue", props.modelValue.filter((x) => x !== id));
}

/** Backspace on an empty box removes the last chip — the mail-client habit. */
function onBackspace() {
  if (!query.value && props.modelValue.length) {
    remove(props.modelValue[props.modelValue.length - 1]);
  }
}
</script>

<template>
  <div class="relative">
    <div
      class="bg-slate-100 rounded-xl px-2 py-1.5 flex flex-wrap items-center gap-1.5
             focus-within:ring-2 focus-within:ring-slate-300"
    >
      <span
        v-for="p in chosen" :key="p.id"
        class="inline-flex items-center gap-1.5 bg-surface rounded-lg pl-1 pr-2 py-1 text-xs"
        :class="taken.includes(p.id) ? 'opacity-50' : ''"
      >
        <UserAvatar :user="p as any" :size="18" />
        <span class="text-ink">{{ p.name }}</span>
        <button
          class="text-slate-400 hover:text-red-500 leading-none"
          :aria-label="`حذف ${p.name}`"
          @click="remove(p.id)"
        >×</button>
      </span>

      <input
        v-model="query"
        class="flex-1 min-w-[7rem] bg-transparent px-1 py-1 text-sm text-ink outline-none"
        :placeholder="chosen.length ? '' : placeholder"
        @focus="open = true"
        @keydown.backspace="onBackspace"
        @keydown.enter.prevent="matches[0] && add(matches[0])"
        @keydown.esc="open = false"
      />
    </div>

    <div
      v-if="open && matches.length"
      class="absolute z-30 mt-1 w-full max-h-60 overflow-y-auto bg-surface rounded-xl
             shadow-pop border border-slate-100 p-1"
    >
      <button
        v-for="p in matches" :key="p.id"
        class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-right hover:bg-slate-100"
        @click="add(p)"
      >
        <UserAvatar :user="p as any" :size="24" />
        <span class="min-w-0 flex-1">
          <span class="block text-sm text-ink truncate">{{ p.name }}</span>
          <span v-if="p.job_title_fa" class="block text-[11px] text-slate-400 truncate">
            {{ p.job_title_fa }}
          </span>
        </span>
      </button>
    </div>

    <!-- Closing on blur would fire before the option's click lands. -->
    <div v-if="open" class="fixed inset-0 z-20" @click="open = false"></div>
  </div>
</template>
