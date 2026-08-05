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
    case "finance":
      return "finance-cash-entry";
    case "commercial":
      return "commercial-dashboard";
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

        // --- مالی: cash in / cash out, and the credit behind some of it ---
        {
          path: "finance/cash",
          name: "finance-cash-report",
          component: () => import("@/views/finance/CashReportView.vue"),
          meta: { finance: true },
        },
        {
          path: "finance/entry",
          name: "finance-cash-entry",
          component: () => import("@/views/finance/CashEntryView.vue"),
          meta: { finance: true },
        },

        // --- بازرگانی داخلی: buying the factory's consumables ---
        {
          path: "commercial",
          name: "commercial-dashboard",
          component: () => import("@/views/commercial/CommercialDashboardView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/materials",
          name: "commercial-materials",
          component: () => import("@/views/commercial/MaterialsView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/materials/:id",
          name: "commercial-material",
          component: () => import("@/views/commercial/MaterialDetailView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/suppliers",
          name: "commercial-suppliers",
          component: () => import("@/views/commercial/SuppliersView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/suppliers/:id",
          name: "commercial-supplier",
          component: () => import("@/views/commercial/SupplierDetailView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/requests",
          name: "commercial-requests",
          component: () => import("@/views/commercial/RequestsView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/requests/:id",
          name: "commercial-request",
          component: () => import("@/views/commercial/RequestDetailView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/orders",
          name: "commercial-orders",
          component: () => import("@/views/commercial/OrdersView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/reports",
          name: "commercial-reports",
          component: () => import("@/views/commercial/CommercialReportsView.vue"),
          meta: { commercial: true },
        },

        // --- بازرگانی خارجی: the import pipeline and the waiting in it ---
        {
          path: "commercial/foreign",
          name: "foreign-dashboard",
          component: () => import("@/views/commercial/ForeignDashboardView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/foreign/orders",
          name: "foreign-orders",
          component: () => import("@/views/commercial/ForeignOrdersView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/foreign/orders/:id",
          name: "foreign-order",
          component: () => import("@/views/commercial/ForeignOrderDetailView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/foreign/queue",
          name: "foreign-queue",
          component: () => import("@/views/commercial/AllocationQueueView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/foreign/stalled",
          name: "foreign-stalled",
          component: () => import("@/views/commercial/StalledOrdersView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/foreign/shipments",
          name: "foreign-shipments",
          component: () => import("@/views/commercial/ShipmentsView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/foreign/demurrage",
          name: "foreign-demurrage",
          component: () => import("@/views/commercial/DemurrageView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/foreign/fx",
          name: "foreign-fx",
          component: () => import("@/views/commercial/FxRatesView.vue"),
          meta: { commercial: true },
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
        { path: "profile/:id", name: "profile", component: () => import("@/views/ProfileView.vue") },

        // --- Site settings (appearance + KPI formulas) — CEO's own controls.
        // User/role/data administration lives in the Admin Panel instead.
        {
          path: "settings",
          name: "settings",
          component: () => import("@/views/admin/SettingsView.vue"),
          meta: { executive: true },
        },
      ],
    },

    // ================= Admin Panel =================
    // A separate application area with its own shell, reachable only by
    // administrators. The CEO and ordinary users are redirected home.
    {
      path: "/admin",
      component: () => import("@/components/admin/AdminShell.vue"),
      meta: { requiresAuth: true, adminPanel: true },
      children: [
        { path: "", redirect: { name: "admin-dashboard" } },
        { path: "dashboard", name: "admin-dashboard", component: () => import("@/views/adminpanel/DashboardView.vue") },
        { path: "users", name: "admin-users", component: () => import("@/views/adminpanel/UsersView.vue") },
        { path: "roles", name: "admin-roles", component: () => import("@/views/adminpanel/RolesView.vue") },
        { path: "teams", name: "admin-teams", component: () => import("@/views/adminpanel/TeamsView.vue") },
        { path: "data", name: "admin-data", component: () => import("@/views/adminpanel/DataView.vue") },
        { path: "system", name: "admin-system", component: () => import("@/views/adminpanel/SystemView.vue") },
        { path: "audit", name: "admin-audit", component: () => import("@/views/adminpanel/AuditView.vue") },
        { path: "security", name: "admin-security", component: () => import("@/views/adminpanel/SecurityView.vue") },
        { path: "notifications", name: "admin-notifications", component: () => import("@/views/adminpanel/NotificationsView.vue") },
        { path: "files", name: "admin-files", component: () => import("@/views/adminpanel/FilesView.vue") },
        { path: "reports", name: "admin-reports", component: () => import("@/views/adminpanel/ReportsView.vue") },
        { path: "database", name: "admin-database", component: () => import("@/views/adminpanel/DatabaseView.vue") },
        { path: "workflow", name: "admin-workflow", component: () => import("@/views/adminpanel/WorkflowView.vue") },
        { path: "monitoring", name: "admin-monitoring", component: () => import("@/views/adminpanel/MonitoringView.vue") },
        { path: "content", name: "admin-content", component: () => import("@/views/adminpanel/ContentView.vue") },
      ],
    },
  ],
});

router.beforeEach(async (to) => {
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
  // Site settings: executives/superusers only.
  if (to.meta.executive && !auth.isExecutive) {
    return { name: homeRouteFor(auth.department) };
  }
  // Admin Panel: administrators only. The CEO has their own dashboards and
  // is kept out unless someone granted them access explicitly.
  if (to.meta.adminPanel && !auth.isAdminPanelUser) {
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
  // Finance: cash position is the most sensitive figure in the platform, so
  // it is the finance department, the CEO and admins — nobody else. The API
  // enforces the same rule; this only keeps the URL from showing an error page.
  if (to.meta.finance) {
    const canFinance =
      auth.isExecutive || !!auth.me?.is_superuser || auth.department === "finance";
    if (!canFinance) return { name: homeRouteFor(auth.department) };
  }
  // بازرگانی: what the company pays its suppliers is commercially sensitive,
  // so the same rule as finance — that department, the CEO and admins only.
  if (to.meta.commercial) {
    const canCommercial =
      auth.isExecutive || !!auth.me?.is_superuser || auth.department === "commercial";
    if (!canCommercial) return { name: homeRouteFor(auth.department) };
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
