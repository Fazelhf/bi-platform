import { onBeforeUnmount, onMounted, type Ref } from "vue";

/**
 * Close a popover when the user clicks anywhere outside it, or presses Escape.
 *
 * Listens on the capture phase so it still fires when an inner handler stops
 * propagation, and checks `composedPath()` rather than `event.target` so a
 * click that lands on a child element still counts as "inside".
 */
export function useClickOutside(
  root: Ref<HTMLElement | null>,
  onOutside: () => void,
) {
  function handlePointer(e: MouseEvent | TouchEvent) {
    const el = root.value;
    if (!el) return;
    if (e.composedPath().includes(el)) return;
    onOutside();
  }

  function handleKey(e: KeyboardEvent) {
    if (e.key === "Escape") onOutside();
  }

  onMounted(() => {
    document.addEventListener("mousedown", handlePointer, true);
    document.addEventListener("touchstart", handlePointer, true);
    document.addEventListener("keydown", handleKey);
  });

  onBeforeUnmount(() => {
    document.removeEventListener("mousedown", handlePointer, true);
    document.removeEventListener("touchstart", handlePointer, true);
    document.removeEventListener("keydown", handleKey);
  });
}
