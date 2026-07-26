<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";
import { usePresence } from "@/composables/usePresence";
import { socialApi } from "@/api/social";
import { inboxApi } from "@/api/platform";
import NavIcon from "@/components/NavIcon.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import NotificationBell from "@/components/NotificationBell.vue";
import DrillDrawer from "@/components/crm/DrillDrawer.vue";

const auth = useAuthStore();
const ui = useUiStore();
const route = useRoute();
const router = useRouter();

usePresence(); // keep me online

const collapsed = ref(false);
const mobileOpen = ref(false); // drawer state on phones
const inboxCount = ref(0);
const chatCount = ref(0);
const userMenu = ref(false);
const search = ref("");

interface Item { name: string; label: string; icon: string; badge?: () => number }

/**
 * CRM section — visible to the CEO and to the sales_team department, since
 * فروش همکار is the only channel it covers today.
 */
const crmItems: Item[] = [
  { name: "crm-dashboard", label: "داشبورد CRM", icon: "grid" },
  { name: "crm-pipeline", label: "مراحل فروش", icon: "target" },
  { name: "crm-deals", label: "معاملات", icon: "box" },
  { name: "crm-customers", label: "مشتریان", icon: "team" },
  { name: "crm-activities", label: "فعالیت‌ها", icon: "notes" },
  { name: "crm-reports", label: "گزارش‌های CRM", icon: "chart" },
];

const showCrm = computed(
  () => auth.isExecutive || auth.department === "sales_team" || !!auth.me?.is_superuser,
);

// Detail pages keep their list item highlighted.
const CRM_PARENT: Record<string, string> = {
  "crm-deal": "crm-deals",
  "crm-customer": "crm-customers",
};
function crmActive(name: string): boolean {
  const current = String(route.name ?? "");
  return current === name || CRM_PARENT[current] === name;
}

const primary = computed<Item[]>(() => {
  const items: Item[] = [];
  if (auth.isExecutive) {
    items.push(
      { name: "overview", label: "نمای کلی", icon: "grid" },
      { name: "sales-dashboard", label: "فروش همکار", icon: "chart" },
      { name: "sales-org-dashboard", label: "فروش بانکی", icon: "chart" },
      { name: "sales-b2b-dashboard", label: "فروش B2B", icon: "chart" },
      { name: "production-dashboard", label: "تولید", icon: "box" },
      { name: "targets", label: "تارگت", icon: "target" },
    );
  } else if (auth.department === "production") {
    items.push(
      { name: "production-entry", label: "ورود تولید", icon: "box" },
      { name: "production-dashboard", label: "داشبورد تولید", icon: "chart" },
    );
  } else if (auth.department === "sales_org") {
    items.push(
      { name: "sales-org-entry", label: "ورود فروش بانکی", icon: "box" },
      { name: "sales-org-dashboard", label: "داشبورد فروش بانکی", icon: "chart" },
    );
  } else if (auth.department === "sales_team") {
    items.push(
      { name: "sales-entry", label: "ورود فروش همکار", icon: "box" },
      { name: "sales-dashboard", label: "داشبورد فروش همکار", icon: "chart" },
    );
  } else if (auth.department === "sales_b2b") {
    items.push(
      { name: "sales-b2b-entry", label: "ورود فروش B2B", icon: "box" },
      { name: "sales-b2b-dashboard", label: "داشبورد فروش B2B", icon: "chart" },
    );
  }
  if (auth.me?.can_approve || auth.me?.is_superuser) {
    items.push({ name: "inbox", label: "کارتابل", icon: "inbox", badge: () => inboxCount.value });
  }
  items.push(
    { name: "chat", label: "پیام‌ها", icon: "chat", badge: () => chatCount.value },
    { name: "notes", label: "یادداشت‌ها", icon: "notes" },
    { name: "team", label: "تیم", icon: "team" },
  );
  return items;
});


const pageTitle = computed(() => {
  const map: Record<string, string> = {
    overview: "نمای کلی", "sales-dashboard": "داشبورد فروش همکار",
    "sales-org-dashboard": "داشبورد فروش بانکی", "production-dashboard": "داشبورد تولید",
    "sales-b2b-dashboard": "داشبورد فروش B2B",
    inbox: "کارتابل تایید", chat: "پیام‌ها", notes: "یادداشت‌ها", team: "تیم",
    "crm-dashboard": "داشبورد CRM", "crm-pipeline": "مراحل فروش",
    "crm-deals": "معاملات", "crm-deal": "پرونده معامله",
    "crm-customers": "مشتریان", "crm-customer": "پرونده مشتری",
    "crm-activities": "فعالیت‌ها و کارها", "crm-reports": "گزارش‌های CRM",
    "sales-entry": "ورود اطلاعات فروش همکار", "sales-org-entry": "ورود فروش بانکی",
    "sales-b2b-entry": "ورود فروش B2B",
    "production-entry": "ورود اطلاعات تولید", profile: "پروفایل",
    targets: "تعیین تارگت", settings: "تنظیمات سایت",
  };
  return map[route.name as string] ?? "شرکت کاغذ حساس نمابر مهر";
});

