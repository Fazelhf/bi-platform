<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { crmApi, type CrmCustomer } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { useClickOutside } from "@/composables/useClickOutside";
import { MODAL_LAYER } from "@/components/picker";

/**
 * انتخاب مشتری — one implementation, instead of the three copies that used to
 * live in the deal, activity and task forms.
 *
 * Three things the copies did not do, each of which was a reason a rep gave
 * up on the form:
 *
 * * **Recents before typing.** The customer you are logging a call against is
 *   almost always one you touched this week. Opening the field now offers
 *   those first, so the common case is one click and no typing at all. The
 *   list comes from the caller's own recent activities — no new endpoint, and
 *   it is genuinely theirs rather than the company's.
 * * **Create from here.** A call to a brand-new lead used to mean abandoning
 *   the half-filled activity, going to مشتری‌ها, adding the customer, and
 *   starting over. Now the search offers to create what was typed, and the
 *   parent form opens a nested quick-add.
 * * **Keyboard.** Arrow keys and Enter, so the field can be filled without
 *   the hand leaving the keyboard.
 *
 * The panel is teleported and positioned fixed for the reason PickerField
 * documents: the شیشه‌ای skin's backdrop-filter makes every card a stacking
 * context that an absolutely positioned child cannot escape, and FormModal's
 * body scrolls and would clip it.
 */
const props = withDefaults(defineProps<{
  modelValue: number | "";
  /** Shown while a customer is selected; kept in sync by the parent. */
  label?: string;
  placeholder?: string;
  /** Locked — the form was opened from this customer's own page. */
  locked?: boolean;
  invalid?: boolean;
  /** Offer «ثبت مشتری جدید» when nothing matches. */
  creatable?: boolean;
}>(), {
  label: "",
  placeholder: "نام، موبایل یا کد مشتری…",
  locked: false,
  invalid: false,
  creatable: true,
});

const emit = defineEmits<{
  (e: "update:modelValue", v: number | ""): void;
  (e: "update:label", v: string): void;
  /** The typed text was not found and the user asked to create it. */
  (e: "create", name: string): void;
}>();

const crm = useCrmStore();

const root = ref<HTMLElement | null>(null);
const panel = ref<HTMLElement | null>(null);
const input = ref<HTMLInputElement | null>(null);

const open = ref(false);
const query = ref("");
const results = ref<CrmCustomer[]>([]);
const recents = ref<CrmCustomer[]>([]);
const searching = ref(false);
const active = ref(0);
const pos = ref({ top: 0, left: 0, width: 260 });

const GAP = 4;
const PANEL_H = 300;
/** How many search hits are worth showing before it stops being a shortlist. */
const LIMIT = 8;

/** Clears its own modal, stays under the quick-add it can open. */
const layer = inject(MODAL_LAYER, null);
const panelZ = computed(() => 210 + (layer?.value ?? 0) * 150);

/** Before anything is typed the list is the caller's own recent contacts. */
const rows = computed(() => (query.value.trim() ? results.value : recents.value));
const showCreate = computed(
  () => props.creatable && !!query.value.trim() && !searching.value,
);

function place() {
  const el = root.value;
  if (!el) return;
  const r = el.getBoundingClientRect();
  const below = window.innerHeight - r.bottom;
  const h = Math.min(panel.value?.offsetHeight ?? PANEL_H, PANEL_H);
  pos.value = {
    top: below > h + GAP ? r.bottom + GAP : Math.max(GAP, r.top - h - GAP),
    left: Math.max(GAP, Math.min(r.left, window.innerWidth - r.width - GAP)),
    width: r.width,
  };
}

async function show() {
  open.value = true;
  active.value = 0;
  place();
  await nextTick();
  place();
}

function close() {
  open.value = false;
}

/**
 * Recent contacts, derived from the caller's own activity log.
 *
 * Customers are ordered by name, so asking the customer list for "recent"
 * would not answer the question. Activities are ordered by time and already
 * carry the customer's name, so folding the last page of them down to unique
 * customers costs one request and no backend change.
 */
async function loadRecents() {
  const mine = crm.me?.employee;
  if (!mine) return;
  try {
    const res = await crmApi.activities({ owner: mine, page_size: 20 });
    const seen = new Set<number>();
    const out: any[] = [];
    for (const a of res.results) {
      if (!a.customer || seen.has(a.customer)) continue;
      seen.add(a.customer);
      out.push({ id: a.customer, name_fa: a.customer_name, province_name: "" });
      if (out.length >= 6) break;
    }
    recents.value = out;
  } catch {
    // Suggestions are a convenience; the search box behind them still works.
    recents.value = [];
  }
}

let timer: number | undefined;
watch(query, (q) => {
  window.clearTimeout(timer);
  active.value = 0;
  if (!q.trim()) {
    results.value = [];
    searching.value = false;
    place();
    return;
  }
  searching.value = true;
  timer = window.setTimeout(async () => {
    try {
      const res = await crmApi.customers({ search: q, page_size: LIMIT });
      // The API's paginator has no `page_size_query_param`, so it returns its
      // own page size no matter what is asked for — a hundred rows for a
      // three-letter search. Trimming here keeps the panel scannable; the
      // request size is a separate, platform-wide fix.
      results.value = res.results.slice(0, LIMIT);
    } finally {
      searching.value = false;
      place();
    }
  }, 250);
});

