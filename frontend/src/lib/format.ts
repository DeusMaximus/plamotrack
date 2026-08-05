import type { KitStatus } from "../api/types";

export const STATUS_LABELS: Record<KitStatus, string> = {
  backlog: "Backlog",
  pre_ordered: "Pre-ordered",
  ordered: "Ordered",
  in_transit: "In Transit",
  in_hand: "In Hand",
  building: "Building",
  complete: "Complete",
};

/** Minor-unit digits for a currency (JPY → 0, AUD → 2), via Intl. */
export function minorFractionDigits(currency: string): number {
  try {
    return (
      new Intl.NumberFormat("en", { style: "currency", currency }).resolvedOptions()
        .maximumFractionDigits ?? 2
    );
  } catch {
    return 2;
  }
}

/** "4999 AUD minor" → "$49.99" */
export function formatMoney(minor: number, currency: string): string {
  const digits = minorFractionDigits(currency);
  const value = minor / 10 ** digits;
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(value);
  } catch {
    return `${value.toFixed(digits)} ${currency}`;
  }
}

/** Integer minor units (4999) → major-unit string for form inputs ("49.99"). */
export function minorToMajor(minor: number, currency: string): string {
  const digits = minorFractionDigits(currency);
  return (minor / 10 ** digits).toFixed(digits);
}

/** Major-unit user input ("49.99") → integer minor units (4999). */
export function majorToMinor(major: string | number, currency: string): number {
  const value = typeof major === "string" ? Number.parseFloat(major) : major;
  if (Number.isNaN(value)) return 0;
  return Math.round(value * 10 ** minorFractionDigits(currency));
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
