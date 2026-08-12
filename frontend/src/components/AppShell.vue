<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { usePresence } from "@/composables/usePresence";
import { useClickOutside } from "@/composables/useClickOutside";
import { socialApi } from "@/api/social";
import { inboxApi } from "@/api/platform";
import NavIcon from "@/components/NavIcon.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import NotificationBell from "@/components/NotificationBell.vue";
import ThemePicker from "@/components/ThemePicker.vue";
import DrillDrawer from "@/components/crm/DrillDrawer.vue";
import { useCrmStore } from "@/stores/crm";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

usePresence(); // keep me online

const collapsed = ref(false);
const mobileOpen = ref(false); // drawer state on phones
const inboxCount = ref(0);
const chatCount = ref(0);
// The avatar menu closes on any click elsewhere or Escape — mouseleave used
// to close it, which snapped it shut whenever the pointer merely drifted off.
const userMenu = ref(false);
const userMenuRoot = ref<HTMLElement | null>(null);
useClickOutside(userMenuRoot, () => (userMenu.value = false));
const search = ref("");

interface Item {
  name: string;
  label: string;
  icon: string;
  badge?: () => number;
  /**
   * A group rather than a link. The CEO oversees every channel, so their
   * sidebar had one row per dashboard and grew a little longer with each
   * section added; folding related destinations under one heading keeps the
   * top level to the handful of things they actually choose between.
   *
   * A group's `name` is a key, not a route — clicking it opens the group.
   */
  children?: Item[];
  /** Shown inside an empty group instead of a blank panel. */
  emptyHint?: string;
  /**
   * Named now, built later. Rendered muted with a «به‌زودی» tag and does not
   * navigate — a menu row that 404s is worse than one that says it is not
   * ready yet.
   */
  placeholder?: boolean;
}

/**
 * CRM ships as a locked demo: until its separate password is entered the
 * sidebar shows a single «دمو CRM» entry, and the real section only appears
 * afterwards. The list below is what unlocking reveals.
 */
const crmItems: Item[] = [
  { name: "crm-dashboard", label: "داشبورد CRM", icon: "grid" },
  { name: "crm-pipeline", label: "مراحل فروش", icon: "target" },
  { name: "crm-deals", label: "فرصت‌های فروش", icon: "box" },
  { name: "crm-customers", label: "مشتریان", icon: "team" },
  { name: "crm-activities", label: "فعالیت‌ها", icon: "notes" },
  { name: "crm-reports", label: "گزارش‌های CRM", icon: "chart" },
];

/**
 * بازرگانی داخلی. The same list serves the CEO (who reads it) and صدف جمالی
 * (who keys it) — the section is read-only for the CEO by permission, not by
 * a different menu, so there is one place to change when a page is added.
 */
// نمونه‌ها is deliberately absent: it is reached from درخواست و استعلام, where
// asking a supplier for one actually happens.
const commercialItems: Item[] = [
  { name: "commercial-dashboard", label: "داشبورد", icon: "grid" },
  { name: "commercial-materials", label: "کالاها", icon: "box" },
  { name: "commercial-suppliers", label: "تامین‌کنندگان", icon: "team" },
  { name: "commercial-requests", label: "درخواست و استعلام", icon: "target" },
  { name: "commercial-orders", label: "سفارش‌های خرید", icon: "notes" },
];

/**
 * بازرگانی خارجی. Its own group rather than more rows under one «بازرگانی»
 * heading: together the two halves are thirteen destinations, which is a
 * scroll rather than a menu, and the two are genuinely different jobs — one
 * is about price, the other about time.
 */
const foreignItems: Item[] = [
  { name: "foreign-dashboard", label: "داشبورد", icon: "grid" },
  { name: "foreign-workbench", label: "میز کار", icon: "inbox" },
  { name: "foreign-orders", label: "پرونده‌ها", icon: "notes" },
  { name: "foreign-shipments", label: "بار و گمرک", icon: "box" },
  { name: "foreign-payments", label: "پرداخت‌ها", icon: "chart" },
  { name: "foreign-history", label: "تاریخچه", icon: "target" },
];

/**
 * Detail pages keep their list row highlighted — landing on «پرونده کالا» from
 * a link would otherwise show a collapsed menu with nothing selected, and you
 * could not tell where you were.
 */
const CHILD_PARENT: Record<string, string> = {
  "commercial-material": "commercial-materials",
  "commercial-supplier": "commercial-suppliers",
  "commercial-request": "commercial-requests",
  // نمونه‌ها has no row of its own — it is reached from درخواست و استعلام,
  // which stays highlighted while you are in it.
  "commercial-samples": "commercial-requests",
  "foreign-order": "foreign-orders",
};

