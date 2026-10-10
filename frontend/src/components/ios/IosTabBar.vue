<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import NavIcon from "@/components/NavIcon.vue";
import { store } from "@/lib/storage";

/**
 * The iOS skin's tab bar, drawn the iOS / iPadOS 26 way.
 *
 * Phone: a Liquid Glass capsule at the bottom with «بیشتر» in a glass circle
 * beside it; the capsule shrinks to icons while you scroll down. «بیشتر»
 * opens the shell's drawer, so every destination stays one tap away.
 *
 * Desktop: as on iPad — the sidebar starts closed, the tabs float at the top
 * centre, and a sidebar button in the leading corner swaps the tab bar for
 * the full sidebar (and back). That choice is remembered per device.
 *
 * Both: which destinations sit in the bar is the user's call, as with
 * UITabBarController's customisation. Long-press or right-click the bar, or
 * use «ویرایش نوار تب» in the appearance panel, to pick them. Saved per
 * workspace (`scope`) and per device.
 *
 * Rendered only while the iOS skin is on; the other skins keep their
 * sidebar and hamburger exactly as they were.
 */
export interface TabItem {
  name: string;
  label: string;
  icon: string;
  badge?: () => number | string | null | undefined;
}

const props = defineProps<{
  /** Every destination this workspace has, in menu order. */
  items: TabItem[];
  isActive: (name: string) => boolean;
  /** Storage key for this workspace's own tab choice. */
  scope: string;
}>();
const emit = defineEmits<{ go: [name: string]; more: [] }>();

const PHONE_MAX = 4;
const DESKTOP_MAX = 6;

// ---- which tabs ------------------------------------------------------
const key = computed(() => `iosTabs.${props.scope}`);
const chosen = ref<string[] | null>(read());
function read(): string[] | null {
  try {
    const raw = store.get(`iosTabs.${props.scope}`);
    const v = raw ? JSON.parse(raw) : null;
    return Array.isArray(v) ? v : null;
  } catch {
    return null;
  }
}
function save(v: string[] | null) {
  chosen.value = v;
  try {
    if (v) store.set(key.value, JSON.stringify(v));
    else store.remove(key.value);
  } catch {
    /* a private window: the choice lasts for this visit only */
  }
}

const desktop = ref(false);
let mq: MediaQueryList | null = null;
const onMq = () => (desktop.value = !!mq?.matches);

const max = computed(() => (desktop.value ? DESKTOP_MAX : PHONE_MAX));
const pinned = computed<TabItem[]>(() => {
  const byName = new Map(props.items.map((i) => [i.name, i]));
  const picked = (chosen.value ?? []).map((n) => byName.get(n)).filter(Boolean) as TabItem[];
  const list = picked.length ? picked : props.items;
  return list.slice(0, max.value);
});
const onTab = computed(() => pinned.value.some((t) => props.isActive(t.name)));

// ---- desktop sidebar ---------------------------------------------------
const sidebarOpen = ref(store.get("iosSidebar") === "1");
function applySidebar() {
  document.documentElement.classList.toggle("ios-sidebar-open", sidebarOpen.value);
}
function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value;
  try { store.set("iosSidebar", sidebarOpen.value ? "1" : "0"); } catch { /* fine */ }
  applySidebar();
}
function onMore() {
  if (desktop.value) toggleSidebar();
  else emit("more");
}

// First visit on a desktop: point at «همه‌ی بخش‌ها» once, then never again.
const hint = ref(false);
let hintTimer = 0;
function dismissHint() {
  if (!hint.value) return;
  hint.value = false;
  window.clearTimeout(hintTimer);
  try { store.set("iosSidebarHint", "1"); } catch { /* fine */ }
}

// ---- minimise on scroll (phone) -----------------------------------------
const minimised = ref(false);
let lastY = 0;
function onScroll() {
  const y = window.scrollY;
  if (desktop.value || y < 60) minimised.value = false; // iPad's bar never shrinks
  else if (y > lastY + 6) minimised.value = true;
  else if (y < lastY - 6) minimised.value = false;
  lastY = y;
}

// ---- editing --------------------------------------------------------------
const editing = ref(false);
const draft = ref<string[]>([]);
function openEditor() {
  // The whole saved list, not just what fits this screen: editing on a
  // phone must not drop the fifth and sixth tabs the desktop shows.
  const names = new Set(props.items.map((i) => i.name));
  const saved = (chosen.value ?? []).filter((n) => names.has(n));
  draft.value = saved.length ? saved : props.items.slice(0, DESKTOP_MAX).map((i) => i.name);
  editing.value = true;
}
function togglePick(name: string) {
  const i = draft.value.indexOf(name);
  if (i >= 0) draft.value.splice(i, 1);
  else if (draft.value.length < DESKTOP_MAX) draft.value.push(name);
}
function done() {
  save(draft.value.length ? [...draft.value] : null);
  editing.value = false;
}
function reset() {
  save(null);
  editing.value = false;
}

// Long-press anywhere on the bar opens the editor, as on iOS.
let pressTimer = 0;
let longPressed = false;
function pressStart() {
  longPressed = false;
  window.clearTimeout(pressTimer);
  pressTimer = window.setTimeout(() => {
    longPressed = true;
    openEditor();
  }, 550);
}
function pressEnd() {
  window.clearTimeout(pressTimer);
}
function tap(name: string) {
  if (longPressed) return; // the press that opened the editor is not a tap
  emit("go", name);
}

const onEditEvent = () => openEditor();

