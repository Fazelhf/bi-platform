import { defineStore } from "pinia";
import api from "@/api/client";
import { store } from "@/lib/storage";
import type { Me } from "@/types";

interface AuthState {
  access: string | null;
  refresh: string | null;
  me: Me | null;
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    access: store.get("access"),
    refresh: store.get("refresh"),
    me: store.getJSON<Me | null>("me", null),
  }),
  getters: {
    isAuthenticated: (s) => !!s.access,
    username: (s) => s.me?.display_name_fa || s.me?.username || "",
    isExecutive: (s) => s.me?.role === "executive" || s.me?.is_superuser,
    /** May this account open the Admin Panel? Mirrors the server's rule. */
    isAdminPanelUser: (s) => !!s.me?.is_admin_panel_user,
    department: (s): string => s.me?.department ?? "",
    canEnter: (s) => !!s.me?.can_enter_data,
  },
  actions: {
    async login(username: string, password: string) {
      const { data } = await api.post("/auth/token/", { username, password });
      this.access = data.access;
      this.refresh = data.refresh;
      store.set("access", data.access);
      store.set("refresh", data.refresh);
      await this.fetchMe();
    },
    async fetchMe() {
      const { data } = await api.get<Me>("/auth/me/");
      this.me = data;
      store.setJSON("me", data);
    },
    logout() {
      this.access = this.refresh = this.me = null;
      store.remove("access");
      store.remove("refresh");
      store.remove("me");
    },
  },
});
