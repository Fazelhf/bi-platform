<script setup lang="ts">
/**
 * اتوماسیون اداری — its own workspace, built on the same rail as CRM.
 *
 * While it was one page (مکاتبات) a single sidebar row was right. With five
 * sections it was five rows competing with تولید and مالی for the same
 * space, which made the main menu read as a list of everything rather than a
 * list of areas. One door in, and the rail takes over from there.
 *
 * گفتگو and یادداشت‌ها moved in with it. They were general collaboration rows
 * before this existed; now they are two of the six things this workspace is
 * for, and leaving them outside would mean checking two menus for the same
 * kind of work. Their URLs are unchanged, so old links still open.
 */
import { computed, ref } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { usePresence } from "@/composables/usePresence";
import { useClickOutside } from "@/composables/useClickOutside";
import { homeRouteFor } from "@/router";
import NavIcon from "@/components/NavIcon.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import ThemePicker from "@/components/ThemePicker.vue";
import NotificationBell from "@/components/NotificationBell.vue";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

usePresence();

const collapsed = ref(localStorage.getItem("officeRailCollapsed") === "1");
const mobileOpen = ref(false);

const NAV = [
  { name: "office-home", label: "میز کار", icon: "grid" },
  { name: "office-letters", label: "مکاتبات", icon: "inbox" },
  { name: "office-tasks", label: "وظایف", icon: "check" },
  { name: "office-projects", label: "پروژه‌ها", icon: "clipboard" },
  { name: "chat", label: "گفتگو", icon: "chat" },
  { name: "notes", label: "یادداشت‌ها", icon: "notes" },
];

/** A detail page keeps its list row lit, so you can tell where you are. */
const PARENT: Record<string, string> = {
  "office-letter": "office-letters",
  "office-project": "office-projects",
};

function active(name: string): boolean {
  const current = String(route.name ?? "");
  return current === name || PARENT[current] === name;
}

const pageTitle = computed(
  () => NAV.find((n) => active(n.name))?.label ?? "اتوماسیون اداری",
);

const userMenu = ref(false);
const userMenuRoot = ref<HTMLElement | null>(null);
useClickOutside(userMenuRoot, () => (userMenu.value = false));

function toggleRail() {
  collapsed.value = !collapsed.value;
  localStorage.setItem("officeRailCollapsed", collapsed.value ? "1" : "0");
}

function go(name: string) {
  router.push({ name });
  mobileOpen.value = false;
}

/** Back to the rest of the platform, at whatever this account's home is. */
function leave() {
  router.push({ name: homeRouteFor(auth.department) });
}
</script>

<template>
  <div class="min-h-screen md:flex md:gap-4 md:p-4" dir="rtl">
    <div
      v-if="mobileOpen"
      class="fixed inset-0 bg-black/40 z-40 md:hidden"
      @click="mobileOpen = false"
    ></div>

    <aside
      class="bg-surface flex flex-col shrink-0 transition-transform duration-200
             fixed inset-y-0 right-0 z-50 w-64 h-screen
             md:sticky md:top-4 md:z-auto md:rounded-card md:shadow-soft md:h-[calc(100vh-2rem)]"
      :class="[
        collapsed ? 'md:w-[74px]' : 'md:w-64',
        mobileOpen ? 'translate-x-0' : 'translate-x-full md:translate-x-0',
      ]"
    >
      <div class="flex items-center gap-3 p-4" :class="collapsed ? 'justify-center' : ''">
        <span class="w-9 h-9 rounded-2xl bg-panel text-white grid place-items-center shrink-0">
          <NavIcon name="inbox" :size="19" />
        </span>
        <div v-if="!collapsed" class="flex-1 min-w-0">
          <p class="font-bold text-sm text-ink leading-tight">اتوماسیون اداری</p>
          <p class="text-[11px] text-slate-400 truncate">نامه، کار و گفتگو</p>
        </div>
        <button
          v-if="!collapsed"
          class="text-slate-400 hover:text-ink hidden md:block"
          aria-label="جمع کردن منو"
          @click="toggleRail"
        ><NavIcon name="chevron" :size="18" /></button>
      </div>
      <button
        v-if="collapsed"
        class="mx-auto mb-2 text-slate-400 hover:text-ink rotate-180 hidden md:block"
        aria-label="باز کردن منو"
        @click="toggleRail"
      ><NavIcon name="chevron" :size="18" /></button>

      <nav class="flex-1 overflow-y-auto px-2.5 pb-2 space-y-0.5">
        <button
          v-for="item in NAV"
          :key="item.name"
          class="w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm transition"
          :class="[
            active(item.name) ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100',
            collapsed ? 'justify-center' : '',
          ]"
          :title="collapsed ? item.label : ''"
          @click="go(item.name)"
        >
          <NavIcon :name="item.icon" :size="20" />
          <span v-if="!collapsed" class="flex-1 text-right">{{ item.label }}</span>
        </button>
      </nav>

      <!-- The way out, in one fixed place. -->
      <div class="p-3 border-t border-slate-100">
        <button
          class="w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm
                 text-slate-500 hover:bg-slate-100 transition"
          :class="collapsed ? 'justify-center' : ''"
          title="بازگشت به بقیه‌ی سامانه"
          @click="leave"
        >
          <NavIcon name="chevron" :size="20" />
          <span v-if="!collapsed" class="flex-1 text-right">خروج از اتوماسیون</span>
        </button>
      </div>
    </aside>

    <div class="flex-1 min-w-0 p-3 md:p-0">
      <header class="bg-surface md:rounded-card md:shadow-soft px-3 sm:px-4 h-14 flex items-center gap-3 mb-4">
        <button
          class="md:hidden text-slate-500 p-1"
          aria-label="منو"
          @click="mobileOpen = true"
        ><NavIcon name="grid" :size="22" /></button>

        <h1 class="font-bold text-ink">{{ pageTitle }}</h1>

        <div class="flex-1"></div>

        <ThemePicker />
        <NotificationBell />

        <div ref="userMenuRoot" class="relative shrink-0">
          <button class="flex items-center" @click="userMenu = !userMenu">
            <UserAvatar :user="auth.me" :size="34" />
          </button>
          <div
            v-if="userMenu"
            class="absolute left-0 mt-2 w-52 bg-surface rounded-2xl shadow-pop
                   border border-slate-100 p-1.5 z-50"
          >
            <p class="px-3 py-2 text-xs text-slate-400 truncate">
              {{ auth.me?.display_name_fa || auth.me?.username }}
            </p>
            <button
              class="w-full text-right px-3 py-2 text-sm rounded-xl hover:bg-slate-100"
              @click="userMenu = false; router.push({ name: 'profile-me' })"
            >پروفایل من</button>
            <button
              class="w-full text-right px-3 py-2 text-sm rounded-xl hover:bg-slate-100"
              @click="userMenu = false; leave()"
            >بازگشت به سامانه</button>
            <button
              class="w-full text-right px-3 py-2 text-sm rounded-xl text-red-500 hover:bg-red-50"
              @click="auth.logout(); router.push({ name: 'login' })"
            >خروج از حساب</button>
          </div>
        </div>
      </header>

      <RouterView />
    </div>
  </div>
</template>
