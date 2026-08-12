<script setup lang="ts">
/**
 * CRM's own workspace, deliberately not the business app's AppShell.
 *
 * Two reasons it is separate. The audience is different — a salesperson lives
 * here all day and never opens تولید or نقدینگی — and so is the shape of the
 * work: CRM is six places you move between constantly, not twenty sections
 * you pick one of. A vertical rail is right for a menu you scan; a row of
 * tabs is right for places you switch between, which is why this one runs
 * along the top and the page below gets the whole width.
 *
 * «خروج از CRM» is always in the same corner. Entering a workspace that has
 * no obvious way out is how a tool starts feeling like a trap.
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
import DrillDrawer from "@/components/crm/DrillDrawer.vue";

const auth = useAuthStore();
const crm = useCrmStore();
const route = useRoute();
const router = useRouter();

usePresence();

/**
 * Plain words, and the ones this company already uses.
 *
 * The data came out of دیدار, where the team has been saying «معامله»,
 * «کاریز» and «پیگیری» for years. Renaming those to «فرصت فروش» or «قیف» here
 * would be a vocabulary they have to translate on every screen.
 */
const TABS = [
  { name: "crm-home", label: "میز کار", icon: "inbox" },
  { name: "crm-customers", label: "مشتری‌ها", icon: "team" },
  { name: "crm-deals", label: "معامله‌ها", icon: "box" },
  { name: "crm-pipeline", label: "کاریز فروش", icon: "target" },
  { name: "crm-activities", label: "پیگیری‌ها", icon: "notes" },
  { name: "crm-dashboard", label: "آمار", icon: "grid" },
  { name: "crm-reports", label: "گزارش‌ها", icon: "chart" },
];

/** A detail page keeps its own tab lit, so you can tell where you are. */
const PARENT: Record<string, string> = {
  "crm-deal": "crm-deals",
  "crm-customer": "crm-customers",
};

function active(name: string): boolean {
  const current = String(route.name ?? "");
  return current === name || PARENT[current] === name;
}

const userMenu = ref(false);
const userMenuRoot = ref<HTMLElement | null>(null);
useClickOutside(userMenuRoot, () => (userMenu.value = false));

function go(name: string) {
  router.push({ name });
}

/** Back to the rest of the platform, at whatever this account's home is. */
function leave() {
  router.push({ name: homeRouteFor(auth.department) });
}

const title = computed(
  () => TABS.find((t) => active(t.name))?.label ?? "CRM",
);

onMounted(() => {
  crm.loadOptions();
});
</script>

<template>
  <div class="min-h-screen bg-canvas" dir="rtl">
    <!-- ===== Top bar ===== -->
    <header class="bg-panel text-white sticky top-0 z-40">
      <div class="px-3 sm:px-5 h-14 flex items-center gap-3">
        <button
          class="flex items-center gap-2.5 shrink-0 hover:opacity-90"
          title="میز کار"
          @click="go('crm-home')"
        >
          <span class="w-9 h-9 rounded-2xl bg-white/10 grid place-items-center">
            <NavIcon name="team" :size="19" />
          </span>
          <span class="hidden sm:block text-right leading-tight">
            <span class="block font-bold text-sm">CRM</span>
            <span class="block text-[11px] text-white/50">مشتریان و فروش</span>
          </span>
        </button>

        <div class="flex-1"></div>

        <ThemePicker />

        <button
          class="flex items-center gap-1.5 text-xs text-white/70 hover:text-white
                 bg-white/10 hover:bg-white/15 rounded-xl px-3 py-2 transition-colors"
          title="بازگشت به بقیه‌ی سامانه"
          @click="leave"
        >
          <NavIcon name="chevron" :size="16" />
          <span class="hidden sm:inline">خروج از CRM</span>
        </button>

        <div ref="userMenuRoot" class="relative shrink-0">
          <button class="flex items-center gap-2" @click="userMenu = !userMenu">
            <UserAvatar :user="auth.me" :size="34" />
          </button>
          <div
            v-if="userMenu"
            class="absolute left-0 mt-2 w-52 bg-surface text-ink rounded-2xl shadow-pop
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

      <!-- Tabs. They scroll sideways on a phone rather than wrapping into a
           second row that pushes the page down. -->
      <nav class="px-2 sm:px-4 flex gap-1 overflow-x-auto no-scrollbar">
        <button
          v-for="t in TABS"
          :key="t.name"
          class="shrink-0 flex items-center gap-2 px-3.5 py-2.5 text-sm rounded-t-xl
                 transition-colors border-b-2"
          :class="active(t.name)
            ? 'bg-canvas text-ink font-medium border-transparent'
            : 'text-white/60 hover:text-white border-transparent hover:bg-white/5'"
          @click="go(t.name)"
        >
          <NavIcon :name="t.icon" :size="17" />
          {{ t.label }}
        </button>
      </nav>
    </header>

    <main class="p-3 sm:p-5 max-w-[1400px] mx-auto">
      <h1 class="sr-only">{{ title }}</h1>
      <RouterView />
    </main>

    <DrillDrawer />
  </div>
</template>

<style scoped>
.no-scrollbar::-webkit-scrollbar { display: none; }
.no-scrollbar { scrollbar-width: none; }
</style>
