import axios from "axios";
import { store } from "@/lib/storage";

// Dev: "/api" is proxied to Django by Vite. Production build: set
// VITE_API_URL (e.g. https://api.your-domain.com/api) in frontend/.env.production.
const baseURL = import.meta.env.VITE_API_URL || "/api";
const api = axios.create({ baseURL });

/** Storage key for the CRM demo grant — separate from the login token. */
export const CRM_KEY = "crmKey";

// Attach the access token to every request.
api.interceptors.request.use((config) => {
  const token = store.get("access");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  // CRM sits behind its own password; its grant rides along on CRM calls only.
  if (config.url?.includes("/crm/")) {
    const crmKey = store.get(CRM_KEY);
    if (crmKey) config.headers["X-CRM-Key"] = crmKey;
  }
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
    // An expired or revoked CRM grant looks like a 403 on a /crm/ call. Drop
    // the dead key so the UI re-prompts instead of silently showing nothing.
    if (
      error.response?.status === 403 &&
      original?.url?.includes("/crm/") &&
      !original.url.includes("/crm/gate/")
    ) {
      store.remove(CRM_KEY);
    }
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
      if (location.pathname !== "/login") location.href = "/login";
    }
    return Promise.reject(error);
  },
);

export default api;
