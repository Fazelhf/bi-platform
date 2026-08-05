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
    // Two ways in that don't need the password — both end in a signed-in
    // session, so the guard below treats them exactly like /login.
    {
      path: "/login-otp",
      name: "login-otp",
      component: () => import("@/views/OtpLoginView.vue"),
    },
    {
      path: "/forgot-password",
      name: "forgot-password",
      component: () => import("@/views/ForgotPasswordView.vue"),
    },
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
          component: () => import("@/views/SalesDashboardView.vue"),
          meta: { salesChannel: "team" },
          props: { channel: "team", title: "داشبورد فروش همکار" },
        },
        {
          path: "sales-org",
          name: "sales-org-dashboard",
          component: () => import("@/views/SalesDashboardView.vue"),
          meta: { salesChannel: "organizational" },
          props: { channel: "organizational", title: "داشبورد فروش بانکی" },
        },
        {
          path: "sales-b2b",
          name: "sales-b2b-dashboard",
          component: () => import("@/views/SalesDashboardView.vue"),
          meta: { salesChannel: "b2b" },
          props: { channel: "b2b", title: "داشبورد فروش B2B" },
        },
        {
          path: "production",
          name: "production-dashboard",
          component: () => import("@/views/ProductionDashboardView.vue"),
        },
        {
          // Targets are the CEO's to set; managers only ever read them.
          path: "targets",
          name: "targets",
          component: () => import("@/views/TargetsView.vue"),
          meta: { executive: true },
        },

        // --- CRM (فروش همکار) — locked demo ---
        // Everything under /crm needs the demo password. `meta.crm` marks the
        // pages the guard protects; the API enforces the same lock, so this
        // is convenience, not the security boundary.
        {
          path: "crm/unlock",
          name: "crm-unlock",
          component: () => import("@/views/crm/CrmLockView.vue"),
        },
        {
          path: "crm",
          name: "crm-dashboard",
          component: () => import("@/views/crm/CrmDashboardView.vue"),
          meta: { crm: true },
        },
        {
          path: "crm/pipeline",
          name: "crm-pipeline",
          component: () => import("@/views/crm/PipelineView.vue"),
          meta: { crm: true },
        },
        {
          path: "crm/deals",
          name: "crm-deals",
          component: () => import("@/views/crm/DealsView.vue"),
          meta: { crm: true },
        },
        {
          path: "crm/deals/:id",
          name: "crm-deal",
          component: () => import("@/views/crm/DealDetailView.vue"),
          meta: { crm: true },
        },
        {
          path: "crm/customers",
          name: "crm-customers",
          component: () => import("@/views/crm/CustomersView.vue"),
          meta: { crm: true },
        },
        {
          path: "crm/customers/:id",
          name: "crm-customer",
          component: () => import("@/views/crm/CustomerDetailView.vue"),
          meta: { crm: true },
        },
        {
          path: "crm/activities",
          name: "crm-activities",
          component: () => import("@/views/crm/ActivitiesView.vue"),
          meta: { crm: true },
        },
        {
          path: "crm/reports",
          name: "crm-reports",
          component: () => import("@/views/crm/CrmReportsView.vue"),
          meta: { crm: true },
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

        // --- منابع انسانی: each department's own roster ---
        {
          path: "roster",
          name: "roster",
          component: () => import("@/views/RosterView.vue"),
          meta: { roster: true },
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
        // Everyone's own account security (two-step login) — not the admin panel.
        { path: "security", name: "security", component: () => import("@/views/SecurityView.vue") },
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

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (to.meta.requiresAuth && !auth.isAuthenticated) return { name: "login" };
  const signedOutOnly = ["login", "login-otp", "forgot-password"];
  if (signedOutOnly.includes(String(to.name)) && auth.isAuthenticated) {
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
  // A sales channel belongs to the department that owns it. The sidebar
  // already only offered your own, but the URL was still reachable — and the
  // API now refuses, so without this the page would just show an error.
  const salesChannel = to.meta.salesChannel as string | undefined;
  if (salesChannel && !auth.isExecutive && !auth.me?.is_superuser) {
    const owner = { team: "sales_team", organizational: "sales_org", b2b: "sales_b2b" }[salesChannel];
    if (auth.department !== owner) return { name: homeRouteFor(auth.department) };
  }
  // Roster: department managers (their own section) and the CEO.
  if (to.meta.roster) {
    const canRoster =
      auth.isExecutive ||
      !!auth.me?.is_superuser ||
      ["sales_team", "sales_org", "sales_b2b"].includes(auth.department);
    if (!canRoster) return { name: homeRouteFor(auth.department) };
  }
  // CRM demo: locked until its own password is entered. `next` is carried so
  // a deep link (a drill-down URL someone was sent) survives the prompt.
  if (to.meta.crm) {
    const { useCrmStore } = await import("@/stores/crm");
    if (!(await useCrmStore().checkGate())) {
      return { name: "crm-unlock", query: { next: to.fullPath } };
    }
  }
});

export default router;
