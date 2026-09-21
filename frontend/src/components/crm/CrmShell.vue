<script setup lang="ts">
/**
 * CRM's own workspace — its own shell, but the same shape as the rest of the
 * platform: a rail on the right, content beside it.
 *
 * It is separate from AppShell because the audience is different (a
 * salesperson lives here and never opens تولید or نقدینگی) and because the
 * way out should be one fixed button rather than a hunt. It is *not* a
 * different kind of navigation: a row of top tabs was tried and read as a
 * foreign app bolted on, so the rail everyone already knows stays.
 *
 * Section names are the company's own words — معامله، کاریز، پیگیری، مشتری —
 * the ones the team has been saying in دیدار for years. Renaming them to
 * «فرصت فروش» or «قیف» would be a vocabulary to translate on every screen.
 */
import { computed, onMounted, ref } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { useCrmStore } from "@/stores/crm";
import { usePresence } from "@/composables/usePresence";
import { useClickOutside } from "@/composables/useClickOutside";
import { homeRouteFor } from "@/router";
import NavIcon from "@/components/NavIcon.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import ThemePicker from "@/components/ThemePicker.vue";
import NotificationBell from "@/components/NotificationBell.vue";
import DrillDrawer from "@/components/crm/DrillDrawer.vue";
import QuickAdd from "@/components/crm/QuickAdd.vue";
import CrmSearch from "@/components/crm/CrmSearch.vue";

const auth = useAuthStore();
const crm = useCrmStore();
const route = useRoute();
const router = useRouter();

usePresence();

const collapsed = ref(localStorage.getItem("crmRailCollapsed") === "1");
const mobileOpen = ref(false);

/**
 * `managerOnly` marks the sections that are about the customer *file* rather
 * than about a book of customers. بازبینی تطبیق compares every account with
 * every other by definition, so there is no per-rep slice of it — the API
 * answers 403, and a menu entry that always leads to a refusal is worse than
 * no entry.
 */
const NAV = [
  // First, deliberately: this is the screen a rep opens in the morning, and
  // the only one that tells them what to do rather than what happened.
  { name: "crm-today", label: "کارتابل امروز", icon: "check" },
  { name: "crm-dashboard", label: "داشبورد", icon: "grid" },
  { name: "crm-customers", label: "مشتری‌ها", icon: "team" },
  { name: "crm-deals", label: "معامله‌ها", icon: "box" },
  { name: "crm-pipeline", label: "کاریز فروش", icon: "target" },
  { name: "crm-activities", label: "پیگیری‌ها", icon: "notes" },
  { name: "crm-reports", label: "گزارش‌ها", icon: "chart" },
  { name: "crm-match-review", label: "بازبینی تطبیق", icon: "check", managerOnly: true },
] as { name: string; label: string; icon: string; managerOnly?: boolean }[];

const nav = computed(() => NAV.filter((n) => !n.managerOnly || crm.isManager));

/** A detail page keeps its list row lit, so you can tell where you are. */
const PARENT: Record<string, string> = {
  "crm-deal": "crm-deals",
  "crm-customer": "crm-customers",
};

function active(name: string): boolean {
  const current = String(route.name ?? "");
  return current === name || PARENT[current] === name;
}

const pageTitle = computed(
  () => NAV.find((n) => active(n.name))?.label ?? "CRM",
);

/**
 * The subtitle under the CRM mark says which of the two jobs this account is
 * here to do. It is not decoration: the same screens behave differently for
 * the two, and someone who does not know which one they are looking at reads
 * a missing filter as a missing feature.
 */
const roleLabel = computed(() => (crm.isManager ? "نمای مدیر فروش" : "میز کار کارشناس"));

const userMenu = ref(false);
const userMenuRoot = ref<HTMLElement | null>(null);
useClickOutside(userMenuRoot, () => (userMenu.value = false));

function toggleRail() {
  collapsed.value = !collapsed.value;
  localStorage.setItem("crmRailCollapsed", collapsed.value ? "1" : "0");
}

function go(name: string) {
  router.push({ name });
  mobileOpen.value = false;
}

/** Back to the rest of the platform, at whatever this account's home is. */
function leave() {
  router.push({ name: homeRouteFor(auth.department) });
}

onMounted(() => {
  crm.loadOptions();
});
</script>

<template>
  <div class="min-h-screen md:flex md:gap-4 md:p-4" dir="rtl">
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
        <span class="w-9 h-9 rounded-2xl bg-panel text-white grid place-items-center shrink-0">
          <NavIcon name="team" :size="19" />
        </span>
        <div v-if="!collapsed" class="flex-1 min-w-0">
          <p class="font-bold text-sm text-ink leading-tight">CRM</p>
          <p class="text-[11px] text-slate-400 truncate">{{ roleLabel }}</p>
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
          v-for="item in nav"
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
          <span v-if="!collapsed" class="flex-1 text-right">خروج از CRM</span>
        </button>
      </div>
    </aside>

    <!-- ===== Content ===== -->
    <!-- `p-3 md:p-0` matches AppShell. Without it the CRM pages were the only
         ones on the platform whose cards ran edge to edge on a phone, with
         nothing between the text and the side of the screen. -->
    <div class="flex-1 min-w-0 p-3 md:p-0">
      <header class="bg-surface md:rounded-card md:shadow-soft px-3 sm:px-4 h-14 flex items-center gap-3 mb-4">
        <button
          class="md:hidden text-slate-500 p-1"
          aria-label="منو"
          @click="mobileOpen = true"
        ><NavIcon name="grid" :size="22" /></button>

        <h1 class="font-bold text-ink">{{ pageTitle }}</h1>

        <!-- Whose book. Three departments share these screens now, and a
             page of customers that does not say which file it is showing
             invites acting on the wrong one. -->
        <span
          v-if="crm.bookLabel"
          class="hidden sm:inline-flex items-center text-[11px] bg-slate-100
                 text-slate-500 rounded-full px-2.5 py-1 shrink-0"
        >{{ crm.bookLabel }}</span>

        <div class="flex-1"></div>

        <CrmSearch />
        <QuickAdd />
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

      <!-- An account in a sales department with no salesperson row behind it
           sees nothing, correctly. Without this it reads as a broken CRM and
           gets reported as one; with it, it names the fix. -->
      <p
        v-if="crm.unlinked"
        class="bg-amber-50 text-amber-800 text-sm rounded-xl px-4 py-3 mb-4"
      >
        این حساب هنوز به هیچ کارشناس فروشی وصل نشده است، بنابراین رکوردی برای
        نمایش ندارد. از مدیر فروش بخواهید حساب شما را به کارشناس مربوطه متصل کند.
      </p>

      <RouterView />
    </div>

    <DrillDrawer />
  </div>
</template>
