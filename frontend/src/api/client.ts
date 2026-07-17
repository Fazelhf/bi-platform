import axios from "axios";

const api = axios.create({ baseURL: "/api" });

// Attach the access token to every request.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// On 401, try one refresh; if that fails, bounce to login.
let refreshing: Promise<string | null> | null = null;

async function refreshToken(): Promise<string | null> {
  const refresh = localStorage.getItem("refresh");
  if (!refresh) return null;
  try {
    const { data } = await axios.post("/api/auth/token/refresh/", { refresh });
    localStorage.setItem("access", data.access);
    if (data.refresh) localStorage.setItem("refresh", data.refresh);
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
      localStorage.removeItem("access");
      localStorage.removeItem("refresh");
      if (location.pathname !== "/login") location.href = "/login";
    }
    return Promise.reject(error);
  },
);

export default api;