function childActive(name: string): boolean {
  const current = String(route.name ?? "");
  return current === name || CHILD_PARENT[current] === name;
}

const crm = useCrmStore();

/** Who even sees the demo entry. */
const showCrm = computed(
  () => auth.isExecutive || auth.department === "sales_team" || !!auth.me?.is_superuser,
);
const crmUnlocked = computed(() => crm.unlocked === true);

// Detail pages keep their list item highlighted.
const CRM_PARENT: Record<string, string> = {
  "crm-deal": "crm-deals",
  "crm-customer": "crm-customers",
};
function crmActive(name: string): boolean {
  const current = String(route.name ?? "");
  return current === name || CRM_PARENT[current] === name;
}

/** The CEO oversees every section, so «تیم من» would be the wrong word. */
const rosterLabel = computed(() => (auth.isExecutive ? "تیم فروش" : "تیم من"));

const primary = computed<Item[]>(() => {
  const items: Item[] = [];
  if (auth.isExecutive) {
    items.push(
      { name: "overview", label: "نمای کلی", icon: "grid" },
      {
        // The three channels are one decision — "which part of sales?" —
        // so they live under one heading instead of three top-level rows.
        name: "group-sales",
        label: "فروش",
        icon: "chart",
        children: [
          { name: "sales-dashboard", label: "فروش همکار", icon: "chart" },
          { name: "sales-org-dashboard", label: "فروش بانکی", icon: "chart" },
          { name: "sales-b2b-dashboard", label: "فروش B2B", icon: "chart" },
        ],
      },
      { name: "production-dashboard", label: "تولید", icon: "box" },
      // Three destinations, no working screens: the CEO reads this section
      // but files no ثبت سفارش and chases no container.
      {
        name: "group-commercial",
        label: "بازرگانی",
        icon: "box",
        children: [
          { name: "commercial-dashboard", label: "بازرگانی داخلی", icon: "grid" },
          { name: "foreign-dashboard", label: "بازرگانی خارجی", icon: "grid" },
          { name: "commercial-full-report", label: "گزارش کامل", icon: "chart" },
        ],
      },
      {
        name: "group-finance",
        label: "مالی",
        icon: "chart",
        // Read-only, like every other section the CEO oversees: entry belongs
        // to the department that owns the numbers. تسهیلات و قرض are not their
        // own row either — they are read on the نقدینگی page itself.
        children: [
          { name: "finance-cash-report", label: "نقدینگی", icon: "chart" },
        ],
      },
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
  } else if (auth.department === "finance") {
    items.push(
      { name: "finance-cash-entry", label: "ورود نقدینگی", icon: "box" },
      { name: "finance-cash-report", label: "گزارش نقدینگی", icon: "chart" },
      // The treasury averages: this manager's own tool, and not on the page
      // the CEO opens to read the company's position.
      { name: "finance-treasury", label: "تحلیل خزانه", icon: "target" },
    );
  } else if (auth.department === "commercial") {
    // Both halves, grouped: eleven rows at the top level would push پیام‌ها
    // and یادداشت‌ها off the first screen.
    //
    // No report rows here. This manager works the section rather than reading
    // it, and the داشبورد is already clickable — every figure on it opens the
    // rows it was counted from, which is what a separate report page was
    // being used for. The composed cross-section report belongs to the CEO.
    items.push(
      {
        name: "group-commercial",
        label: "بازرگانی داخلی",
        icon: "box",
        children: [...commercialItems],
      },
      {
        name: "group-commercial-foreign",
        label: "بازرگانی خارجی",
        icon: "box",
        children: [...foreignItems],
      },
    );
  }
  if (auth.me?.can_approve || auth.me?.is_superuser) {
    items.push({ name: "inbox", label: "کارتابل", icon: "inbox", badge: () => inboxCount.value });
  }
  // Each department manager keeps their own list of کارشناسان; the CEO sees all.
  if (auth.isExecutive || ["sales_team", "sales_org", "sales_b2b"].includes(auth.department)) {
    items.push({ name: "roster", label: rosterLabel.value, icon: "team" });
  }
  const collaboration: Item[] = [
    { name: "chat", label: "پیام‌ها", icon: "chat", badge: () => chatCount.value },
    { name: "notes", label: "یادداشت‌ها", icon: "notes" },
    { name: "team", label: "همکاران", icon: "team" },
  ];
  if (auth.isExecutive) {
    // The CEO's menu carries every section of the company, so these three
    // general rows are what pushes it past a screen. A department manager's
    // menu is short enough to keep them at the top level, where they are one
    // click instead of two.
    items.push({
      name: "group-collaboration",
      // «همکاری» named a value, not a place — nothing in the company is
      // filed under it. These three are the people side of the platform:
      // talking to someone, noting something about them, looking them up.
      label: "ارتباطات",
      icon: "chat",
      children: collaboration,
    });
  } else {
    items.push(...collaboration);
  }
  return items;
});


/**
 * Which sidebar groups are unfolded.
 *
 * A group holding the current page is always open — otherwise landing on
 * «فروش بانکی» from a link would show a collapsed menu with nothing
 * highlighted, and you could not tell where you were.
 */
const openGroups = ref<Set<string>>(new Set());

function groupHasActive(item: Item): boolean {
  return (item.children ?? []).some((c) => childActive(c.name));
}

function isGroupOpen(item: Item): boolean {
  return openGroups.value.has(item.name) || groupHasActive(item);
}

function toggleGroup(item: Item) {
  // On the icon-only rail there is nowhere to show children, so opening a
  // group widens the sidebar first rather than doing nothing visible.
  if (collapsed.value) {
    collapsed.value = false;
    openGroups.value = new Set([...openGroups.value, item.name]);
    return;
  }
  const next = new Set(openGroups.value);
  next.has(item.name) ? next.delete(item.name) : next.add(item.name);
  openGroups.value = next;
}

const pageTitle = computed(() => {
  const map: Record<string, string> = {
    overview: "نمای کلی", "sales-dashboard": "داشبورد فروش همکار",
    "sales-org-dashboard": "داشبورد فروش بانکی", "production-dashboard": "داشبورد تولید",
    "sales-b2b-dashboard": "داشبورد فروش B2B",
    inbox: "کارتابل تایید", chat: "پیام‌ها", notes: "یادداشت‌ها", team: "همکاران",
    "crm-dashboard": "داشبورد CRM", "crm-pipeline": "مراحل فروش",
    "crm-deals": "فرصت‌های فروش", "crm-deal": "پرونده فرصت فروش",
    "crm-customers": "مشتریان", "crm-customer": "پرونده مشتری",
    "crm-activities": "فعالیت‌ها و کارها", "crm-reports": "گزارش‌های CRM",
    "crm-unlock": "دمو CRM",
    "sales-entry": "ورود اطلاعات فروش همکار", "sales-org-entry": "ورود فروش بانکی",
    "sales-b2b-entry": "ورود فروش B2B",
    "finance-cash-report": "نقدینگی", "finance-cash-entry": "ورود اطلاعات نقدینگی",
    "production-entry": "ورود اطلاعات تولید", profile: "پروفایل",
    targets: "تعیین تارگت", settings: "تنظیمات سایت",
    "commercial-dashboard": "داشبورد بازرگانی داخلی",
    "commercial-materials": "کالاهای مصرفی", "commercial-material": "پرونده کالا",
    "commercial-suppliers": "تامین‌کنندگان", "commercial-supplier": "پرونده تامین‌کننده",
    "commercial-requests": "درخواست خرید و استعلام",
    "commercial-request": "مقایسه استعلام‌ها",
    "commercial-samples": "نمونه‌ها",
    "commercial-orders": "سفارش‌های خرید",
    "commercial-full-report": "گزارش کامل بازرگانی",
    "foreign-dashboard": "داشبورد بازرگانی خارجی",
    "foreign-workbench": "میز کار بازرگانی خارجی",
    "foreign-orders": "پرونده‌های واردات", "foreign-order": "پرونده واردات",
    "foreign-shipments": "بار و گمرک",
    "foreign-payments": "پرداخت‌ها و سود دیرکرد",
    "foreign-history": "تاریخچه واردات",
  };
  if (route.name === "roster") return rosterLabel.value;
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

function lockCrm() {
  crm.lock();
  if (String(route.name ?? "").startsWith("crm")) router.push({ name: "home" });
}
function logout() { auth.logout(); router.push({ name: "login" }); }

onMounted(() => {
  refreshBadges();
  window.setInterval(refreshBadges, 30_000);
  // Resolve the demo lock once, so a reload on any page shows the sidebar in
  // the state it is actually in rather than always starting locked.
  if (showCrm.value) crm.checkGate();
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
        <template v-for="it in primary" :key="it.name">
          <!-- ===== Group: a heading that folds its destinations away ===== -->
          <template v-if="it.children">
            <button
              class="w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm transition"
              :class="[
                groupHasActive(it) && !isGroupOpen(it)
                  ? 'bg-slate-100 text-ink'
                  : 'text-slate-500 hover:bg-slate-100',
                collapsed ? 'justify-center' : '',
              ]"
              :title="collapsed ? it.label : ''"
              :aria-expanded="isGroupOpen(it)"
              @click="toggleGroup(it)"
            >
              <NavIcon :name="it.icon" :size="20" />
              <template v-if="!collapsed">
                <span class="flex-1 text-right">{{ it.label }}</span>
                <NavIcon
                  name="chevron"
                  :size="15"
                  class="shrink-0 text-slate-300 transition-transform"
                  :class="isGroupOpen(it) ? '-rotate-90' : ''"
                />
              </template>
            </button>

            <div v-if="!collapsed && isGroupOpen(it)" class="mr-3 pr-3 border-r border-slate-100 space-y-1">
              <button
                v-for="child in it.children"
                :key="child.name"
                class="w-full flex items-center gap-3 rounded-2xl px-3 py-2 text-sm transition"
                :class="child.placeholder
                  ? 'text-slate-300 cursor-default'
                  : childActive(child.name)
                    ? 'bg-panel text-white'
                    : 'text-slate-500 hover:bg-slate-100'"
                :disabled="child.placeholder"
                :title="child.placeholder ? 'هنوز ساخته نشده است' : ''"
                @click="child.placeholder || go(child.name)"
              >
                <NavIcon :name="child.icon" :size="17" />
                <span class="flex-1 text-right">{{ child.label }}</span>
                <!-- These rows name a section that is agreed but not built.
                     Navigating would hit an undefined route, so they are inert
                     and say so rather than failing silently. -->
                <span
                  v-if="child.placeholder"
                  class="text-[10px] rounded-full bg-slate-100 text-slate-400 px-1.5 py-0.5 shrink-0"
                >به‌زودی</span>
              </button>
              <p v-if="!it.children.length" class="text-[11px] text-slate-300 px-3 py-2">
                {{ it.emptyHint }}
              </p>
            </div>
          </template>

          <!-- ===== Plain destination ===== -->
          <button
            v-else
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
        </template>

        <!-- CRM — one locked entry until the demo password is entered -->
        <template v-if="showCrm">
          <button
            v-if="!crmUnlocked"
            class="w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm transition mt-2"
            :class="[
              route.name === 'crm-unlock' ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100',
              collapsed ? 'justify-center' : '',
            ]"
            title="دمو CRM — رمز جداگانه دارد"
            @click="go('crm-unlock')"
          >
            <NavIcon name="chart" :size="20" />
            <template v-if="!collapsed">
              <span class="flex-1 text-right">دمو CRM</span>
              <svg class="w-3.5 h-3.5 opacity-50 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <rect x="3" y="11" width="18" height="11" rx="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
            </template>
          </button>

          <template v-else>
            <div class="pt-3 pb-1 px-3 flex items-center gap-2">
              <p v-if="!collapsed" class="text-[10px] font-semibold text-slate-300 tracking-wide flex-1">دمو CRM</p>
              <button
                v-if="!collapsed"
                class="text-[10px] text-slate-300 hover:text-red-500"
                title="بستن دمو"
                @click="lockCrm"
              >قفل</button>
              <div v-if="collapsed" class="h-px bg-slate-200 mx-1 flex-1"></div>
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
        <!-- Administrators only — a separate application area. -->
        <button
          v-if="auth.isAdminPanelUser"
          class="w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm text-slate-500 hover:bg-slate-100 transition"
          :class="collapsed ? 'justify-center' : ''"
          :title="collapsed ? 'پنل مدیریت' : ''"
          @click="go('admin-dashboard')"
        >
          <NavIcon name="shield" :size="20" />
          <span v-if="!collapsed" class="text-right flex-1">پنل مدیریت</span>
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
          <!-- One control for the whole look: skin + light/dark live together
               inside the palette, so there is no second sun/moon button. -->
          <ThemePicker />
          <NotificationBell />
          <div ref="userMenuRoot" class="relative">
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
      <DrillDrawer v-if="crmUnlocked" />

      <!-- Footer -->
      <footer class="text-center text-xs text-slate-400 py-3">
        شرکت کاغذ حساس نمابر مهر · طراحی و توسعه: <span class="font-medium text-slate-500">فاضل حافظی</span>
      </footer>
    </div>
  </div>
</template>