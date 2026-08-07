import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import router from "./router";
import { useUiStore } from "./stores/ui";
import { useAuthStore } from "./stores/auth";
import "./style.css";

const app = createApp(App);
app.use(createPinia()).use(router);

// `me` is cached in localStorage so the first paint knows who you are without
// waiting on a request. The cache was never refreshed, though: an account
// whose role or department changed after its last sign-in kept the old
// answer — and every sidebar entry, route guard and permission check reads
// it. Someone given a department yesterday still had none today, until they
// happened to sign out. Re-reading it on boot costs one request and is the
// only place that can notice.
const auth = useAuthStore();
if (auth.isAuthenticated && auth.me) {
  auth.fetchMe().catch(() => {
    /* offline or expired — the cached copy and the guard still cover it */
  });
}

const ui = useUiStore();
// Apply the saved skin and light/dark choice before the first paint, so the
// page never flashes the wrong theme on reload.
ui.initAppearance();
// Load the CEO-selected chart theme before first paint.
ui.fetch();

app.mount("#app");
