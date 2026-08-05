<script setup lang="ts">
/**
 * The Admin Panel's own layout — deliberately separate from the business
 * app's AppShell. Different audience, different navigation, and a visual
 * identity (dark rail) that makes it obvious you are in system-management
 * territory rather than looking at dashboards.
 *
 * Menu entries are permission-filtered: an admin never sees a section whose
 * API would answer 403.
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import { useAdminStore } from "@/stores/admin";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";
import { usePresence } from "@/composables/usePresence";
import NavIcon from "@/components/NavIcon.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import CommandPalette from "@/components/admin/CommandPalette.vue";
import type { AdminNavItem } from "@/types/admin";

const admin = useAdminStore();
const auth = useAuthStore();
const ui = useUiStore();
const route = useRoute();
const router = useRouter();

usePresence();

const collapsed = ref(localStorage.getItem("adminRailCollapsed") === "1");
const mobileOpen = ref(false);
const paletteOpen = ref(false);

const NAV: AdminNavItem[] = [
  { name: "admin-dashboard", label: "داشبورد", icon: "grid", permissions: [], group: "overview" },

  { name: "admin-users", label: "کاربران", icon: "users", permissions: ["users.view"], group: "people" },
  { name: "admin-roles", label: "نقش‌ها و دسترسی‌ها", icon: "key", permissions: ["roles.view"], group: "people" },
  { name: "admin-teams", label: "تیم‌ها", icon: "team", permissions: ["teams.view"], group: "people" },

  { name: "admin-data", label: "مدیریت داده", icon: "database", permissions: ["data.view"], group: "data" },
  { name: "admin-reports", label: "گزارش‌ها", icon: "clipboard", permissions: ["reports.view"], group: "data" },
  { name: "admin-database", label: "پایگاه داده", icon: "layers", permissions: ["db.view"], group: "data" },

  { name: "admin-system", label: "تنظیمات سیستم", icon: "settings", permissions: ["system.view"], group: "system" },
  { name: "admin-workflow", label: "گردش‌کار", icon: "workflow", permissions: ["workflow.view"], group: "system" },
  { name: "admin-monitoring", label: "پایش", icon: "activity", permissions: ["monitor.view"], group: "system" },

  { name: "admin-security", label: "امنیت", icon: "shield", permissions: ["security.view"], group: "guard" },
  { name: "admin-audit", label: "گزارش رخدادها", icon: "history", permissions: ["audit.view"], group: "guard" },

  { name: "admin-notifications", label: "اعلان‌ها", icon: "megaphone", permissions: ["notify.view"], group: "content" },
  { name: "admin-content", label: "محتوا", icon: "tag", permissions: ["content.view"], group: "content" },
  { name: "admin-files", label: "فایل‌ها", icon: "folder", permissions: ["files.view"], group: "content" },
];

const GROUP_LABELS: Record<string, string> = {
  overview: "",
  people: "افراد",
  data: "داده",
  system: "سیستم",
  guard: "امنیت و نظارت",
  content: "محتوا",
};

const visible = computed(() =>
  NAV.filter((item) => !item.permissions.length || admin.canAny(item.permissions)),
);

const grouped = computed(() => {
  const out: { key: string; label: string; items: AdminNavItem[] }[] = [];
  for (const item of visible.value) {
    const existing = out.find((g) => g.key === item.group);
    if (existing) existing.items.push(item);
    else out.push({ key: item.group, label: GROUP_LABELS[item.group] ?? "", items: [item] });
  }
  return out;
});

const currentLabel = computed(
  () => NAV.find((n) => n.name === route.name)?.label ?? "پنل مدیریت",
);

function go(name: string) {
  router.push({ name });
  mobileOpen.value = false;
}

function toggleRail() {
  collapsed.value = !collapsed.value;
  localStorage.setItem("adminRailCollapsed", collapsed.value ? "1" : "0");
}

// ---- keyboard shortcuts (power users) ----
// Ctrl/⌘+K opens the palette; g then <n> jumps to the nth visible section.
let chord = false;
let chordTimer: number | undefined;

function onKey(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null;
  const typing = !!target && (
    target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable
  );

  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    paletteOpen.value = true;
    return;
  }
  if (typing) return;

  if (event.key === "?") { paletteOpen.value = true; return; }
  if (event.key.toLowerCase() === "g") {
    chord = true;
    window.clearTimeout(chordTimer);
    chordTimer = window.setTimeout(() => (chord = false), 1200);
    return;
  }
  if (chord && /^[1-9]$/.test(event.key)) {
    const item = visible.value[Number(event.key) - 1];
    if (item) go(item.name);
    chord = false;
  }
  if (chord && event.key.toLowerCase() === "b") { toggleRail(); chord = false; }
}

onMounted(() => {
  window.addEventListener("keydown", onKey);
  admin.bootstrap().catch(() => router.replace({ name: "home" }));
});
onUnmounted(() => window.removeEventListener("keydown", onKey));

watch(() => route.name, () => (mobileOpen.value = false));

function backToApp() { router.push({ name: "home" }); }
function logout() { auth.logout(); admin.reset(); router.push({ name: "login" }); }
</script>

<template>
  <div class="min-h-screen bg-canvas md:flex md:gap-4 md:p-4" dir="rtl">
    <div
      v-if="mobileOpen"
      class="fixed inset-0 bg-black/40 z-40 md:hidden"
      @click="mobileOpen = false"
    ></div>

    <!-- ===== Rail ===== -->
    <aside
      class="bg-panel text-white flex flex-col shrink-0 transition-transform duration-200
             fixed inset-y-0 right-0 z-50 w-64 h-screen
             md:sticky md:top-4 md:z-auto md:rounded-card md:h-[calc(100vh-2rem)]"
      :class="[
        collapsed ? 'md:w-[74px]' : 'md:w-64',
        mobileOpen ? 'translate-x-0' : 'translate-x-full md:translate-x-0',
      ]"
    >
      <div class="flex items-center gap-3 p-4" :class="collapsed ? 'justify-center' : ''">
        <span class="w-9 h-9 rounded-2xl bg-white/10 grid place-items-center shrink-0">
          <NavIcon name="shield" :size="19" />
        </span>
        <div v-if="!collapsed" class="flex-1 min-w-0">
          <p class="font-bold text-sm leading-tight">پنل مدیریت</p>
          <p class="text-[11px] text-white/50 truncate">{{ admin.companyName }}</p>
        </div>
        <button
          v-if="!collapsed"
          class="text-white/50 hover:text-white hidden md:block"
          aria-label="جمع کردن منو"
          @click="toggleRail"
        ><NavIcon name="chevron" :size="18" /></button>
      </div>
      <button
        v-if="collapsed"
        class="mx-auto mb-2 text-white/50 hover:text-white rotate-180 hidden md:block"
        aria-label="باز کردن منو"
        @click="toggleRail"
      ><NavIcon name="chevron" :size="18" /></button>

      <nav class="flex-1 overflow-y-auto px-2.5 pb-2 space-y-0.5">
        <template v-for="group in grouped" :key="group.key">
          <p
            v-if="group.label && !collapsed"
            class="text-[10px] uppercase tracking-wide text-white/35 px-3 pt-3 pb-1"
          >{{ group.label }}</p>
          <div v-else-if="group.label && collapsed" class="h-px bg-white/10 my-2 mx-2"></div>

          <button
            v-for="item in group.items"
            :key="item.name"
            class="w-full flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition"
            :class="[
              route.name === item.name
                ? 'bg-white text-panel font-medium'
                : 'text-white/70 hover:bg-white/10 hover:text-white',
              collapsed ? 'justify-center' : '',
            ]"
            :title="collapsed ? item.label : ''"
            @click="go(item.name)"
          >
            <NavIcon :name="item.icon" :size="19" />
            <span v-if="!collapsed" class="flex-1 text-right truncate">{{ item.label }}</span>
          </button>
        </template>
      </nav>

      <div class="p-2.5 border-t border-white/10 space-y-0.5">
        <button
          class="w-full flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-white/70 hover:bg-white/10 hover:text-white transition"
          :class="collapsed ? 'justify-center' : ''"
          :title="collapsed ? 'بازگشت به داشبوردها' : ''"
          @click="backToApp"
        >
          <NavIcon name="chart" :size="19" />
          <span v-if="!collapsed" class="flex-1 text-right">بازگشت به سامانه</span>
        </button>
        <button
          class="w-full flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-red-300 hover:bg-red-500/15 transition"
          :class="collapsed ? 'justify-center' : ''"
          :title="collapsed ? 'خروج' : ''"
          @click="logout"
        >
          <NavIcon name="logout" :size="19" />
          <span v-if="!collapsed" class="flex-1 text-right">خروج</span>
        </button>
      </div>
    </aside>

    <!-- ===== Main ===== -->
    <div class="flex-1 min-w-0 flex flex-col gap-4 p-3 md:p-0">
      <header class="bg-surface rounded-card shadow-soft px-4 py-3 flex items-center justify-between gap-2">
        <div class="flex items-center gap-2 min-w-0">
          <button
            class="md:hidden text-slate-500 hover:text-ink p-1"
            aria-label="منو"
            @click="mobileOpen = true"
          ><NavIcon name="grid" :size="22" /></button>
          <h1 class="font-bold text-ink truncate">{{ currentLabel }}</h1>
          <span
            v-if="admin.maintenance"
            class="hidden sm:inline-flex items-center gap-1 text-[11px] bg-amber-50 text-amber-700 rounded-full px-2 py-0.5"
          >
            <NavIcon name="alert" :size="12" /> حالت تعمیرات فعال است
          </span>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          <button
            class="hidden lg:flex items-center gap-2 bg-slate-100 rounded-full px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-200 transition"
            @click="paletteOpen = true"
          >
            <NavIcon name="search" :size="14" />
            <span>جستجوی سریع</span>
            <kbd class="bg-surface rounded px-1 text-[10px] border border-slate-200">Ctrl K</kbd>
          </button>
          <button
            class="p-2 rounded-full hover:bg-slate-100 text-slate-500 hover:text-ink transition"
            :title="ui.dark ? 'حالت روشن' : 'حالت شب'"
            :aria-label="ui.dark ? 'حالت روشن' : 'حالت شب'"
            @click="ui.toggleDark()"
          >
            <svg
              v-if="ui.dark" class="w-5 h-5" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
            >
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
            </svg>
            <svg
              v-else class="w-5 h-5" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
            >
              <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
            </svg>
          </button>
          <div class="flex items-center gap-2 pr-2 border-r border-slate-100">
            <UserAvatar
              :name="admin.user?.name"
              :initials="admin.user?.initials"
              :color="admin.user?.avatar_color"
              :image="admin.user?.avatar_image"
              :online="true"
              :size="34"
            />
            <div class="hidden sm:block leading-tight">
              <p class="text-xs font-semibold text-ink">{{ admin.user?.name }}</p>
              <p class="text-[10px] text-slate-400">
                {{ admin.isSuperuser ? "ادمین ارشد" : "ادمین سیستم" }}
              </p>
            </div>
          </div>
        </div>
      </header>

      <main class="flex-1 min-w-0">
        <div v-if="admin.error" class="bg-red-50 text-red-600 rounded-card p-6 text-center">
          {{ admin.error }}
        </div>
        <RouterView v-else-if="admin.loaded" />
        <div v-else class="text-center text-slate-400 py-16 text-sm">در حال بارگذاری…</div>
      </main>

      <footer class="text-center text-[11px] text-slate-400 pb-2">
        پنل مدیریت · {{ admin.companyName }}
      </footer>
    </div>

    <CommandPalette v-model:open="paletteOpen" :items="visible" @go="go" />
  </div>
</template>
