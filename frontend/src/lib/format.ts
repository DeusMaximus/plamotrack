import { minorFractionDigits } from "./currency";
import { formatPreferences } from "./presentation";
import type { FormatPreferences } from "./presentation";

export { COMMON_CURRENCIES, currencyOptions, minorFractionDigits, stepFor } from "./currency";

/** "4999 AUD minor" → "$49.99"
 *
 * The instance's formatting locale (#27) picks the symbol, grouping and
 * placement, but the decimals are ours — plamotrack's own ISO 4217 exponent
 * table (§6): left to itself Intl would render a 1234-minor IQD line as
 * "IQD 1,234" rather than the 1.234 dinar it stands for, and a locale is never
 * allowed to change what an amount means.
 *
 * Each helper has a `…With` twin taking explicit preferences — the Language
 * section's live preview drives drafts through them before anything is saved,
 * and the unit suite drives them without touching module state. */
export function formatMoneyWith(locale: string, minor: number, currency: string): string {
  const digits = minorFractionDigits(currency);
  const value = minor / 10 ** digits;
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(value);
  } catch {
    return `${value.toFixed(digits)} ${currency}`;
  }
}

export function formatMoney(minor: number, currency: string): string {
  return formatMoneyWith(formatPreferences().locale, minor, currency);
}

/** A plain count or quantity under the instance's formatting locale — grouping
 *  and digit punctuation only; the value itself is canonical. */
export function formatNumberWith(locale: string, value: number): string {
  try {
    return new Intl.NumberFormat(locale).format(value);
  } catch {
    return String(value);
  }
}

export function formatNumber(value: number): string {
  return formatNumberWith(formatPreferences().locale, value);
}

/** Integer minor units (4999) → major-unit string for form inputs ("49.99"). */
export function minorToMajor(minor: number, currency: string): string {
  const digits = minorFractionDigits(currency);
  return (minor / 10 ** digits).toFixed(digits);
}

/** Thousands separators removed, or `null` where the comma is ambiguous.
 *
 * The mirror of `strip_numeric_grouping` in `backend/app/services/numeric.py`;
 * `__fixtures__/money-cases.json` is read by both suites so the two cannot drift.
 * A comma used to be stripped unconditionally on both sides, which made `12,34` —
 * how much of the world writes 12.34 — into 1234 major units, a hundredfold error.
 * It is accepted only where it cannot be a decimal point: grouped in threes, and
 * never after the decimal point. */
function degroup(text: string, digits: number): string | null {
  if (!text.includes(",")) return text;
  const point = text.indexOf(".");
  const head = point === -1 ? text : text.slice(0, point);
  const tail = point === -1 ? "" : text.slice(point);
  if (tail.includes(",") || !/^[+-]?\d{1,3}(?:,\d{3})+$/.test(head)) return null;
  // A *lone* group is grammatical and still ambiguous: "1,234" is equally a
  // European spelling of 1.234, and in KWD those are 1,234,000 fils and 1234 fils.
  // Only the exponent settles it, and only one way — with no minor unit there is
  // nowhere for a decimal reading to land, so "1,234" JPY is plainly ¥1234.
  if (digits !== 0 && (text.match(/,/g) ?? []).length === 1 && point === -1) return null;
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
  const text = degroup(
    (typeof major === "number" ? String(major) : major).replace(/\s/g, ""),
    digits,
  );
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

/** A bare `YYYY-MM-DD` — a calendar date with no time attached. */
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/** The zone a value renders in. A plain calendar date names a day, not an
 *  instant: it renders as that day verbatim (via UTC, the zone its midnight
 *  parse landed in), never shifted into the instance zone — the presentation
 *  twin of #114's import rule. An instant renders in the instance's zone. */
function renderZone(iso: string, prefs: FormatPreferences): string | undefined {
  return DATE_ONLY.test(iso) ? "UTC" : prefs.timeZone;
}

export function formatDateWith(prefs: FormatPreferences, iso: string): string {
  const value = new Date(iso);
  try {
    if (prefs.dateStyle === "locale") {
      // The locale's own default rendering — what `toLocaleDateString()` gave
      // before #27, now pinned to the instance locale and zone.
      return value.toLocaleDateString(prefs.locale, { timeZone: renderZone(iso, prefs) });
    }
    return new Intl.DateTimeFormat(prefs.locale, {
      dateStyle: prefs.dateStyle as Intl.DateTimeFormatOptions["dateStyle"],
      timeZone: renderZone(iso, prefs),
    }).format(value);
  } catch {
    // A locale or zone this browser can't serve must degrade, not white-screen.
    return value.toLocaleDateString();
  }
}

export function formatDate(iso: string): string {
  return formatDateWith(formatPreferences(), iso);
}

export function formatDateTimeWith(prefs: FormatPreferences, iso: string): string {
  const value = new Date(iso);
  const hourCycle =
    prefs.hourCycle === "locale"
      ? undefined
      : (prefs.hourCycle as Intl.DateTimeFormatOptions["hourCycle"]);
  try {
    if (prefs.dateStyle === "locale") {
      return value.toLocaleString(prefs.locale, { timeZone: renderZone(iso, prefs), hourCycle });
    }
    return new Intl.DateTimeFormat(prefs.locale, {
      dateStyle: prefs.dateStyle as Intl.DateTimeFormatOptions["dateStyle"],
      // The setting names a date style; the time part stays compact beside it.
      timeStyle: "short",
      timeZone: renderZone(iso, prefs),
      hourCycle,
    }).format(value);
  } catch {
    return value.toLocaleString();
  }
}

export function formatDateTime(iso: string): string {
  return formatDateTimeWith(formatPreferences(), iso);
}

export function todayISO(): string {
  // Local date, not UTC — an evening order in AEST is not "yesterday".
  // Deliberately the *browser's* calendar, not the instance zone (#27): these
  // entry-side helpers feed the #93 contract, where a picked date travels as
  // midnight in the browser's own offset. Presentation reads instance settings;
  // data entry keeps meaning what the person at the keyboard sees.
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

/** The date part of a stored timestamp, on the viewer's own calendar — the same
 *  calendar `todayISO` reads, so a receipt stamped "now" renders as today. */
export function isoToLocalDateInput(iso: string): string {
  const value = new Date(iso);
  value.setMinutes(value.getMinutes() - value.getTimezoneOffset());
  return value.toISOString().slice(0, 10);
}

/** The browser's UTC offset in minutes at local midnight of `date` (yyyy-mm-dd) —
 *  at that date, not today, so a backdate across a DST boundary keeps the offset
 *  that was actually in force. */
function offsetAtLocalMidnight(date: string): number {
  const [year, month, day] = date.split("-").map(Number);
  return -new Date(year, month - 1, day).getTimezoneOffset();
}

/** A picked calendar date as an offset-aware instant: midnight local time with
 *  the browser's own offset written out, never converted to Z (#93). The server
 *  judges "is this future?" as a calendar date in the instant's *own* offset, so
 *  the offset carries the user's meaning — "it arrived on this date, here" —
 *  and folding it into UTC would shift the asserted date for half the world. */
export function localMidnightISO(
  date: string,
  offsetMinutes: number = offsetAtLocalMidnight(date),
): string {
  const sign = offsetMinutes < 0 ? "-" : "+";
  const magnitude = Math.abs(offsetMinutes);
  const hours = String(Math.floor(magnitude / 60)).padStart(2, "0");
  const minutes = String(magnitude % 60).padStart(2, "0");
  return `${date}T00:00:00${sign}${hours}:${minutes}`;
}
