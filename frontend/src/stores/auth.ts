import { defineStore } from "pinia";
import api from "@/api/client";
import { store } from "@/lib/storage";
import type { Me, OtpChallenge } from "@/types";

interface AuthState {
  access: string | null;
  refresh: string | null;
  me: Me | null;
}

/**
 * What `login()` came back with. Either the session is open, or the account
 * has two-step login on and owes a code — the challenge is not a credential
 * on its own, so it is safe to hold in component state.
 */
export type LoginResult =
  | { otpRequired: false }
  | { otpRequired: true; challenge: OtpChallenge };

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
    async login(username: string, password: string): Promise<LoginResult> {
      const { data } = await api.post("/auth/token/", { username, password });
      if (data.otp_required) return { otpRequired: true, challenge: data };
      await this.accept(data);
      return { otpRequired: false };
    },
    /** Second step: trade the code for the session. */
    async verifyOtp(challenge: string, code: string) {
      const { data } = await api.post("/auth/2fa/verify/", { challenge, code });
      await this.accept(data);
    },
    async resendOtp(challenge: string): Promise<OtpChallenge> {
      const { data } = await api.post("/auth/2fa/resend/", { challenge });
      return data as OtpChallenge;
    },
    async accept(tokens: { access: string; refresh: string }) {
      this.access = tokens.access;
      this.refresh = tokens.refresh;
      store.set("access", tokens.access);
      store.set("refresh", tokens.refresh);
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
