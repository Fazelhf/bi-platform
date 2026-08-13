import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import router from "./router";
import { useUiStore } from "./stores/ui";
import { useAuthStore } from "./stores/auth";
import "./style.css";

const app = createApp(App);
app.use(createPinia()).use(router);

// A deploy replaces every hashed chunk at once. A tab that was already open —
// or one that loaded a cached index.html — keeps asking for the names it was
// told about, the server no longer has them, and the lazy route resolves to
// nothing: a white page, and no error the user can act on. Reloading fetches
// the current index.html, which names the chunks that now exist.
//
// The timestamp is the loop guard: if the page has just reloaded for this
// reason, a second failure is a real one and gets left alone rather than
// reloading forever.
function reloadOnceForStaleChunks() {
  const KEY = "spa:chunk-reload";
  const last = Number(sessionStorage.getItem(KEY) ?? 0);
  if (Date.now() - last < 10_000) return false;
  sessionStorage.setItem(KEY, String(Date.now()));
  window.location.reload();
  return true;
}

window.addEventListener("vite:preloadError", (event) => {
  if (reloadOnceForStaleChunks()) event.preventDefault();
});

// The same failure arriving through the router instead of the preloader —
// a route whose component chunk is gone.
router.onError((error) => {
  if (/dynamically imported module|Importing a module script failed/i.test(String(error?.message))) {
    reloadOnceForStaleChunks();
  }
});

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
