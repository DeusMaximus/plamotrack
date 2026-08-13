import type { KitStatus } from "../api/types";
import { minorFractionDigits } from "./currency";

export { COMMON_CURRENCIES, currencyOptions, minorFractionDigits, stepFor } from "./currency";

export const STATUS_LABELS: Record<KitStatus, string> = {
  pre_ordered: "Pre-ordered",
  ordered: "Ordered",
  in_transit: "In Transit",
  backlog: "Backlog",
  building: "Building",
  complete: "Complete",
};

/** "4999 AUD minor" → "$49.99"
 *
 * Intl still picks the symbol, grouping and placement, but the decimals are ours:
 * left to itself it would render a 1234-minor IQD line as "IQD 1,234" rather than
 * the 1.234 dinar it stands for. */
export function formatMoney(minor: number, currency: string): string {
  const digits = minorFractionDigits(currency);
  const value = minor / 10 ** digits;
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(value);
  } catch {
    return `${value.toFixed(digits)} ${currency}`;
  }
}

/** Integer minor units (4999) → major-unit string for form inputs ("49.99"). */
export function minorToMajor(minor: number, currency: string): string {
  const digits = minorFractionDigits(currency);
  return (minor / 10 ** digits).toFixed(digits);
}

/** Thousands separators removed, or `null` where the comma is ambiguous.
 *
 * The mirror of `strip_numeric_grouping` in `backend/app/services/currency.py`;
 * `__fixtures__/money-cases.json` is read by both suites so the two cannot drift.
 * A comma used to be stripped unconditionally on both sides, which made `12,34` —
 * how much of the world writes 12.34 — into 1234 major units, a hundredfold error.
 * It is accepted only where it cannot be a decimal point: grouped in threes, and
 * never after the decimal point. */
function degroup(text: string): string | null {
  if (!text.includes(",")) return text;
  const point = text.indexOf(".");
  const head = point === -1 ? text : text.slice(0, point);
  const tail = point === -1 ? "" : text.slice(point);
  if (tail.includes(",") || !/^[+-]?\d{1,3}(?:,\d{3})+$/.test(head)) return null;
  return head.replace(/,/g, "") + tail;
}

/** Major-unit user input ("49.99") → integer minor units (4999).
 *
 * Scaled by moving the decimal point through the string rather than multiplying,
 * because the float route disagrees with the backend at the halfway point: 1.005
 * AUD is 100.49999999999999 cents to `Math.round` and 101 to Python's Decimal.
 * The backend rounds half away from zero; so does this. */
export function majorToMinor(major: string | number, currency: string): number {
  const digits = minorFractionDigits(currency);
  const text = degroup((typeof major === "number" ? String(major) : major).replace(/\s/g, ""));
  if (text === null) return 0;
  // Exponent notation is not exotic here: `<input type="number">` treats "1e2" as a
  // valid value and hands it over unchanged, and Decimal reads it on the backend. A
  // parser that ignored it would return 0 for a field the user filled in.
  const parts = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(text);
  if (!parts || (!parts[2] && !parts[3])) return 0;

  const [, sign, whole = "", fraction = "", exponent] = parts;
  const mantissa = whole + fraction;
  // Where the decimal point ends up once the amount is counted in minor units:
  // its position in `mantissa`, moved right by the currency's digits and by the
  // exponent. Everything left of it is the answer; the digit on it decides the
  // rounding, and nothing further right can reach the decision.
  const point = whole.length + digits + Number(exponent ?? 0);
  if (point <= 0) {
    // Below half a minor unit, unless the leading digit sits exactly on the cut.
    const rounds = point === 0 && Number(mantissa[0]) >= 5;
    return rounds ? (sign === "-" ? -1 : 1) : 0;
  }

  const padded = mantissa.padEnd(point + 1, "0");
  const kept = Number(padded.slice(0, point));
  if (!Number.isFinite(kept)) return 0;

  const magnitude = kept + (Number(padded[point]) >= 5 ? 1 : 0);
  return sign === "-" ? -magnitude : magnitude;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString();
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function todayISO(): string {
  // Local date, not UTC — an evening order in AEST is not "yesterday".
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}
