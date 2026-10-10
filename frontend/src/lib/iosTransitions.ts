import type { Router } from "vue-router";

/**
 * The iOS skin's navigation transition: a new page slides in from the
 * leading edge the way UINavigationController pushes, and going back
 * slides it in from the other side. RTL flips the sides — in Persian iOS a
 * pushed screen arrives from the left.
 *
 * Direction comes from Vue Router's own history position, so the browser's
 * back button and swipe-back read as «back» too. Nothing happens in the
 * other skins, or when the OS asks for reduced motion (the CSS collapses it).
 */
export function installIosTransitions(router: Router) {
  let lastPosition = (window.history.state?.position as number | undefined) ?? 0;
  let timer = 0;

  router.afterEach((to, from) => {
    const root = document.documentElement;
    const position = (window.history.state?.position as number | undefined) ?? lastPosition;
    const back = position < lastPosition;
    lastPosition = position;
    if (root.dataset.skin !== "ios" || !from.matched.length || to.path === from.path) return;

    root.classList.remove("ios-push", "ios-pop");
    void root.offsetWidth; // restart the animation on quick successive taps
    root.classList.add(back ? "ios-pop" : "ios-push");
    window.clearTimeout(timer);
    // Removed afterwards: an animated transform makes its element the
    // containing block for `position: fixed` children, and a dialog opened
    // on the new page must be pinned to the viewport, not to the page.
    timer = window.setTimeout(() => root.classList.remove("ios-push", "ios-pop"), 520);
  });
}
