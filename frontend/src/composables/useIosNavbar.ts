import { onBeforeUnmount, onMounted, ref } from "vue";

/**
 * iOS navigation-bar behaviour for a shell's sticky header: transparent and
 * borderless while the page sits at the top, then frosted with a hairline
 * once content scrolls under it — the way every UINavigationBar behaves.
 * The class is harmless in the other skins; only the iOS CSS reads it.
 */
export function useIosNavbar() {
  const scrolled = ref(false);
  const onScroll = () => {
    // Roughly the height of a large title: the small title should arrive as
    // the large one leaves, not the moment the page moves.
    scrolled.value = window.scrollY > 44;
  };
  onMounted(() => {
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  });
  onBeforeUnmount(() => window.removeEventListener("scroll", onScroll));
  return { scrolled };
}