onMounted(() => {
  mq = window.matchMedia("(min-width: 768px)");
  onMq();
  mq.addEventListener("change", onMq);
  applySidebar();
  if (desktop.value && !sidebarOpen.value && store.get("iosSidebarHint") !== "1") {
    hint.value = true;
    hintTimer = window.setTimeout(dismissHint, 7000);
  }
  lastY = window.scrollY;
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("ios-edit-tabs", onEditEvent);
});
onBeforeUnmount(() => {
  mq?.removeEventListener("change", onMq);
  window.removeEventListener("scroll", onScroll);
  window.removeEventListener("ios-edit-tabs", onEditEvent);
  window.clearTimeout(pressTimer);
  window.clearTimeout(hintTimer);
});
</script>

<template>
  <!-- Desktop, sidebar open: the button that closes it, in its top corner.
       (While it is closed, the opener sits beside the tabs instead.) -->
  <button
    class="ios-sidebar-toggle no-print"
    :aria-pressed="sidebarOpen"
    :aria-label="sidebarOpen ? 'بستن نوار کناری' : 'باز کردن نوار کناری'"
    :title="sidebarOpen ? 'بستن نوار کناری' : 'باز کردن نوار کناری'"
    @click="toggleSidebar"
  >
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="3.5" />
      <path d="M15 4v16" />
    </svg>
  </button>

  <!-- Desktop: rendered inside the shell's nav bar (its .ios-tabslot), so it
       only ever gets the room between the title and the toolbar and can
       never sit on top of either. Phone: fixed at the bottom of the screen. -->
  <Teleport defer to=".ios-tabslot" :disabled="!desktop">
  <nav
    class="ios-tabbar no-print"
    :class="{ 'is-min': minimised }"
    aria-label="بخش‌های اصلی"
    @contextmenu.prevent="openEditor"
    @pointerdown="pressStart"
    @pointerup="pressEnd"
    @pointerleave="pressEnd"
    @pointercancel="pressEnd"
  >
    <div class="ios-tabgroup">
      <button
        v-for="t in pinned"
        :key="t.name"
        class="ios-tab"
        :class="{ 'is-active': isActive(t.name) }"
        :aria-current="isActive(t.name) ? 'page' : undefined"
        :aria-label="t.label"
        @click="tap(t.name)"
      >
        <span class="relative">
          <NavIcon :name="t.icon" :size="23" />
          <span v-if="t.badge && t.badge()" class="ios-tab-badge ltr-nums">{{ t.badge() }}</span>
        </span>
        <span class="ios-tab-label">{{ t.label }}</span>
      </button>
    </div>
    <!-- Phone: «بیشتر» opens the drawer. Desktop: «همه‌ی بخش‌ها» opens the
         sidebar — labelled, and right beside the tabs, because a bare icon
         in a corner is the kind of control nobody finds. -->
    <button
      class="ios-tab-more"
      :class="{ 'is-active': !onTab && !desktop }"
      :aria-label="desktop ? 'همه‌ی بخش‌ها — باز کردن نوار کناری' : 'بخش‌های بیشتر'"
      :title="desktop ? 'باز کردن نوار کناری' : undefined"
      @click="onMore(); dismissHint()"
    >
      <svg v-if="!desktop" width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" />
      </svg>
      <template v-else>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="3" y="4" width="18" height="16" rx="3.5" />
          <path d="M15 4v16" />
        </svg>
        <span class="ios-tab-more-label">همه‌ی بخش‌ها</span>
      </template>
      <span v-if="desktop && hint" class="ios-hint" role="status" @click.stop="dismissHint">
        همه‌ی بخش‌ها اینجاست — نوار کناری را باز می‌کند
      </span>
    </button>
  </nav>
  </Teleport>

  <!-- «ویرایش نوار تب»: a sheet listing every destination. -->
  <Teleport to="body">
    <div
      v-if="editing"
      class="fixed inset-0 z-[120] bg-black/40 flex items-center justify-center p-4"
      dir="rtl"
      @click.self="editing = false"
    >
      <div class="ios-tab-editor bg-surface rounded-3xl shadow-pop w-full max-w-md flex flex-col max-h-[85vh] animate-pop" role="dialog" aria-label="ویرایش نوار تب">
        <header class="flex items-center justify-between gap-3 px-5 pt-4 pb-2">
          <button class="text-sm text-slate-500 px-2 py-1" @click="reset">پیش‌فرض</button>
          <h3 class="font-bold text-ink">ویرایش نوار تب</h3>
          <button class="text-sm font-semibold text-brand-500 px-2 py-1" @click="done">تمام</button>
        </header>
        <p class="px-5 pb-3 text-xs text-slate-400 leading-5">
          به ترتیب انتخاب در نوار می‌نشینند. روی گوشی {{ PHONE_MAX }} تای اول و روی کامپیوتر تا {{ DESKTOP_MAX }} تا نمایش داده می‌شود.
        </p>
        <ul class="overflow-y-auto px-3 pb-4 space-y-1">
          <li v-for="it in items" :key="it.name">
            <button
              class="ios-edit-row w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-right hover:bg-slate-50"
              :aria-pressed="draft.includes(it.name)"
              :disabled="!draft.includes(it.name) && draft.length >= DESKTOP_MAX"
              @click="togglePick(it.name)"
            >
              <span class="ios-edit-tile"><NavIcon :name="it.icon" :size="17" /></span>
              <span class="flex-1 text-sm text-ink">{{ it.label }}</span>
              <span
                v-if="draft.includes(it.name)"
                class="ios-edit-order ltr-nums"
              >{{ draft.indexOf(it.name) + 1 }}</span>
              <span v-else class="ios-edit-empty"></span>
            </button>
          </li>
        </ul>
      </div>
    </div>
  </Teleport>
</template>
