/**
 * The three facts the app needs to know about being an installed app.
 *
 * They arrive from three unrelated browser APIs, at three unrelated moments,
 * and every one of them is easy to get subtly wrong — so they are read once
 * here, as a module-level singleton, and shared. A component that calls this
 * twice gets the same state, not a second `beforeinstallprompt` listener.
 *
 *   needsUpdate — a new bundle is sitting in a waiting service worker
 *   canInstall  — the browser has offered us the install prompt to fire
 *   online      — whether the numbers on screen can still be refreshed
 */
import { readonly, ref, watch } from "vue";
import { useRegisterSW } from "virtual:pwa-register/vue";

/** The event Chrome fires when the app becomes installable. Not in lib.dom. */
interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

const deferredPrompt = ref<InstallPromptEvent | null>(null);
const canInstall = ref(false);
const online = ref(navigator.onLine);
/** True from the moment the network drops until it comes back *and* is used. */
const wasOffline = ref(false);

let started = false;

/**
 * `useRegisterSW` must be called inside an effect scope on some Vue versions,
 * and exactly once regardless. Hoisting its refs out here keeps both true
 * while still letting any component read the result.
 */
const needsUpdate = ref(false);
const offlineReady = ref(false);
let doUpdate: (reload?: boolean) => Promise<void> = async () => {};
/** The installed-but-not-yet-active worker, when we found it ourselves. */
let waiting: ServiceWorker | null = null;

function start() {
  if (started) return;
  started = true;

  const { needRefresh, offlineReady: ready, updateServiceWorker } = useRegisterSW({
    onRegisteredSW(_url, registration) {
      if (!registration) return;

      // Chrome only checks for a new worker on navigation, and this app is a
      // SPA: someone who leaves the tab open all week would never be offered
      // an update. An hourly poll costs one conditional GET of a 12 KB file.
      setInterval(() => registration.update().catch(() => {}), 60 * 60 * 1000);

      // A worker that was *already* waiting when this page loaded.
      //
      // The plugin's own flag is driven by workbox's `waiting` event, which
      // fires for the worker this page instance installed — so dismissing the
      // prompt and then refreshing (the most natural thing to do) left the
      // update sitting there, installed and waiting, with nothing ever
      // offering it again. Checked directly here instead.
      const promote = () => {
        if (registration.waiting && navigator.serviceWorker.controller) {
          waiting = registration.waiting;
          needsUpdate.value = true;
        }
      };
      promote();
      registration.addEventListener("updatefound", () => {
        const fresh = registration.installing;
        fresh?.addEventListener("statechange", () => {
          if (fresh.state === "installed") promote();
        });
      });
    },
  });

  // Mirrored rather than re-exported: callers get stable readonly refs whose
  // identity does not depend on when the worker happened to register.
  watch(needRefresh, (v) => (needsUpdate.value = v), { immediate: true });
  watch(ready, (v) => (offlineReady.value = v), { immediate: true });
  doUpdate = updateServiceWorker;

  window.addEventListener("beforeinstallprompt", (e) => {
    // Chrome shows its own mini-infobar unless this is prevented; we would
    // rather offer it from the menu, where it is not in the way of work.
    e.preventDefault();
    deferredPrompt.value = e as InstallPromptEvent;
    canInstall.value = true;
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt.value = null;
    canInstall.value = false;
  });

  window.addEventListener("online", () => (online.value = true));
  window.addEventListener("offline", () => {
    online.value = false;
    wasOffline.value = true;
  });
}

export function usePwa() {
  start();

  /** Fire the browser's own install dialog. One shot — the event is spent. */
  async function install(): Promise<boolean> {
    const evt = deferredPrompt.value;
    if (!evt) return false;
    await evt.prompt();
    const { outcome } = await evt.userChoice;
    deferredPrompt.value = null;
    canInstall.value = false;
    return outcome === "accepted";
  }

  /**
   * Activate the waiting worker and reload onto the new bundle.
   *
   * Told to the worker directly when we are the ones who found it, since the
   * plugin's helper only knows about workers it saw install. Either way the
   * reload waits for `controllerchange`: reloading first would just fetch the
   * old bundle from the old worker and change nothing, which reads as a
   * button that does not work.
   */
  async function update() {
    needsUpdate.value = false;
    if (waiting) {
      navigator.serviceWorker.addEventListener(
        "controllerchange",
        () => window.location.reload(),
        { once: true },
      );
      waiting.postMessage({ type: "SKIP_WAITING" });
      waiting = null;
      return;
    }
    await doUpdate(true);
  }

  /** Already installed? Then «نصب برنامه» would be a button to nowhere. */
  const isInstalled =
    window.matchMedia("(display-mode: standalone)").matches ||
    // iOS Safari's own flag, which predates the standard and is still the
    // only way to tell there.
    (navigator as unknown as { standalone?: boolean }).standalone === true;

  return {
    needsUpdate: readonly(needsUpdate),
    offlineReady: readonly(offlineReady),
    canInstall: readonly(canInstall),
    online: readonly(online),
    wasOffline: readonly(wasOffline),
    isInstalled,
    install,
    update,
  };
}
