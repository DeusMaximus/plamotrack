import type { KitStatus } from "../api/types";
import { minorFractionDigits } from "./currency";

export { minorFractionDigits, stepFor } from "./currency";

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

/** Major-unit user input ("49.99") → integer minor units (4999).
 *
 * Scaled by moving the decimal point through the string rather than multiplying,
 * because the float route disagrees with the backend at the halfway point: 1.005
 * AUD is 100.49999999999999 cents to `Math.round` and 101 to Python's Decimal.
 * The backend rounds half away from zero; so does this. */
export function majorToMinor(major: string | number, currency: string): number {
  const digits = minorFractionDigits(currency);
  // toFixed rather than String() on the number path: it keeps 1e-7 out of the
  // regex below, and one spare digit is enough to decide the rounding.
  const text = (typeof major === "number" ? major.toFixed(digits + 1) : major)
    .trim()
    .replace(/[\s,]/g, "");
  const parts = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(text);
  if (!parts || (!parts[2] && !parts[3])) return 0;

  const [, sign, whole = "", fraction = ""] = parts;
  // One digit past the cut is all a half-up decision needs; the rest can't reach it.
  const scaled = (fraction + "0".repeat(digits + 1)).slice(0, digits + 1);
  const kept = Number(whole + scaled.slice(0, digits));
  if (!Number.isFinite(kept)) return 0;

  const magnitude = kept + (Number(scaled[digits]) >= 5 ? 1 : 0);
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
