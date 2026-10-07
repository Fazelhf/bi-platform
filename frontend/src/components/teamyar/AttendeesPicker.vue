<script setup lang="ts">
/**
 * حاضرین — names as chips, picked from our staff (منابع انسانی), Teamyar's
 * team and anyone written into an earlier meeting, or typed freely for a
 * guest who is in none of them. Saved as the same «، »-separated text the
 * field always held, so older meetings read back unchanged.
 */
import { computed, onMounted, ref } from "vue";
import { teamyarApi, type Person } from "@/api/teamyar";

const props = defineProps<{ modelValue: string }>();
const emit = defineEmits<{ (e: "update:modelValue", v: string): void }>();

const GROUPS: Record<Person["group"], string> = {
  ours: "کاغذ حساس نمابر",
  teamyar: "تیمیار",
  past: "از جلسات قبل",
};

/** Cached for the page's lifetime: the list barely changes between two dialogs. */
let cache: Promise<Person[]> | null = null;
const people = ref<Person[]>([]);
onMounted(async () => {
  cache ??= teamyarApi.people().catch(() => { cache = null; return []; });
  people.value = await cache;
});

const fold = (s: string) =>
  s.replace(/[يى]/g, "ی").replace(/ك/g, "ک").replace(/[‌\s]+/g, "").replace(/^(آقای|خانم|جناب)/, "");

const names = computed(() =>
  props.modelValue.split(/[،,;؛\n]+/).map((n) => n.trim()).filter(Boolean),
);
function set(list: string[]) {
  emit("update:modelValue", list.join("، "));
}
function add(name: string) {
  const n = name.trim();
  if (n && !names.value.some((x) => fold(x) === fold(n))) set([...names.value, n]);
  query.value = "";
  active.value = 0;
}
function remove(i: number) {
  set(names.value.filter((_, j) => j !== i));
}

const query = ref("");
const focused = ref(false);
const active = ref(0);
const suggestions = computed(() => {
  const q = fold(query.value);
  const taken = new Set(names.value.map(fold));
  return people.value
    .filter((p) => !taken.has(fold(p.name)) && (!q || fold(p.name).includes(q) || fold(p.note).includes(q)))
    .slice(0, 30);
});
const grouped = computed(() =>
  (Object.keys(GROUPS) as Person["group"][])
    .map((g) => ({ g, label: GROUPS[g], items: suggestions.value.filter((p) => p.group === g) }))
    .filter((x) => x.items.length),
);
const flat = computed(() => grouped.value.flatMap((x) => x.items));

function onKey(e: KeyboardEvent) {
  if (e.key === "ArrowDown") { active.value = Math.min(active.value + 1, flat.value.length - 1); e.preventDefault(); }
  else if (e.key === "ArrowUp") { active.value = Math.max(active.value - 1, 0); e.preventDefault(); }
  else if (e.key === "Enter" || e.key === "،" || e.key === ",") {
    e.preventDefault();
    const pick = query.value.trim() && flat.value[active.value] && fold(flat.value[active.value].name).includes(fold(query.value))
      ? flat.value[active.value].name : query.value;
    if (pick.trim()) add(pick);
  } else if (e.key === "Backspace" && !query.value && names.value.length) {
    remove(names.value.length - 1);
  } else if (e.key === "Escape") {
    focused.value = false;
  }
}
function blur() {
  // Let a click on a suggestion land first.
  setTimeout(() => { focused.value = false; if (query.value.trim()) add(query.value); }, 150);
}
function groupOf(name: string) {
  return people.value.find((p) => fold(p.name) === fold(name))?.group;
}
</script>

<template>
  <div class="relative">
    <div
      class="w-full bg-slate-100 rounded-xl px-2 py-1.5 flex flex-wrap gap-1.5 items-center min-h-[40px]
             focus-within:ring-2 focus-within:ring-slate-300"
    >
      <span
        v-for="(n, i) in names" :key="n + i"
        class="inline-flex items-center gap-1 rounded-lg pr-2 pl-1 py-0.5 text-sm"
        :class="groupOf(n) === 'teamyar' ? 'bg-amber-500/15 text-amber-700' : 'bg-surface text-ink shadow-sm'"
      >
        {{ n }}
        <button type="button" class="text-slate-400 hover:text-red-500 px-0.5" :title="`حذف ${n}`" @click="remove(i)">×</button>
      </span>
      <input
        v-model="query"
        class="flex-1 min-w-[8rem] bg-transparent outline-none text-sm text-ink py-1"
        :placeholder="names.length ? 'نفر بعدی…' : 'نام را بنویسید یا از فهرست انتخاب کنید'"
        @focus="focused = true" @blur="blur" @keydown="onKey" @input="active = 0; focused = true"
      />
    </div>
    <div
      v-if="focused && (grouped.length || query.trim())"
      class="absolute z-30 inset-x-0 mt-1 bg-surface rounded-xl shadow-lg border border-slate-100 max-h-64 overflow-y-auto py-1"
    >
      <template v-for="grp in grouped" :key="grp.g">
        <p class="px-3 pt-2 pb-1 text-[11px] font-bold text-slate-400">{{ grp.label }}</p>
        <button
          v-for="p in grp.items" :key="p.name" type="button"
          class="w-full text-right px-3 py-1.5 text-sm flex items-baseline gap-2"
          :class="flat[active] === p ? 'bg-slate-100' : 'hover:bg-slate-50'"
          @mousedown.prevent="add(p.name)"
        >
          <span class="text-ink">{{ p.name }}</span>
          <span v-if="p.note" class="text-[11px] text-slate-400 truncate">{{ p.note }}</span>
        </button>
      </template>
      <button
        v-if="query.trim() && !flat.some((p) => fold(p.name) === fold(query))" type="button"
        class="w-full text-right px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-50 border-t border-slate-100"
        @mousedown.prevent="add(query)"
      >+ افزودن «{{ query.trim() }}»</button>
    </div>
  </div>
</template>
