<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useClickOutside } from "@/composables/useClickOutside";
import { matches, ordered, type PickerOption } from "@/components/picker";

/**
 * انتخاب با جستجو — a select you can type into.
 *
 * A native `<select>` is fine for five options and hostile at fifty. The
 * department has ten suppliers today and will have sixty; کالاها grows the
 * same way. Scrolling a list to find «نشاسته کاتیونی» is the slowest part of
 * entering a purchase, and it gets slower every month the system is used.
 *
 * Two modes:
 *
 * * **Pick** (default) — the value is an id chosen from the list.
 * * **`creatable`** — the value is free text. The field is an ordinary input
 *   that also suggests what has been typed before. کشور, برند, شرکت حمل and
 *   بندر are like this: they are not lookup tables, but they repeat, and
 *   retyping «شهید رجایی» for the fortieth time is how «شهید رجائی» ends up in
 *   the database as a second, separate port.
 *
 * The panel is teleported to <body> and positioned fixed, for the reason
 * ThemePicker documents: in the شیشه‌ای skin every card carries a
 * backdrop-filter, which makes it a stacking context that an absolutely
 * positioned child cannot escape at any z-index. It also has to clear
 * FormModal's own scroll container, which would otherwise clip it.
 */
const props = withDefaults(defineProps<{
  modelValue: string | number | null;
  options: PickerOption[];
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  clearable?: boolean;
  creatable?: boolean;
  loading?: boolean;
  /** Rendered under the field when nothing is selected yet. */
  hint?: string;
  invalid?: boolean;
}>(), {
  placeholder: "انتخاب کنید…",
  searchPlaceholder: "برای جستجو تایپ کنید…",
  emptyText: "چیزی پیدا نشد",
  disabled: false,
  clearable: true,
  creatable: false,
  loading: false,
  hint: "",
  invalid: false,
});

const emit = defineEmits<{
  (e: "update:modelValue", value: string | number | null): void;
}>();

const root = ref<HTMLElement | null>(null);
const panel = ref<HTMLElement | null>(null);
const searchBox = ref<HTMLInputElement | null>(null);
const textBox = ref<HTMLInputElement | null>(null);
const listBox = ref<HTMLElement | null>(null);

const open = ref(false);
const query = ref("");
const active = ref(0);
const pos = ref({ top: 0, left: 0, width: 240 });

const GAP = 4;
const MAX_PANEL_H = 320;

const selected = computed(
  () => props.options.find((o) => o.value === props.modelValue) ?? null,
);

/**
 * A search box over four currencies is furniture, not help — it costs a
 * click and a decision to reach a list the eye already read. It appears once
 * the list is long enough that scanning it stops being instant.
 */
const SEARCH_FROM = 8;
const showSearch = computed(() => !props.creatable && props.options.length >= SEARCH_FROM);

/** In creatable mode the box shows the value itself and filters by it, so
 *  there is no second search field to tab into. */
const term = computed(() => (props.creatable ? String(props.modelValue ?? "") : query.value));

const visible = computed(() => {
  const hits = props.options.filter((o) => matches(o, term.value));
  return ordered(hits, term.value);
});

/** Offer to keep what was typed when it is not already a known value. */
const canCreate = computed(() => {
  if (!props.creatable) return false;
  const typed = String(props.modelValue ?? "").trim();
  return !!typed && !props.options.some((o) => String(o.value) === typed);
});

function place() {
  const el = root.value;
  if (!el) return;
  const r = el.getBoundingClientRect();
  const below = window.innerHeight - r.bottom;
  const h = Math.min(panel.value?.offsetHeight ?? MAX_PANEL_H, MAX_PANEL_H);
  const top = below > h + GAP ? r.bottom + GAP : Math.max(GAP, r.top - h - GAP);
  pos.value = {
    top,
    left: Math.max(GAP, Math.min(r.left, window.innerWidth - r.width - GAP)),
    width: r.width,
  };
}

async function show() {
  if (props.disabled) return;
  open.value = true;
  active.value = Math.max(0, visible.value.findIndex((o) => o.value === props.modelValue));
  place();
  await nextTick();
  place();
  if (showSearch.value) searchBox.value?.focus();
  scrollActiveIntoView();
}

function close() {
  open.value = false;
  query.value = "";
}

function toggle() {
  open.value ? close() : show();
}

function choose(option: PickerOption) {
  if (option.disabled) return;
  emit("update:modelValue", option.value);
  close();
  if (props.creatable) textBox.value?.focus();
}

function clear() {
  emit("update:modelValue", props.creatable ? "" : null);
  close();
}

function onType(e: Event) {
  emit("update:modelValue", (e.target as HTMLInputElement).value);
  active.value = 0;
  if (!open.value) show();
  else place();
}

/** Keep the highlighted row on screen when arrowing through a long list. */
async function scrollActiveIntoView() {
  await nextTick();
  listBox.value
    ?.querySelector<HTMLElement>('[data-active="true"]')
    ?.scrollIntoView({ block: "nearest" });
}

function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") { close(); return; }
  if (e.key === "Tab") { close(); return; }

  if (!open.value) {
    if (["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) {
      e.preventDefault();
      show();
    }
    return;
  }

  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const last = visible.value.length - 1;
    if (last < 0) return;
    active.value = e.key === "ArrowDown"
      ? (active.value >= last ? 0 : active.value + 1)
      : (active.value <= 0 ? last : active.value - 1);
    scrollActiveIntoView();
  } else if (e.key === "Enter") {
    e.preventDefault();
    const option = visible.value[active.value];
    // In creatable mode, Enter on nothing matching keeps what was typed —
    // the field is free text and the list is only a memory of past answers.
    if (option) choose(option);
    else close();
  }
}

