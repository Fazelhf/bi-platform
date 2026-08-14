/**
 * The office workspace's sections, and the colour each one owns.
 *
 * Colour per section is the one identity cue the first build missed. Six grey
 * pages with grey cards are six pages you have to read the heading of to know
 * where you are; a coloured rail item and a matching header strip tell you
 * before you focus. Mizito does the same thing and it is why its sections
 * feel distinct despite sharing one layout.
 *
 * Delivered as a CSS custom property (`--sec`) rather than Tailwind classes,
 * because Tailwind compiles class names at build time and cannot generate
 * `bg-[#f97316]` from a variable at runtime. Setting `--sec` on the shell
 * root lets every child read it, and it composes with the three skins instead
 * of fighting them.
 */
export interface OfficeSection {
  name: string;
  label: string;
  icon: string;
  /** Hex. Written to `--sec` when the section is open. */
  color: string;
  /** One line under the page title — what this section is for. */
  hint: string;
}

export const OFFICE_SECTIONS: OfficeSection[] = [
  {
    name: "office-home",
    label: "میز کار",
    icon: "grid",
    color: "#0ea5e9",
    hint: "آنچه امروز منتظر شماست",
  },
  {
    name: "office-letters",
    label: "مکاتبات",
    icon: "inbox",
    color: "#f97316",
    hint: "نامه‌ها، پاراف و ارجاع",
  },
  {
    name: "office-tasks",
    label: "وظایف",
    icon: "check",
    color: "#10b981",
    hint: "کارهای من و آنچه به دیگران سپرده‌ام",
  },
  {
    name: "office-projects",
    label: "پروژه‌ها",
    icon: "clipboard",
    color: "#8b5cf6",
    hint: "کارهای گروهی و پیشرفتشان",
  },
  {
    name: "chat",
    label: "گفتگو",
    icon: "chat",
    color: "#3b6fed",
    hint: "پیام مستقیم و گروهی",
  },
  {
    name: "notes",
    label: "یادداشت‌ها",
    icon: "notes",
    color: "#f59e0b",
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
