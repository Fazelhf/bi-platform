<script setup lang="ts">
/**
 * اتوماسیون اداری — the workspace shell.
 *
 * The first version was the CRM rail with different labels, and it read that
 * way: six grey rows, six grey pages, nothing telling you where you were
 * except the heading. Three things changed.
 *
 * **Each section owns a colour.** It lights its rail row, tints the page
 * header, and is published as `--sec` for the page itself to use. That is the
 * cue that arrives before you read anything.
 *
 * **The header carries the section, not just a word.** Title, one line of
 * what the section is for, and room for the page's own actions — so pages
 * stop each inventing their own toolbar strip.
 *
 * **Counts live on the rail.** Unread letters and open tasks are the two
 * numbers people come here for; putting them beside the section names means
 * the workspace answers «چیزی هست؟» without a click.
 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import { workApi } from "@/api/officeWork";
import { useAuthStore } from "@/stores/auth";
import { usePresence } from "@/composables/usePresence";
import { useClickOutside } from "@/composables/useClickOutside";
import { homeRouteFor } from "@/router";
import { OFFICE_SECTIONS, isActive, sectionFor } from "@/components/office/sections";
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
const section = computed(() => sectionFor(route.name as string));

/** Live counts for the rail. Refreshed on a slow timer — these are hints. */
const badges = ref<Record<string, number>>({});
let timer: number | undefined;

async function loadBadges() {
  try {
    const wb = await workApi.workbench();
    const by = Object.fromEntries(wb.tiles.map((t) => [t.key, t.value]));
    badges.value = {
      "office-letters": by.letters ?? 0,
      "office-tasks": by.today ?? 0,
      chat: by.messages ?? 0,
    };
  } catch {
    // A badge is a nicety; the workspace must open without it.
    badges.value = {};
  }
}

onMounted(() => {
  loadBadges();
  timer = window.setInterval(loadBadges, 60_000);
});
onUnmounted(() => window.clearInterval(timer));

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
  <div
    class="office-workspace min-h-screen md:flex md:gap-4 md:p-4"
    dir="rtl"
    :style="{ '--sec': section.color }"
  >
    <div
      v-if="mobileOpen"
      class="fixed inset-0 bg-black/40 z-40 md:hidden"
      @click="mobileOpen = false"
    ></div>

    <!-- ===== Rail ===== -->
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
        <span
          class="w-9 h-9 rounded-2xl grid place-items-center shrink-0 text-white transition-colors"
          :style="{ background: 'rgb(' + section.color + ')' }"
        >
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

      <nav class="flex-1 overflow-y-auto px-2.5 pb-2 space-y-1">
        <button
          v-for="item in OFFICE_SECTIONS"
          :key="item.name"
          class="office-nav w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm transition-colors"
          :class="[
            isActive(item.name, route.name as string) ? 'is-active' : 'text-slate-500 hover:bg-slate-100',
            collapsed ? 'justify-center' : '',
          ]"
          :style="{ '--row': item.color }"
          :title="collapsed ? item.label : ''"
          @click="go(item.name)"
        >
          <NavIcon :name="item.icon" :size="20" />
          <template v-if="!collapsed">
            <span class="flex-1 text-right">{{ item.label }}</span>
            <span
              v-if="badges[item.name]"
              class="text-[10px] rounded-full min-w-[18px] px-1.5 leading-[18px] text-center ltr-nums shrink-0"
              :class="isActive(item.name, route.name as string)
                ? 'bg-white/25 text-white'
                : 'bg-slate-100 text-slate-500'"
            >{{ badges[item.name] }}</span>
          </template>
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

    <!-- ===== Content ===== -->
    <div class="flex-1 min-w-0 p-3 md:p-0">
      <header
        class="bg-surface md:rounded-card md:shadow-soft mb-4 overflow-hidden"
      >
        <!-- The section's colour as a top edge: present without shouting. -->
        <div class="h-1" :style="{ background: 'rgb(' + section.color + ')' }"></div>
        <div class="px-4 sm:px-5 py-3 flex items-center gap-3">
          <button
            class="md:hidden text-slate-500 p-1 shrink-0"
            aria-label="منو"
            @click="mobileOpen = true"
          ><NavIcon name="grid" :size="22" /></button>

          <span
            class="w-9 h-9 rounded-xl grid place-items-center shrink-0 text-white hidden sm:grid"
            :style="{ background: 'rgb(' + section.color + ')' }"
          >
            <NavIcon :name="section.icon" :size="18" />
          </span>

          <div class="min-w-0">
            <h1 class="font-bold text-ink leading-tight">{{ section.label }}</h1>
            <p class="text-[11px] text-slate-400 truncate">{{ section.hint }}</p>
          </div>

          <div class="flex-1"></div>

          <!-- Pages put their own buttons here instead of each building a
               second toolbar card under the header. -->
          <div id="office-actions" class="flex items-center gap-2"></div>

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
        </div>
      </header>

      <RouterView />
    </div>
  </div>
</template>
