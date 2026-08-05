import { onBeforeUnmount, onMounted, type Ref } from "vue";

/**
 * Close a popover when the user clicks anywhere outside it, or presses Escape.
 *
 * Listens on the capture phase so it still fires when an inner handler stops
 * propagation, and checks `composedPath()` rather than `event.target` so a
 * click that lands on a child element still counts as "inside".
 *
 * `also` covers panels that are teleported out of the trigger's subtree: a
 * click inside them is still "inside" even though the DOM says otherwise.
 */
export function useClickOutside(
  root: Ref<HTMLElement | null>,
  onOutside: () => void,
  also?: Ref<HTMLElement | null>,
) {
  function handlePointer(e: MouseEvent | TouchEvent) {
    const el = root.value;
    if (!el) return;
    const path = e.composedPath();
    if (path.includes(el)) return;
    if (also?.value && path.includes(also.value)) return;
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
