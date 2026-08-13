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

/**
 * Every section's manager-composed board.
 *
 * One component, one route per section — rather than a single `/reports/:id` —
 * so each page keeps the exact guard its section already has. The report of a
 * section must not be reachable by anyone the section itself is not.
 */
const BOARD_SECTIONS: { path: string; section: string; meta: Record<string, unknown> }[] = [
  { path: "reports/overview", section: "overview", meta: { executive: true } },
  { path: "reports/sales", section: "sales_team", meta: { salesChannel: "team" } },
  { path: "reports/sales-org", section: "sales_org", meta: { salesChannel: "organizational" } },
  { path: "reports/sales-b2b", section: "sales_b2b", meta: { salesChannel: "b2b" } },
  { path: "reports/production", section: "production", meta: {} },
  { path: "reports/finance", section: "finance", meta: { finance: true } },
  { path: "reports/commercial", section: "commercial", meta: { commercial: true } },
  { path: "reports/commercial-foreign", section: "commercial_foreign", meta: { commercial: true } },
  { path: "reports/crm", section: "crm", meta: { crm: true } },
];

/** `sales_team` → `board-sales-team`, the name the sidebar links to. */
export function boardRouteFor(section: string): string {
  return `board-${section.replace(/_/g, "-")}`;
}

const boardRoutes = BOARD_SECTIONS.map((b) => ({
  path: b.path,
  name: boardRouteFor(b.section),
  component: () => import("@/views/BoardView.vue"),
  props: { section: b.section },
  meta: b.meta,
}));

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

        // --- Manager-composed reports, one per section ---
        ...boardRoutes,

        // --- CRM (فروش همکار) — locked demo ---
        // مکاتبات — every signed-in employee has a کارتابل, so no meta
        // guard: a letter is addressed to a person, and being addressed is
        // the permission. The API enforces the same rule.
        {
          path: "office/letters",
          name: "office-letters",
          component: () => import("@/views/office/LettersView.vue"),
        },
        {
          path: "office/letters/:id",
          name: "office-letter",
          component: () => import("@/views/office/LetterDetailView.vue"),
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
          // The averages, which are a treasury tool rather than a company
          // figure — see the note on TreasuryView.
          path: "finance/treasury",
          name: "finance-treasury",
          component: () => import("@/views/finance/TreasuryView.vue"),
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
          // Both halves in tables, for review rather than for reacting.
          path: "commercial/report",
          name: "commercial-full-report",
          component: () => import("@/views/commercial/CommercialFullReportView.vue"),
          meta: { commercial: true },
        },
        {
          path: "commercial/materials",
          name: "commercial-materials",
          component: () => import("@/views/commercial/MaterialsView.vue"),
          meta: { commercial: true, commercialOnly: true },
        },
        {
          path: "commercial/materials/:id",
          name: "commercial-material",
          component: () => import("@/views/commercial/MaterialDetailView.vue"),
          meta: { commercial: true, commercialOnly: true },
        },
        {
          path: "commercial/suppliers",
          name: "commercial-suppliers",
          component: () => import("@/views/commercial/SuppliersView.vue"),
          meta: { commercial: true, commercialOnly: true },
        },
        {
          path: "commercial/suppliers/:id",
          name: "commercial-supplier",
          component: () => import("@/views/commercial/SupplierDetailView.vue"),
          meta: { commercial: true, commercialOnly: true },
        },
        {
          path: "commercial/requests",
          name: "commercial-requests",
          component: () => import("@/views/commercial/RequestsView.vue"),
          meta: { commercial: true, commercialOnly: true },
        },
        {
          path: "commercial/requests/:id",
          name: "commercial-request",
          component: () => import("@/views/commercial/RequestDetailView.vue"),
          meta: { commercial: true, commercialOnly: true },
        },
        {
          path: "commercial/samples",
          name: "commercial-samples",
          component: () => import("@/views/commercial/SamplesView.vue"),
          meta: { commercial: true, commercialOnly: true },
        },
        {
          path: "commercial/orders",
          name: "commercial-orders",
          component: () => import("@/views/commercial/OrdersView.vue"),
          meta: { commercial: true, commercialOnly: true },
        },

        // --- بازرگانی خارجی: the import pipeline and the waiting in it ---
        // Organised by what a file needs, not by which stage table it sits in.
        {
          path: "commercial/foreign",
          name: "foreign-dashboard",
          component: () => import("@/views/commercial/ForeignDashboardView.vue"),
          meta: { foreign: true },
        },
        {
          path: "commercial/foreign/workbench",
          name: "foreign-workbench",
          component: () => import("@/views/commercial/WorkbenchView.vue"),
          meta: { foreign: true, foreignOnly: true },
        },
        {
          path: "commercial/foreign/orders",
          name: "foreign-orders",
          component: () => import("@/views/commercial/ForeignOrdersView.vue"),
          meta: { foreign: true, foreignOnly: true },
        },
        {
          path: "commercial/foreign/orders/:id",
          name: "foreign-order",
          component: () => import("@/views/commercial/ForeignOrderDetailView.vue"),
          meta: { foreign: true, foreignOnly: true },
        },
        {
          path: "commercial/foreign/cargo",
          name: "foreign-shipments",
          component: () => import("@/views/commercial/ShipmentsView.vue"),
          meta: { foreign: true, foreignOnly: true },
        },
        {
          path: "commercial/foreign/payments",
          name: "foreign-payments",
          component: () => import("@/views/commercial/PaymentsView.vue"),
          meta: { foreign: true, foreignOnly: true },
        },
        {
          path: "commercial/foreign/history",
          name: "foreign-history",
          component: () => import("@/views/commercial/ForeignHistoryView.vue"),
          meta: { foreign: true, foreignOnly: true },
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
    // ===== CRM — its own workspace =====
    // Mounted outside AppShell on purpose: a salesperson lives in here and
    // never opens تولید or نقدینگی, and CRM is six places you switch between
    // rather than one of twenty sections you pick. Its shell gives the page
    // the full width and puts the way out in a fixed corner.
    {
      path: "/crm",
      component: () => import("@/components/crm/CrmShell.vue"),
      meta: { requiresAuth: true, crm: true },
      children: [
        {
          // The dashboard is the landing page. A separate «میز کار» was tried
          // and removed: this dataset is a sixteen-month history, so every
          // outstanding follow-up in it is a year old, and a to-do list where
          // all four hundred rows are equally late is not a to-do list.
          path: "",
          name: "crm-dashboard",
          component: () => import("@/views/crm/CrmDashboardView.vue"),
        },
        {
          path: "pipeline",
          name: "crm-pipeline",
          component: () => import("@/views/crm/PipelineView.vue"),
        },
        {
          path: "deals",
          name: "crm-deals",
          component: () => import("@/views/crm/DealsView.vue"),
        },
        {
          path: "deals/:id",
          name: "crm-deal",
          component: () => import("@/views/crm/DealDetailView.vue"),
        },
        {
          path: "customers",
          name: "crm-customers",
          component: () => import("@/views/crm/CustomersView.vue"),
        },
        {
          path: "customers/:id",
          name: "crm-customer",
          component: () => import("@/views/crm/CustomerDetailView.vue"),
        },
        {
          path: "activities",
          name: "crm-activities",
          component: () => import("@/views/crm/ActivitiesView.vue"),
        },
        {
          path: "reports",
          name: "crm-reports",
          component: () => import("@/views/crm/CrmReportsView.vue"),
        },
      ],
    },

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

/**
 * Where to send someone a guard has just turned away.
 *
 * Normally that is their own home page. But `homeRouteFor` answers `overview`
 * for anyone without a department, and `overview` is executive-only: a viewer
 * or a newly-created account with no section set was sent home, refused,
 * sent home again — and vue-router, finding the same target on every hop,
 * gave up and rendered nothing. A white screen, for the one kind of account
 * an administrator creates most often. When home is the page that just
 * refused, fall back to a page every signed-in account may open.
 */
function sentHome(to: { name?: unknown }) {
  const home = homeRouteFor(useAuthStore().department);
  return { name: home === to.name ? "profile-me" : home };
}

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (to.meta.requiresAuth && !auth.isAuthenticated) return { name: "login" };

  // Every check below reads `auth.me` — role, department, approver, panel
  // access. `me` is fetched at login and then cached, so a session that
  // arrives without it (a cleared cache, a deep link, a second device) ran
  // every one of those checks against null: department came back "", which
  // sends the user to `overview`, which is executive-only, which sends them
  // to `overview` again. The router aborted the loop and rendered nothing.
  if (auth.isAuthenticated && !auth.me) {
    try {
      await auth.fetchMe();
    } catch {
      // The token is no longer good for anything — sign out rather than
      // loop, and let the login screen say so.
      auth.logout();
      return { name: "login" };
    }
  }
  const signedOutOnly = ["login", "login-otp", "forgot-password"];
  if (signedOutOnly.includes(String(to.name)) && auth.isAuthenticated) {
    return sentHome(to);
  }
  // Entry pages are department-scoped; keep others out.
  const dept = to.meta.department as string | undefined;
  if (dept && !auth.me?.is_superuser && auth.department !== dept) {
    return sentHome(to);
  }
  // Site settings: executives/superusers only.
  if (to.meta.executive && !auth.isExecutive) {
    return sentHome(to);
  }
  // Admin Panel: administrators only. The CEO has their own dashboards and
  // is kept out unless someone granted them access explicitly.
  if (to.meta.adminPanel && !auth.isAdminPanelUser) {
    return sentHome(to);
  }
  // Inbox: approvers only.
  if (to.meta.approver && !auth.me?.can_approve && !auth.me?.is_superuser) {
    return sentHome(to);
  }
  // A sales channel belongs to the department that owns it. The sidebar
  // already only offered your own, but the URL was still reachable — and the
  // API now refuses, so without this the page would just show an error.
  const salesChannel = to.meta.salesChannel as string | undefined;
  if (salesChannel && !auth.isExecutive && !auth.me?.is_superuser) {
    const owner = { team: "sales_team", organizational: "sales_org", b2b: "sales_b2b" }[salesChannel];
    if (auth.department !== owner) return sentHome(to);
  }
  // Finance: cash position is the most sensitive figure in the platform, so
  // it is the finance department, the CEO and admins — nobody else. The API
  // enforces the same rule; this only keeps the URL from showing an error page.
  if (to.meta.finance) {
    const canFinance =
      auth.isExecutive || !!auth.me?.is_superuser || auth.department === "finance";
    if (!canFinance) return sentHome(to);
  }
  // CRM holds the company's real customer file — names, numbers, what each
  // account is worth. It belongs to فروش همکار, who work it, and the CEO, who
  // reads it. The API enforces the same rule (apps.crm.views.CrmAccess); this
  // only keeps the URL from landing someone on an error page.
  if (to.meta.crm) {
    const canCrm =
      auth.isExecutive
      || !!auth.me?.is_superuser
      || auth.department === "sales_team";
    if (!canCrm) return sentHome(to);
  }
  // بازرگانی: what the company pays its suppliers is commercially sensitive,
  // so the same rule as finance — that department, the CEO and admins only.
  // بازرگانی has two halves and one department. Each half has a dashboard the
  // CEO reads and working pages only بازرگانی opens — a BI dashboard answers
  // «چطور پیش می‌رود», and screens of rows answer a question the CEO is not
  // asking.
  const worksCommercial =
    !!auth.me?.is_superuser || auth.department === "commercial";
  if (to.meta.commercial) {
    if (!worksCommercial && !auth.isExecutive) {
      return sentHome(to);
    }
    if (to.meta.commercialOnly && !worksCommercial) {
      return { name: "commercial-dashboard" };
    }
  }
  if (to.meta.foreign) {
    if (!worksCommercial && !auth.isExecutive) {
      return sentHome(to);
    }
    if (to.meta.foreignOnly && !worksCommercial) {
      return { name: "foreign-dashboard" };
    }
  }
  // Roster: department managers (their own section) and the CEO.
  if (to.meta.roster) {
    const canRoster =
      auth.isExecutive ||
      !!auth.me?.is_superuser ||
      ["sales_team", "sales_org", "sales_b2b"].includes(auth.department);
    if (!canRoster) return sentHome(to);
  }
});

export default router;
