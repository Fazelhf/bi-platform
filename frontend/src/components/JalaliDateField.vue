<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useClickOutside } from "@/composables/useClickOutside";
import { MODAL_LAYER } from "@/components/picker";
import {
  MONTH_NAMES, WEEKDAY_NAMES, addMonths, faDigits, firstWeekdayColumn,
  isoToJalali, jalaliLabel, jalaliToIso, monthLength, todayIso,
  type JalaliDate,
} from "@/utils/jalali";

/**
 * انتخاب تاریخ شمسی.
 *
 * `<input type="date">` renders the browser's own calendar, which is
 * Gregorian on every platform the company runs. A سامانه whose every label,
 * report and column header is in Jalali and whose date boxes open on
 * «August 2025» is asking each user to do the conversion in their head, once
 * per entry, and «۱۵ مرداد» becomes whatever they guessed.
 *
 * So the picker is Jalali and the value stays Gregorian ISO — the exact
 * string the native input produced, so nothing downstream changes. The
 * conversion lives in `utils/jalali`, on top of the browser's own Persian
 * calendar rather than a hand-rolled leap-year cycle.
 *
 * The panel is teleported and layer-aware for the reason PickerField
 * documents: the شیشه‌ای skin's backdrop-filter traps absolutely positioned
 * children, and a modal body would clip this.
 */
const props = withDefaults(defineProps<{
  /** "YYYY-MM-DD", or "YYYY-MM-DDTHH:mm" when `withTime`. Empty for unset. */
  modelValue: string;
  withTime?: boolean;
  placeholder?: string;
  invalid?: boolean;
  clearable?: boolean;
  disabled?: boolean;
}>(), {
  withTime: false,
  placeholder: "انتخاب تاریخ",
  invalid: false,
  clearable: true,
  disabled: false,
});

const emit = defineEmits<{ (e: "update:modelValue", v: string): void }>();

const root = ref<HTMLElement | null>(null);
const panel = ref<HTMLElement | null>(null);
const open = ref(false);
const pos = ref({ top: 0, left: 0, width: 260 });

const GAP = 4;
const PANEL_H = 340;

const layer = inject(MODAL_LAYER, null);
const panelZ = computed(() => 210 + (layer?.value ?? 0) * 150);

/** The date part of the value, and the time part, kept separate. */
const datePart = computed(() => (props.modelValue || "").slice(0, 10));
const timePart = computed(() => {
  const m = /T(\d{2}:\d{2})/.exec(props.modelValue || "");
  return m ? m[1] : "10:00";
});

const label = computed(() =>
  props.modelValue ? jalaliLabel(props.modelValue, props.withTime) : "",
);

/** Which Jalali month the grid is showing — not necessarily the selection. */
const cursor = ref<JalaliDate>(
  isoToJalali(datePart.value || todayIso()) ?? { jy: 1404, jm: 1, jd: 1 },
);

watch(() => props.modelValue, (v) => {
  const j = isoToJalali((v || "").slice(0, 10));
  if (j) cursor.value = j;
});

const selected = computed(() => isoToJalali(datePart.value));
const today = computed(() => isoToJalali(todayIso()));

/**
 * The month grid: leading blanks so the first day lands in its weekday
 * column, then the days. Trailing blanks are not needed — the grid just ends.
 */
const cells = computed(() => {
  const { jy, jm } = cursor.value;
  const lead = firstWeekdayColumn(jy, jm);
  const days = monthLength(jy, jm);
  const out: ({ jd: number } | null)[] = Array.from({ length: lead }, () => null);
  for (let jd = 1; jd <= days; jd++) out.push({ jd });
  return out;
});

function isSelected(jd: number): boolean {
  const s = selected.value;
  return !!s && s.jy === cursor.value.jy && s.jm === cursor.value.jm && s.jd === jd;
}
function isToday(jd: number): boolean {
  const t = today.value;
  return !!t && t.jy === cursor.value.jy && t.jm === cursor.value.jm && t.jd === jd;
}

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
  if (props.disabled) return;
  open.value = true;
  place();
  await nextTick();
  place();
}
function close() {
  open.value = false;
}

function emitValue(iso: string, time = timePart.value) {
  emit("update:modelValue", props.withTime ? `${iso}T${time}` : iso);
}

