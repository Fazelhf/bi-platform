/**
 * Entry sheets start every cell at 0. Clicking one and typing 5 would leave
 * "05" — the zero is a placeholder nobody meant to keep. Selecting it on focus
 * makes the first keystroke replace it, while a cell holding a real figure is
 * left untouched so it can still be edited in place.
 */
export function selectIfZero(e: FocusEvent) {
  const el = e.target as HTMLInputElement | null;
  if (!el) return;
  if (Number(el.value || 0) === 0) el.select();
}
