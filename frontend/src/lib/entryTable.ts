import type { Directive } from "vue";

/**
 * `v-entry-table` — makes a data-entry sheet usable without sideways
 * scrolling. Put it on the <table> of any entry grid.
 *
 *   • Phone (< 768px): every row turns into its own card. The row's first
 *     cell is the card title and every other cell becomes a labelled field,
 *     the label taken from that column's header. A 12-column sheet becomes
 *     a column of short cards you scroll *down* through, the way iOS forms
 *     work — nothing is hidden off the side of the screen.
 *   • Wider screens: the table stays a table, but its first column (the row
 *     name) is pinned while the figures scroll, so you never lose track of
 *     which row you are typing into.
 *   • Everywhere: Enter moves to the same column in the next row (Shift+Enter
 *     to the previous), so a column of figures is typed straight down
 *     without reaching for the mouse.
 *
 * The layout itself lives in styles/entry-table.css. This directive only
 * copies each column's header text onto its cells (data-label), which CSS
 * cannot do on its own, and keeps that in step as rows are added or removed.
 */

function headerLabels(table: HTMLTableElement): string[] {
  const rows = table.tHead?.rows;
  if (!rows?.length) return [];
  const labels: string[] = [];
  for (const th of Array.from(rows[rows.length - 1].cells)) {
    const text = (th.textContent ?? "").replace(/\s+/g, " ").trim();
    for (let i = 0; i < (th.colSpan || 1); i++) labels.push(text);
  }
  return labels;
}

function label(table: HTMLTableElement) {
  const labels = headerLabels(table);
  for (const body of Array.from(table.tBodies)) {
    for (const tr of Array.from(body.rows)) {
      const cells = Array.from(tr.cells);
      // A lone full-width cell is a section heading inside the sheet.
      const section = cells.length === 1 && cells[0].colSpan > 1;
      tr.classList.toggle("entry-section", section);
      let col = 0;
      cells.forEach((td, i) => {
        td.classList.toggle("entry-title", i === 0 && !section);
        const text = labels[col] ?? "";
        if (td.dataset.label !== text) td.dataset.label = text;
        col += td.colSpan || 1;
      });
    }
  }
}

/** Enter / Shift+Enter: same column, next / previous row. */
function onKeydown(e: KeyboardEvent) {
  if (e.key !== "Enter" || e.isComposing) return;
  const input = e.target as HTMLElement;
  if (!(input instanceof HTMLInputElement)) return;
  const td = input.closest("td");
  const tr = td?.parentElement as HTMLTableRowElement | null;
  if (!td || !tr) return;
  const index = Array.from(tr.cells).indexOf(td as HTMLTableCellElement);
  let row: Element | null = tr;
  while ((row = e.shiftKey ? row.previousElementSibling : row.nextElementSibling)) {
    const next = (row as HTMLTableRowElement).cells?.[index]?.querySelector<HTMLInputElement>(
      "input:not([type=checkbox]):not([type=radio]):not(:disabled)",
    );
    if (next) {
      e.preventDefault();
      next.focus();
      next.select?.();
      return;
    }
  }
}

const state = new WeakMap<HTMLElement, { observer: MutationObserver; frame: number }>();

export const vEntryTable: Directive<HTMLTableElement> = {
  mounted(el) {
    el.classList.add("entry-table");
    label(el);
    const entry = {
      frame: 0,
      observer: new MutationObserver(() => {
        if (entry.frame) return;
        entry.frame = requestAnimationFrame(() => {
          entry.frame = 0;
          label(el);
        });
      }),
    };
    entry.observer.observe(el, { childList: true, subtree: true, characterData: true });
    state.set(el, entry);
    el.addEventListener("keydown", onKeydown);
  },
  beforeUnmount(el) {
    const entry = state.get(el);
    entry?.observer.disconnect();
    if (entry?.frame) cancelAnimationFrame(entry.frame);
    state.delete(el);
    el.removeEventListener("keydown", onKeydown);
  },
};