watch(query, () => { active.value = 0; place(); });

/**
 * Keep the panel glued to its field while the page moves under it.
 *
 * Two things have to be true, and the obvious one-liner («close on any
 * scroll», which is what ThemePicker does) gets both wrong here:
 *
 * * **Scrolling the option list must not close the option list.** A `scroll`
 *   listener on window with capture also receives scrolls that happened
 *   *inside* the panel, so reaching for the fifth supplier in a long list
 *   dismissed the list on the way to it.
 * * **Scrolling the form should reposition, not dismiss.** These fields live
 *   inside a modal whose body scrolls. Closing on that scroll throws away a
 *   half-finished choice for no reason.
 *
 * It still closes when the field itself has scrolled out of sight, because a
 * panel anchored to something off-screen is just floating.
 */
function onScroll(e: Event) {
  const target = e.target as Node | null;
  if (target && panel.value && (panel.value === target || panel.value.contains(target))) {
    return;
  }
  const el = root.value;
  if (!el) { close(); return; }
  const r = el.getBoundingClientRect();
  if (r.bottom < 0 || r.top > window.innerHeight) { close(); return; }
  place();
}

window.addEventListener("scroll", onScroll, true);
window.addEventListener("resize", close);
onBeforeUnmount(() => {
  window.removeEventListener("scroll", onScroll, true);
  window.removeEventListener("resize", close);
});

useClickOutside(root, close, panel);

const box =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300 text-right";
</script>

<template>
  <div ref="root" class="relative">
    <!-- Free-text mode: an ordinary input that happens to remember. -->
    <input
      v-if="creatable"
      ref="textBox"
      :value="modelValue ?? ''"
      :class="[box, invalid ? 'ring-2 ring-red-300' : '']"
      :placeholder="placeholder"
      :disabled="disabled"
      role="combobox"
      :aria-expanded="open"
      aria-autocomplete="list"
      @input="onType"
      @focus="show"
      @keydown="onKey"
    />

    <!-- Pick mode: a button that opens a searchable list. -->
    <button
      v-else
      type="button"
      :class="[box, 'flex items-center justify-between gap-2',
               invalid ? 'ring-2 ring-red-300' : '',
               disabled ? 'opacity-60 cursor-not-allowed' : '']"
      :disabled="disabled"
      role="combobox"
      :aria-expanded="open"
      @click="toggle"
      @keydown="onKey"
    >
      <span :class="selected ? 'text-ink truncate' : 'text-slate-400 truncate'">
        {{ selected?.label ?? placeholder }}
      </span>
      <span class="flex items-center gap-1 shrink-0">
        <span
          v-if="selected?.badge"
          class="text-[11px] text-slate-400"
        >{{ selected.badge }}</span>
        <svg
          class="w-4 h-4 text-slate-400" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
        ><path d="m6 9 6 6 6-6" /></svg>
      </span>
    </button>

    <p v-if="hint && !selected && !creatable" class="text-xs text-slate-400 mt-1">
      {{ hint }}
    </p>

    <Teleport to="body">
      <div
        v-if="open"
        ref="panel"
        class="fixed bg-surface rounded-2xl shadow-pop border border-slate-100 z-[210] overflow-hidden animate-pop"
        :style="{
          top: pos.top + 'px',
          left: pos.left + 'px',
          width: Math.max(pos.width, 220) + 'px',
        }"
        dir="rtl"
      >
        <div v-if="showSearch" class="p-2 border-b border-slate-100">
          <input
            ref="searchBox"
            v-model="query"
            class="w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300"
            :placeholder="searchPlaceholder"
            @keydown="onKey"
          />
        </div>

        <div ref="listBox" class="max-h-64 overflow-y-auto py-1" role="listbox">
          <p v-if="loading" class="px-3 py-4 text-xs text-slate-400 text-center">
            در حال بارگذاری…
          </p>

          <template v-else-if="visible.length">
            <button
              v-for="(o, i) in visible" :key="o.value"
              type="button"
              role="option"
              :data-active="i === active"
              :aria-selected="o.value === modelValue"
              class="w-full text-right px-3 py-2 flex items-start gap-2 transition-colors"
              :class="[
                o.disabled ? 'opacity-40 cursor-not-allowed' : 'hover:bg-slate-100',
                i === active ? 'bg-slate-100' : '',
                o.value === modelValue ? 'text-accent-600 font-medium' : 'text-ink',
              ]"
              @mouseenter="active = i"
              @click="choose(o)"
            >
              <span class="min-w-0 flex-1">
                <span class="block text-sm truncate">{{ o.label }}</span>
                <span
                  v-if="o.hint"
                  class="block text-[11px] text-slate-400 truncate"
                >{{ o.hint }}</span>
              </span>
              <span
                v-if="o.badge"
                class="text-[11px] text-slate-400 shrink-0 mt-0.5 ltr-nums"
              >{{ o.badge }}</span>
            </button>
          </template>

          <p v-else class="px-3 py-4 text-xs text-slate-400 text-center">
            {{ canCreate ? "مقدار جدید — همین که نوشتید ثبت می‌شود." : emptyText }}
          </p>
        </div>

        <button
          v-if="clearable && modelValue !== null && modelValue !== ''"
          type="button"
          class="w-full text-right px-3 py-2 text-xs text-slate-400 hover:text-red-500 hover:bg-slate-50 border-t border-slate-100"
          @click="clear"
        >پاک کردن انتخاب</button>
      </div>
    </Teleport>
  </div>
</template>
