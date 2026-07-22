import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "@/stores/auth";

/** Where a user lands after login, by department (CEO → overview). */
export function homeRouteFor(department: string): string {
  switch (department) {
    case "production":
      return "production-entry";
    case "sales_org":
      return "sales-org-entry";
    case "sales_team":
      return "sales-entry";
    case "sales_b2b":
      return "sales-b2b-entry";
    default:
      return "overview"; // CEO / admin
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: () => import("@/views/LoginView.vue") },
    {
      path: "/",
      component: () => import("@/components/AppShell.vue"),
      meta: { requiresAuth: true },
      children: [
        {
          // Dynamic home: CEO -> overview, each manager -> their entry page.
          path: "",
          name: "home",
          redirect: () => ({ name: homeRouteFor(useAuthStore().department) }),
        },

        // --- CEO dashboards (read-only) ---
        {
          path: "overview",
          name: "overview",
          component: () => import("@/views/OverviewView.vue"),
          meta: { executive: true }, // company-wide view — CEO/admin only
        },
        {
          path: "sales",
          name: "sales-dashboard",
          component: () => import("@/views/DashboardView.vue"),
          props: { channel: "team", title: "داشبورد فروش همکار" },
        },
        {
          path: "sales-org",
          name: "sales-org-dashboard",
          component: () => import("@/views/DashboardView.vue"),
          props: { channel: "organizational", title: "داشبورد فروش بانکی" },
        },
        {
          path: "sales-b2b",
          name: "sales-b2b-dashboard",
          component: () => import("@/views/DashboardView.vue"),
          props: { channel: "b2b", title: "داشبورد فروش B2B" },
        },
        {
          path: "production",
          name: "production-dashboard",
          component: () => import("@/views/ProductionDashboardView.vue"),
        },

        // --- Department manager entry (department-guarded) ---
        {
          path: "sales/entry",
          name: "sales-entry",
          component: () => import("@/views/SalesInputView.vue"),
          props: { channel: "team", title: "ورود اطلاعات فروش همکار" },
          meta: { department: "sales_team" },
        },
        {
          path: "sales-org/entry",
          name: "sales-org-entry",
          component: () => import("@/views/SalesInputView.vue"),
          props: { channel: "organizational", title: "ورود اطلاعات فروش بانکی" },
          meta: { department: "sales_org" },
        },
        {
          path: "sales-b2b/entry",
          name: "sales-b2b-entry",
          component: () => import("@/views/SalesInputView.vue"),
          props: { channel: "b2b", title: "ورود اطلاعات فروش B2B" },
          meta: { department: "sales_b2b" },
        },
        {
          path: "production/entry",
          name: "production-entry",
          component: () => import("@/views/ProductionInputView.vue"),
          meta: { department: "production" },
        },

        // --- Approval inbox (کارتابل) — anyone who can approve ---
        {
          path: "inbox",
          name: "inbox",
          component: () => import("@/views/InboxView.vue"),
          meta: { approver: true },
        },

        // --- Collaboration: chat, notes, team, profiles ---
        { path: "chat", name: "chat", component: () => import("@/views/ChatView.vue") },
        { path: "notes", name: "notes", component: () => import("@/views/NotesView.vue") },
        { path: "team", name: "team", component: () => import("@/views/TeamView.vue") },
        { path: "profile", name: "profile-me", component: () => import("@/views/ProfileView.vue") },
        { path: "profile/:id", name: "profile", component: () => import("@/views/ProfileView.vue") },

        // --- Site settings (users, base data, formulas, audit) — admin + CEO ---
        {
          path: "settings",
          name: "settings",
          component: () => import("@/views/admin/SettingsView.vue"),
          meta: { executive: true },
        },
      ],
    },
  ],
});

router.beforeEach((to) => {
  const auth = useAuthStore();
  if (to.meta.requiresAuth && !auth.isAuthenticated) return { name: "login" };
  if (to.name === "login" && auth.isAuthenticated) {
    return { name: homeRouteFor(auth.department) };
  }
  // Entry pages are department-scoped; keep others out.
  const dept = to.meta.department as string | undefined;
  if (dept && !auth.me?.is_superuser && auth.department !== dept) {
    return { name: homeRouteFor(auth.department) };
  }
  // Admin panel: executives/superusers only.
  if (to.meta.executive && !auth.isExecutive) {
    return { name: homeRouteFor(auth.department) };
  }
  // Inbox: approvers only.
  if (to.meta.approver && !auth.me?.can_approve && !auth.me?.is_superuser) {
    return { name: homeRouteFor(auth.department) };
  }
});

export default router;