function pick(jd: number) {
  emitValue(jalaliToIso({ ...cursor.value, jd }));
  // With a time to set, the panel stays open so the next click is the hour.
  if (!props.withTime) close();
}

function pickToday() {
  emitValue(todayIso());
  if (!props.withTime) close();
}

function onTime(e: Event) {
  const time = (e.target as HTMLInputElement).value || "00:00";
  emitValue(datePart.value || todayIso(), time);
}

function clear() {
  emit("update:modelValue", "");
  close();
}

function step(delta: number) {
  cursor.value = addMonths(cursor.value, delta);
}

/** Same rule as PickerField: scrolling inside the panel must not close it. */
function onScroll(e: Event) {
  const t = e.target as Node | null;
  if (t && panel.value && (panel.value === t || panel.value.contains(t))) return;
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
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm outline-none " +
  "focus:ring-2 focus:ring-slate-300 flex items-center justify-between gap-2";
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      :class="[box, invalid ? 'ring-2 ring-red-300' : '',
               disabled ? 'opacity-60 cursor-not-allowed' : '']"
      :disabled="disabled"
      @click="open ? close() : show()"
      @keydown.escape="close"
    >
      <span :class="label ? 'text-ink truncate' : 'text-slate-400 truncate'">
        {{ label || placeholder }}
      </span>
      <span
        v-if="clearable && modelValue"
        class="text-slate-400 hover:text-ink shrink-0 text-base leading-none"
        role="button"
        aria-label="پاک کردن تاریخ"
        @click.stop="clear"
      >×</span>
      <svg
        v-else
        class="w-4 h-4 text-slate-400 shrink-0" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
      >
        <rect x="3" y="4" width="18" height="18" rx="2" />
        <path d="M16 2v4M8 2v4M3 10h18" />
      </svg>
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        ref="panel"
        class="fixed bg-surface rounded-2xl shadow-pop border border-slate-100
               overflow-hidden animate-pop p-2"
        :style="{
          top: pos.top + 'px',
          left: pos.left + 'px',
          width: Math.max(pos.width, 260) + 'px',
          zIndex: panelZ,
        }"
        dir="rtl"
      >
        <!-- Month header. The arrows point the way the reader's eye moves in
             RTL: «قبل» is on the right. -->
        <div class="flex items-center justify-between px-1 pb-2">
          <button
            type="button" class="text-slate-400 hover:text-ink px-2 py-1"
            aria-label="ماه قبل" @click="step(-1)"
          >‹</button>
          <span class="text-sm font-medium text-ink">
            {{ MONTH_NAMES[cursor.jm - 1] }} {{ faDigits(cursor.jy) }}
          </span>
          <button
            type="button" class="text-slate-400 hover:text-ink px-2 py-1"
            aria-label="ماه بعد" @click="step(1)"
          >›</button>
        </div>

        <div class="grid grid-cols-7 gap-0.5 text-center">
          <span
            v-for="w in WEEKDAY_NAMES" :key="w"
            class="text-[10px] text-slate-400 py-1"
          >{{ w }}</span>

          <template v-for="(cell, i) in cells" :key="i">
            <span v-if="!cell"></span>
            <button
              v-else
              type="button"
              class="text-xs rounded-lg py-1.5 transition-colors"
              :class="isSelected(cell.jd)
                ? 'bg-panel text-white'
                : isToday(cell.jd)
                  ? 'text-ink ring-1 ring-slate-300'
                  : 'text-slate-600 hover:bg-slate-100'"
              @click="pick(cell.jd)"
            >{{ faDigits(cell.jd) }}</button>
          </template>
        </div>

        <div class="flex items-center gap-2 pt-2 mt-1 border-t border-slate-100">
          <button
            type="button"
            class="text-xs text-slate-500 hover:bg-slate-100 rounded-lg px-2 py-1.5"
            @click="pickToday"
          >امروز</button>

          <span class="flex-1"></span>

          <template v-if="withTime">
            <label class="text-[11px] text-slate-400">ساعت</label>
            <input
              :value="timePart" type="time" dir="ltr"
              class="bg-slate-100 rounded-lg px-2 py-1 text-xs text-ink outline-none"
              @input="onTime"
            />
            <button
              type="button"
              class="text-xs bg-panel text-white rounded-lg px-3 py-1.5"
              @click="close"
            >تایید</button>
          </template>
        </div>
      </div>
    </Teleport>
  </div>
</template>
