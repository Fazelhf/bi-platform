/**
 * عدد به حروف — for the «مبلغ به حروف» line of a printed invoice.
 *
 * An amount written in words is the part of an invoice that cannot be
 * altered by adding a digit, which is why the standard form asks for it.
 */
const ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"];
const TEENS = ["ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده"];
const TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"];
const HUNDREDS = ["", "یکصد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"];
const SCALES = ["", "هزار", "میلیون", "میلیارد", "هزار میلیارد", "میلیون میلیارد"];

function belowThousand(n: number): string {
  const parts: string[] = [];
  const h = Math.floor(n / 100);
  const rest = n % 100;
  if (h) parts.push(HUNDREDS[h]);
  if (rest >= 10 && rest < 20) parts.push(TEENS[rest - 10]);
  else {
    const t = Math.floor(rest / 10);
    const o = rest % 10;
    if (t) parts.push(TENS[t]);
    if (o) parts.push(ONES[o]);
  }
  return parts.join(" و ");
}

export function numberToWords(value: number | string): string {
  let n = Math.round(Math.abs(Number(value) || 0));
  if (n === 0) return "صفر";
  const groups: string[] = [];
  let scale = 0;
  while (n > 0) {
    const chunk = n % 1000;
    if (chunk) groups.unshift(`${belowThousand(chunk)}${SCALES[scale] ? ` ${SCALES[scale]}` : ""}`);
    n = Math.floor(n / 1000);
    scale += 1;
  }
  return (Number(value) < 0 ? "منفی " : "") + groups.join(" و ");
}

export function rialInWords(value: number | string): string {
  return `${numberToWords(value)} ریال`;
}
