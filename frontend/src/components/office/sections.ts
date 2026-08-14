/**
 * The office workspace's sections, and the colour each one owns.
 *
 * Colour per section is the one identity cue the first build missed. Six grey
 * pages with grey cards are six pages you have to read the heading of to know
 * where you are; a coloured rail item and a matching header strip tell you
 * before you focus. Mizito does the same thing and it is why its sections
 * feel distinct despite sharing one layout.
 *
 * Delivered as a CSS custom property rather than Tailwind classes, because
 * Tailwind compiles class names at build time and cannot build `bg-[#f97316]`
 * from a runtime value.
 *
 * The value is **RGB channels**, not hex, matching the convention in
 * style.css. That is what lets `rgb(var(--sec) / 0.12)` produce a tint that
 * adapts per skin — the first version concatenated alpha onto a hex string,
 * which cannot adapt and left section chips nearly invisible in dark mode.
 * The palette itself lives in styles/office.css as primitive tokens; this
 * file only says which section owns which one.
 */
export interface OfficeSection {
  name: string;
  label: string;
  icon: string;
  /** RGB channels, e.g. "249 115 22". Written to `--sec` when open. */
  color: string;
  /** One line under the page title — what this section is for. */
  hint: string;
}

export const OFFICE_SECTIONS: OfficeSection[] = [
  {
    name: "office-home",
    label: "میز کار",
    icon: "grid",
    color: "14 165 233",
    hint: "آنچه امروز منتظر شماست",
  },
  {
    name: "office-letters",
    label: "مکاتبات",
    icon: "inbox",
    color: "249 115 22",
    hint: "نامه‌ها، پاراف و ارجاع",
  },
  {
    name: "office-tasks",
    label: "وظایف",
    icon: "check",
    color: "16 185 129",
    hint: "کارهای من و آنچه به دیگران سپرده‌ام",
  },
  {
    name: "office-projects",
    label: "پروژه‌ها",
    icon: "clipboard",
    color: "139 92 246",
    hint: "کارهای گروهی و پیشرفتشان",
  },
  {
    name: "chat",
    label: "گفتگو",
    icon: "chat",
    color: "59 111 237",
    hint: "پیام مستقیم و گروهی",
  },
  {
    name: "notes",
    label: "یادداشت‌ها",
    icon: "notes",
    color: "245 158 11",
    hint: "یادداشت‌های شخصی",
  },
];

/** Detail pages keep their parent section lit and coloured. */
const PARENT: Record<string, string> = {
  "office-letter": "office-letters",
  "office-project": "office-projects",
};

export function sectionFor(routeName: string | undefined): OfficeSection {
  const key = PARENT[String(routeName)] ?? String(routeName);
  return OFFICE_SECTIONS.find((s) => s.name === key) ?? OFFICE_SECTIONS[0];
}

export function isActive(section: string, routeName: string | undefined): boolean {
  const current = String(routeName ?? "");
  return current === section || PARENT[current] === section;
}
