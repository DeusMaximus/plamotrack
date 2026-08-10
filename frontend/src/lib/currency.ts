/**
 * ISO 4217 minor units — the mirror of `backend/app/services/currency.py`.
 *
 * Deliberately not `Intl.NumberFormat().resolvedOptions()`, which is where this
 * used to come from. Intl reports CLDR *presentation* digits: they follow everyday
 * practice and move between ICU releases, so Chromium 151 says IQD, HUF, COP and
 * MGA have no decimals where ISO 4217 gives 3, 2, 2 and 2. Since the exponent is
 * what turns a stored integer into an amount, sourcing it from the browser means a
 * browser update can change what an already-saved order is worth.
 *
 * Keep this table byte-identical in meaning to the Python one — a backend test
 * reads this file and fails if the two disagree.
 */
export const MINOR_UNITS: Record<string, number> = {
  // No minor unit at all — the major unit is already the smallest.
  BIF: 0,
  CLP: 0,
  DJF: 0,
  GNF: 0,
  ISK: 0,
  JPY: 0,
  KMF: 0,
  KRW: 0,
  PYG: 0,
  RWF: 0,
  UGX: 0,
  UYI: 0,
  VND: 0,
  VUV: 0,
  XAF: 0,
  XOF: 0,
  XPF: 0,
  // Three — the Gulf and North African dinars, plus the Iraqi one that CLDR
  // rounds away because fils are no longer spent in practice.
  BHD: 3,
  IQD: 3,
  JOD: 3,
  KWD: 3,
  LYD: 3,
  OMR: 3,
  TND: 3,
  // Four — both are unit-of-account codes rather than notes and coins.
  CLF: 4,
  UYW: 4,
};

/** What a currency has unless the table above says otherwise. */
export const DEFAULT_MINOR_UNITS = 2;

/** Minor-unit digits for a currency (JPY → 0, AUD → 2, KWD → 3). */
export function minorFractionDigits(currency: string): number {
  return MINOR_UNITS[currency?.trim().toUpperCase()] ?? DEFAULT_MINOR_UNITS;
}

/** The `step` a money input needs so the currency's smallest unit is typeable. */
export function stepFor(currency: string): string {
  const digits = minorFractionDigits(currency);
  return digits === 0 ? "1" : `0.${"0".repeat(digits - 1)}1`;
}
