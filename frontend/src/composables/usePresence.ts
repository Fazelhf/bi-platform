import { onBeforeUnmount, onMounted } from "vue";
import { socialApi } from "@/api/social";

/** Ping the server every 30s so this user shows as online to others. */
export function usePresence() {
  let timer: number | undefined;
  onMounted(() => {
    socialApi.heartbeat();
    timer = window.setInterval(() => socialApi.heartbeat(), 30_000);
    document.addEventListener("visibilitychange", onVisible);
  });
  onBeforeUnmount(() => {
    window.clearInterval(timer);
    document.removeEventListener("visibilitychange", onVisible);
  });
  function onVisible() {
    if (document.visibilityState === "visible") socialApi.heartbeat();
  }
}
