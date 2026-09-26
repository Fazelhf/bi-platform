<script setup lang="ts">
/**
 * فروش ۲'s own workspace, shaped like CRM's: a rail on the right with every
 * page of the module, content beside it, and one fixed way out.
 *
 * Separate from AppShell for the reason CRM is: the work here is a sequence
 * of documents (پیش‌فاکتور → فاکتور → حواله → دریافت), and the platform's
 * sidebar of dashboards only gets in its way. Admins only for now — the
 * route guard and the API (apps.sales2.permissions) both say so.
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

const collapsed = ref(localStorage.getItem("sales2RailCollapsed") === "1");
const mobileOpen = ref(false);

/** The documents in the order a sale produces them, then the files they draw on. */
const NAV = [
  { name: "sales2-dashboard", label: "داشبورد", icon: "activity" },
  { name: "sales2-proformas", label: "پیش‌فاکتورها", icon: "clipboard" },
  { name: "sales2-invoices", label: "فاکتورهای فروش", icon: "file" },
  { name: "sales2-returns", label: "مرجوعی‌ها", icon: "refresh" },
  { name: "sales2-deliveries", label: "حواله‌های خروج", icon: "truck" },
  { name: "sales2-receipts", label: "دریافت و چک", icon: "banknote" },
  { name: "sales2-receivables", label: "مطالبات", icon: "wallet" },
  { name: "sales2-customers", label: "مشتریان و اعتبار", icon: "contact" },
  { name: "sales2-price-list", label: "لیست قیمت", icon: "tag" },
  { name: "sales2-products", label: "کالاها و فی حسابداری", icon: "box" },
  { name: "sales2-sales-list", label: "لیست فروش", icon: "layers" },
  { name: "sales2-commission", label: "پورسانت", icon: "target" },
  { name: "sales2-settings", label: "تنظیمات", icon: "settings" },
];

const DOC_LIST: Record<string, string> = {
  proforma: "sales2-proformas", invoice: "sales2-invoices", return: "sales2-returns",
};

/** A detail page keeps its list row lit, so you can tell where you are. */
function active(name: string): boolean {
  const current = String(route.name ?? "");
  if (current === "sales2-document" || current === "sales2-document-new") {
    const kind = String(route.query.kind ?? route.params.kind ?? "invoice");
    return name === (DOC_LIST[kind] ?? "sales2-invoices");
  }
  if (current === "sales2-customer") return name === "sales2-customers";
  return current === name;
}

const pageTitle = computed(() => {
  if (route.name === "sales2-document-new") return "سند جدید";
  if (route.name === "sales2-document") return "سند فروش";
  if (route.name === "sales2-customer") return "پرونده مشتری";
  return NAV.find((n) => active(n.name))?.label ?? "فروش ۲";
});

const userMenu = ref(false);
const userMenuRoot = ref<HTMLElement | null>(null);
useClickOutside(userMenuRoot, () => (userMenu.value = false));

function toggleRail() {
  collapsed.value = !collapsed.value;
  localStorage.setItem("sales2RailCollapsed", collapsed.value ? "1" : "0");
}

function go(name: string) {
  router.push({ name });
  mobileOpen.value = false;
}

function leave() {
  router.push({ name: homeRouteFor(auth.department) });
}
</script>

<template>
  <div class="min-h-screen md:flex md:gap-4 md:p-4" dir="rtl">
    <div v-if="mobileOpen" class="fixed inset-0 bg-black/40 z-40 md:hidden" @click="mobileOpen = false"></div>

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
          <NavIcon name="briefcase" :size="19" />
        </span>
        <div v-if="!collapsed" class="flex-1 min-w-0">
          <p class="font-bold text-sm text-ink leading-tight">فروش ۲</p>
          <p class="text-[11px] text-slate-400 truncate">پیش‌فاکتور تا دریافت</p>
        </div>
        <button v-if="!collapsed" class="text-slate-400 hover:text-ink hidden md:block" aria-label="جمع کردن منو" @click="toggleRail">
          <NavIcon name="chevron" :size="18" />
        </button>
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

      <div class="p-3 border-t border-slate-100">
        <button
          class="w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm text-slate-500 hover:bg-slate-100 transition"
          :class="collapsed ? 'justify-center' : ''"
          title="بازگشت به بقیه‌ی سامانه"
          @click="leave"
        >
          <NavIcon name="chevron" :size="20" />
          <span v-if="!collapsed" class="flex-1 text-right">خروج از فروش ۲</span>
        </button>
      </div>
    </aside>

    <!-- ===== Content ===== -->
    <div class="flex-1 min-w-0 p-3 md:p-0">
      <header class="bg-surface md:rounded-card md:shadow-soft px-3 sm:px-4 h-14 flex items-center gap-3 mb-4">
        <button class="md:hidden text-slate-500 p-1" aria-label="منو" @click="mobileOpen = true">
          <NavIcon name="grid" :size="22" />
        </button>
        <h1 class="font-bold text-ink">{{ pageTitle }}</h1>
        <span class="hidden sm:inline-flex items-center text-[11px] bg-amber-50 text-amber-700 rounded-full px-2.5 py-1 shrink-0">
          آزمایشی · فقط مدیر سامانه
        </span>
        <div class="flex-1"></div>
        <ThemePicker />
        <NotificationBell />
        <div ref="userMenuRoot" class="relative shrink-0">
          <button class="flex items-center" @click="userMenu = !userMenu">
            <UserAvatar :user="auth.me" :size="34" />
          </button>
          <div
            v-if="userMenu"
            class="absolute left-0 mt-2 w-52 bg-surface rounded-2xl shadow-pop border border-slate-100 p-1.5 z-50"
          >
            <p class="px-3 py-2 text-xs text-slate-400 truncate">{{ auth.me?.display_name_fa || auth.me?.username }}</p>
            <button class="w-full text-right px-3 py-2 text-sm rounded-xl hover:bg-slate-100" @click="userMenu = false; leave()">
              بازگشت به سامانه
            </button>
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