function pick(c: { id: number; name_fa: string }) {
  emit("update:modelValue", c.id);
  emit("update:label", c.name_fa);
  query.value = "";
  results.value = [];
  close();
}

function clear() {
  emit("update:modelValue", "");
  emit("update:label", "");
  query.value = "";
  nextTick(() => input.value?.focus());
}

function create() {
  emit("create", query.value.trim());
  close();
}

function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") { close(); return; }
  if (e.key === "Tab") { close(); return; }
  if (!open.value && ["ArrowDown", "Enter"].includes(e.key)) { show(); return; }

  const last = rows.value.length - 1 + (showCreate.value ? 1 : 0);
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (last < 0) return;
    active.value = e.key === "ArrowDown"
      ? (active.value >= last ? 0 : active.value + 1)
      : (active.value <= 0 ? last : active.value - 1);
  } else if (e.key === "Enter") {
    e.preventDefault();
    const row = rows.value[active.value];
    if (row) pick(row);
    else if (showCreate.value) create();
  }
}

/** Same rule as PickerField: scrolling the list must not dismiss the list. */
function onScroll(e: Event) {
  const t = e.target as Node | null;
  if (t && panel.value && (panel.value === t || panel.value.contains(t))) return;
  const el = root.value;
  if (!el) { close(); return; }
  const r = el.getBoundingClientRect();
  if (r.bottom < 0 || r.top > window.innerHeight) { close(); return; }
  place();
}

onMounted(() => {
  loadRecents();
  window.addEventListener("scroll", onScroll, true);
  window.addEventListener("resize", close);
});
onBeforeUnmount(() => {
  window.removeEventListener("scroll", onScroll, true);
  window.removeEventListener("resize", close);
  window.clearTimeout(timer);
});

useClickOutside(root, close, panel);

/** Called by the parent after a nested quick-add saved a new customer. */
function select(id: number, name: string) {
  pick({ id, name_fa: name });
}
defineExpose({ select, focus: () => input.value?.focus() });

const box =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
</script>

<template>
  <div ref="root" class="relative">
    <!-- Chosen: a chip, not a box you can accidentally retype into. -->
    <div v-if="modelValue" class="flex items-center gap-2">
      <span class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink flex-1 truncate">
        {{ label || "مشتری انتخاب‌شده" }}
      </span>
      <button
        v-if="!locked"
        type="button"
        class="text-xs text-slate-400 hover:text-ink px-2 shrink-0"
        @click="clear"
      >تغییر</button>
    </div>

    <input
      v-else
      ref="input"
      v-model="query"
      :class="[box, invalid ? 'ring-2 ring-red-300' : '']"
      :placeholder="placeholder"
      role="combobox"
      :aria-expanded="open"
      aria-autocomplete="list"
      @focus="show"
      @keydown="onKey"
    />

    <Teleport to="body">
      <div
        v-if="open && !modelValue"
        ref="panel"
        class="fixed bg-surface rounded-2xl shadow-pop border border-slate-100
               overflow-hidden animate-pop"
        :style="{
          top: pos.top + 'px',
          left: pos.left + 'px',
          width: Math.max(pos.width, 240) + 'px',
          zIndex: panelZ,
        }"
        dir="rtl"
      >
        <p
          v-if="!query.trim() && recents.length"
          class="px-3 pt-2 pb-1 text-[11px] text-slate-400"
        >اخیراً با آن‌ها کار کرده‌اید</p>

        <div class="max-h-60 overflow-y-auto py-1" role="listbox">
          <button
            v-for="(c, i) in rows" :key="c.id"
            type="button" role="option"
            class="w-full text-right px-3 py-2 text-sm transition-colors flex items-baseline gap-2"
            :class="i === active ? 'bg-slate-100 text-ink' : 'text-ink hover:bg-slate-50'"
            @mouseenter="active = i"
            @click="pick(c)"
          >
            <span class="flex-1 truncate">{{ c.name_fa }}</span>
            <span
              v-if="c.province_name || c.mobile"
              class="text-[11px] text-slate-400 shrink-0" dir="ltr"
            >{{ c.mobile || c.province_name }}</span>
          </button>

          <p v-if="searching" class="px-3 py-3 text-xs text-slate-400 text-center">
            در حال جستجو…
          </p>
          <p
            v-else-if="!rows.length && !query.trim()"
            class="px-3 py-3 text-xs text-slate-400 text-center"
          >نام مشتری را تایپ کنید</p>
        </div>

        <!-- The escape hatch: a new lead should not send anyone to another
             page in the middle of a form. -->
        <button
          v-if="showCreate"
          type="button"
          class="w-full text-right px-3 py-2.5 text-sm border-t border-slate-100 transition-colors"
          :class="active === rows.length ? 'bg-slate-100 text-ink' : 'text-slate-600 hover:bg-slate-50'"
          @mouseenter="active = rows.length"
          @click="create"
        >
          <span class="text-slate-400">+</span>
          ثبت «{{ query.trim() }}» به عنوان مشتری جدید
        </button>
      </div>
    </Teleport>
  </div>
</template>
