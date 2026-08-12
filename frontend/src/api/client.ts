import axios from "axios";
import { store } from "@/lib/storage";

// Dev: "/api" is proxied to Django by Vite. Production build: set
// VITE_API_URL (e.g. https://api.your-domain.com/api) in frontend/.env.production.
const baseURL = import.meta.env.VITE_API_URL || "/api";
const api = axios.create({ baseURL });

/** Storage key for the CRM demo grant — separate from the login token. */

/**
 * Pages reachable while signed out. A 401 on one of these is expected — the
 * app boots on the login screen and asks for site settings before anyone has
 * a token — so bouncing to /login from here would just be a redirect loop
 * that throws the user off «ورود با کد پیامکی» or «فراموشی رمز» the instant
 * the page loads.
 */
const PUBLIC_PATHS = ["/login", "/login-otp", "/forgot-password"];

function onPublicPage(): boolean {
  // endsWith, not equality: the app can be mounted under a path (ntpbi.ir/crm).
  return PUBLIC_PATHS.some((p) => location.pathname.endsWith(p));
}

// Attach the access token to every request.
api.interceptors.request.use((config) => {
  const token = store.get("access");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// On 401, try one refresh; if that fails, bounce to login.
let refreshing: Promise<string | null> | null = null;

async function refreshToken(): Promise<string | null> {
  const refresh = store.get("refresh");
  if (!refresh) return null;
  try {
    const { data } = await axios.post(`${baseURL}/auth/token/refresh/`, { refresh });
    store.set("access", data.access);
    if (data.refresh) store.set("refresh", data.refresh);
    return data.access;
  } catch {
    return null;
  }
}

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      refreshing = refreshing ?? refreshToken();
      const token = await refreshing;
      refreshing = null;
      if (token) {
        original.headers.Authorization = `Bearer ${token}`;
        return api(original);
      }
      store.remove("access");
      store.remove("refresh");
      if (!onPublicPage()) location.href = "/login";
    }
    return Promise.reject(error);
  },
);

export default api;
