import { defineStore } from "pinia";
import api from "@/api/client";

interface AuthState {
  access: string | null;
  refresh: string | null;
  username: string | null;
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    access: localStorage.getItem("access"),
    refresh: localStorage.getItem("refresh"),
    username: localStorage.getItem("username"),
  }),
  getters: {
    isAuthenticated: (s) => !!s.access,
  },
  actions: {
    async login(username: string, password: string) {
      const { data } = await api.post("/auth/token/", { username, password });
      this.access = data.access;
      this.refresh = data.refresh;
      this.username = username;
      localStorage.setItem("access", data.access);
      localStorage.setItem("refresh", data.refresh);
      localStorage.setItem("username", username);
    },
    logout() {
      this.access = this.refresh = this.username = null;
      localStorage.removeItem("access");
      localStorage.removeItem("refresh");
      localStorage.removeItem("username");
    },
  },
});