const today = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  day: "numeric", month: "long", year: "numeric",
}).format(new Date());

async function refreshBadges() {
  try {
    if (auth.me?.can_approve || auth.me?.is_superuser) {
      const [s, p] = await Promise.all([inboxApi.pendingSales(), inboxApi.pendingProduction()]);
      inboxCount.value = s.length + p.length;
    }
    chatCount.value = (await socialApi.unreadMessages()).total;
  } catch { /* ignore */ }
}

function go(name: string) { router.push({ name }); mobileOpen.value = false; }
function logout() { auth.logout(); router.push({ name: "login" }); }

onMounted(() => {
  refreshBadges();
  window.setInterval(refreshBadges, 30_000);
});
</script>

<template>
  <div class="min-h-screen md:flex md:gap-4 md:p-4" dir="rtl">
    <!-- Mobile backdrop -->
    <div
      v-if="mobileOpen"
      class="fixed inset-0 bg-black/40 z-40 md:hidden"
      @click="mobileOpen = false"
    ></div>

    <!-- ============ Sidebar (right in RTL) ============ -->
    <aside
      class="bg-surface shadow-soft flex flex-col shrink-0 transition-transform duration-200
             fixed inset-y-0 right-0 z-50 w-64 rounded-none h-screen
             md:sticky md:top-4 md:z-auto md:rounded-card md:h-[calc(100vh-2rem)]"
      :class="[
        collapsed ? 'md:w-[76px]' : 'md:w-64',
        mobileOpen ? 'translate-x-0' : 'translate-x-full md:translate-x-0',
      ]"
    >
      <!-- Logo + collapse -->
      <div class="flex items-center gap-3 p-4" :class="collapsed ? 'justify-center' : ''">
        <img src="/apple-touch-icon.png" alt="لوگوی شرکت" class="w-10 h-10 rounded-2xl shrink-0" />
        <span v-if="!collapsed" class="font-bold text-ink flex-1">کاغذ حساس نمابر مهر</span>
        <button
          v-if="!collapsed"
          class="text-slate-400 hover:text-ink"
          @click="collapsed = true"
        ><NavIcon name="chevron" :size="18" /></button>
      </div>
      <button
        v-if="collapsed"
        class="mx-auto mb-2 text-slate-400 hover:text-ink rotate-180"
        @click="collapsed = false"
      ><NavIcon name="chevron" :size="18" /></button>

      <!-- Nav -->
      <nav class="flex-1 overflow-y-auto px-3 space-y-1">
        <button
          v-for="it in primary"
          :key="it.name"
          class="w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm transition group relative"
          :class="[
            route.name === it.name ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100',
            collapsed ? 'justify-center' : '',
          ]"
          :title="collapsed ? it.label : ''"
          @click="go(it.name)"
        >
          <NavIcon :name="it.icon" :size="20" />
          <span v-if="!collapsed" class="flex-1 text-right">{{ it.label }}</span>
          <span
            v-if="it.badge && it.badge()"
            class="text-[11px] font-bold rounded-full min-w-[20px] h-5 px-1.5 leading-5 text-center"
            :class="route.name === it.name ? 'bg-white/20' : 'bg-slate-200 text-slate-600'"
          >{{ it.badge() }}</span>
        </button>

        <!-- CRM section -->
        <template v-if="showCrm">
          <div class="pt-3 pb-1 px-3">
            <p v-if="!collapsed" class="text-[10px] font-semibold text-slate-300 tracking-wide">CRM · فروش همکار</p>
            <div v-else class="h-px bg-slate-200 mx-1"></div>
          </div>
          <button
            v-for="it in crmItems"
            :key="it.name"
            class="w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm transition"
            :class="[
              crmActive(it.name) ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100',
              collapsed ? 'justify-center' : '',
            ]"
            :title="collapsed ? it.label : ''"
            @click="go(it.name)"
          >
            <NavIcon :name="it.icon" :size="20" />
            <span v-if="!collapsed" class="flex-1 text-right">{{ it.label }}</span>
          </button>
        </template>
      </nav>

      <!-- Bottom: profile, settings (admin+CEO only), logout -->
      <div class="p-3 border-t border-slate-100 space-y-1">
        <button
          class="w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm text-slate-500 hover:bg-slate-100"
          :class="collapsed ? 'justify-center' : ''"
          @click="go('profile-me')"
        >
          <NavIcon name="team" :size="20" />
          <span v-if="!collapsed" class="text-right flex-1">پروفایل من</span>
        </button>
        <button
          v-if="auth.isExecutive"
          class="w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm transition"
          :class="[
            route.name === 'settings' ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100',
            collapsed ? 'justify-center' : '',
          ]"
          :title="collapsed ? 'تنظیمات سایت' : ''"
          @click="go('settings')"
        >
          <NavIcon name="settings" :size="20" />
          <span v-if="!collapsed" class="text-right flex-1">تنظیمات سایت</span>
        </button>
        <button
          class="w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm text-red-500 hover:bg-red-50"
          :class="collapsed ? 'justify-center' : ''"
          @click="logout"
        >
          <NavIcon name="logout" :size="20" />
          <span v-if="!collapsed" class="text-right flex-1">خروج</span>
        </button>
      </div>
    </aside>

    <!-- ============ Main ============ -->
    <div class="flex-1 min-w-0 flex flex-col gap-4 p-3 md:p-0">
      <!-- Topbar -->
      <header class="bg-surface rounded-card shadow-soft px-4 md:px-5 py-3 flex items-center justify-between gap-2">
        <!-- Title (right) + hamburger -->
        <div class="flex items-center gap-2 min-w-0">
          <button
            class="md:hidden text-slate-500 hover:text-ink shrink-0 -mr-1 p-1"
            aria-label="منو"
            @click="mobileOpen = true"
          ><NavIcon name="grid" :size="22" /></button>
          <h1 class="font-bold text-ink truncate">{{ pageTitle }}</h1>
          <span class="text-slate-300 hidden sm:inline">|</span>
          <span class="text-xs text-slate-400 hidden sm:inline">{{ today }}</span>
        </div>

        <!-- Actions (left) -->
        <div class="flex items-center gap-2 md:gap-3 shrink-0">
          <div class="hidden lg:flex items-center gap-2 bg-slate-100 rounded-full px-3 py-1.5 text-sm text-slate-500">
            <NavIcon name="search" :size="16" />
            <input v-model="search" placeholder="جستجو" class="bg-transparent outline-none w-32 text-ink" />
          </div>
          <button
            class="p-2 rounded-full hover:bg-slate-100 text-slate-500 hover:text-ink transition-colors no-print"
            :title="ui.dark ? 'حالت روشن' : 'حالت شب'"
            :aria-label="ui.dark ? 'حالت روشن' : 'حالت شب'"
            @click="ui.toggleDark()"
          >
            <!-- sun when dark (click → go light), moon when light -->
            <svg
              v-if="ui.dark" class="w-5 h-5" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
            >
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
            </svg>
            <svg
              v-else class="w-5 h-5" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
            >
              <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
            </svg>
          </button>
          <NotificationBell />
          <div class="relative">
            <button class="flex items-center gap-2" @click="userMenu = !userMenu">
              <UserAvatar
                :name="auth.me?.display_name_fa"
                :initials="auth.me?.initials"
                :color="auth.me?.avatar_color"
                :image="auth.me?.avatar_image"
                :online="true"
                :size="38"
              />
            </button>
            <div
              v-if="userMenu"
              class="absolute left-0 mt-2 w-48 bg-surface rounded-2xl shadow-pop border border-slate-100 p-2 z-50 animate-pop"
              @mouseleave="userMenu = false"
            >
              <div class="px-3 py-2">
                <p class="text-sm font-semibold text-ink">{{ auth.username }}</p>
                <p class="text-xs text-slate-400">{{ auth.me?.job_title_fa }}</p>
              </div>
              <div class="h-px bg-slate-100 my-1"></div>
              <button class="w-full text-right text-sm px-3 py-2 rounded-lg hover:bg-slate-100" @click="go('profile-me'); userMenu = false">پروفایل من</button>
              <button class="w-full text-right text-sm px-3 py-2 rounded-lg text-red-500 hover:bg-red-50" @click="logout">خروج</button>
            </div>
          </div>
        </div>
      </header>

      <!-- Page content -->
      <main class="flex-1 min-w-0">
        <RouterView />
      </main>

      <!-- CRM drill-down panel — mounted once, opened from any CRM page -->
      <DrillDrawer v-if="showCrm" />

      <!-- Footer -->
      <footer class="text-center text-xs text-slate-400 py-3">
        شرکت کاغذ حساس نمابر مهر · طراحی و توسعه: <span class="font-medium text-slate-500">فاضل حافظی</span>
      </footer>
    </div>
  </div>
</template>
