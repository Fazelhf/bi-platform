import { defineStore } from "pinia";
import { shellApi } from "@/api/admin";
import type { AdminBootstrap, PermissionGroup } from "@/types/admin";

/**
 * Admin-Panel session state.
 *
 * `can(code)` is the single source of truth for showing an action in the UI.
 * It mirrors the server's rule exactly — superusers hold every code — so the
 * interface never offers a button the API would refuse.
 */
export const useAdminStore = defineStore("adminPanel", {
  state: () => ({
    loaded: false,
    loading: false,
    error: "",
    permissions: [] as string[],
    catalog: [] as PermissionGroup[],
    user: null as AdminBootstrap["user"] | null,
    maintenance: false,
    companyName: "",
    flags: {} as Record<string, boolean>,
    // Served by the API from the model's choices — never hard-coded here,
    // or a new department silently goes missing from every dropdown.
    departments: [] as { value: string; label: string }[],
    roles: [] as { value: string; label: string }[],
  }),
  getters: {
    isSuperuser: (s) => !!s.user?.is_superuser,
    /** Does this admin hold a given permission code? */
    can(state) {
      return (code: string): boolean =>
        !!state.user?.is_superuser || state.permissions.includes(code);
    },
    /** True if they hold at least one of the codes (menu visibility). */
    canAny(state) {
      return (codes: string[]): boolean =>
        !!state.user?.is_superuser || codes.some((c) => state.permissions.includes(c));
    },
    permissionLabels(state): Record<string, string> {
      const map: Record<string, string> = {};
      for (const group of state.catalog) {
        for (const [code, label] of group.permissions) map[code] = label;
      }
      return map;
    },
  },
  actions: {
    async bootstrap(force = false) {
      if (this.loaded && !force) return;
      this.loading = true;
      this.error = "";
      try {
        const data = await shellApi.bootstrap();
        this.user = data.user;
        this.permissions = data.permissions;
        this.catalog = data.catalog;
        this.maintenance = data.maintenance;
        this.companyName = data.company_name;
        this.flags = data.flags;
        this.departments = data.departments ?? [];
        this.roles = data.roles ?? [];
        this.loaded = true;
      } catch (e: any) {
        this.error = e?.response?.status === 403
          ? "دسترسی به پنل مدیریت ندارید."
          : "بارگذاری پنل مدیریت ناموفق بود.";
        throw e;
      } finally {
        this.loading = false;
      }
    },
    reset() {
      this.$reset();
    },
  },
});
