"""ISO 4217 minor units: what an integer money column actually counts (§6).

A currency's exponent is a property of the currency, not of the reader — a dinar is
1000 fils whether the interface is in English or Japanese — so this table is not
locale data and does not wait on the i18n milestone.

It is deliberately **not** derived from CLDR (`Intl.NumberFormat` in the browser,
`babel` here). CLDR publishes *presentation* digits that follow everyday practice
and move between ICU releases: as of ICU 78 it reports 0 digits for IQD, HUF, COP
and MGA, where ISO 4217 gives 3, 2, 2 and 2. An exponent read from the runtime
means a browser update can change what an already-stored integer is worth, which
is the precise failure §6 exists to prevent. So the table is pinned here, and the
frontend is pinned to the same one — `frontend/src/lib/currency.ts` mirrors it and
`tests/test_currency.py` compares the two so they cannot drift.

Presentation is a separate question and stays open for M5.1: a Hungarian reader may
well want forint shown without decimals. That is a formatting choice layered on top
of a stored amount, not a change to what the stored integer counts.
"""

import re
from decimal import Decimal

#: A digit run grouped in threes, which is the only reading of a comma this parser
#: will accept: "1,299" and "1,234,567", never "12,34".
_GROUPED_INTEGER = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+")


def strip_numeric_grouping(raw: str) -> str:
    """Numeric text with thousands separators removed, or a ValueError saying why not.

    Shared by `spec.parse_int`, `spec.parse_decimal` and `major_to_minor` so the three
    cannot disagree about what a cell means — the same rule also lives in
    `frontend/src/lib/majorToMinor`, held to it by `__fixtures__/money-cases.json`.

    Two characters used to be read generously and both changed the number:

    * **A comma was stripped unconditionally**, so `12,34` — how most of Europe writes
      12.34 — became 1234 major units and stored as a hundredfold error. A comma is
      genuinely ambiguous between grouping and decimal separator, so it is accepted
      only where it *cannot* be a decimal point: grouped in threes, with no comma
      after the decimal point. `1,299.50` and `1,234` still read as they look;
      `12,34` and `1.234,56` are now refused rather than guessed at.
    * **`Decimal()` honours Python's numeric-literal underscores**, so `1_000` parsed
      as 1000 — a number no spreadsheet wrote and no human typed.
    """
    value = raw.strip()
    if "_" in value:
        raise ValueError(f"'{raw}' isn't a number — remove the underscores")
    if "," not in value:
        return value
    head, point, tail = value.partition(".")
    if "," in tail or not _GROUPED_INTEGER.fullmatch(head):
        raise ValueError(
            f"a comma in '{raw}' is ambiguous — it reads as a thousands separator to "
            "this importer and as a decimal point to much of the world. Write it "
            "without one, or as a decimal point."
        )
    return head.replace(",", "") + point + tail


#: Currencies whose exponent is not 2. Everything else in ISO 4217 has two minor
#: units, so listing only the exceptions keeps the table short enough to audit.
MINOR_UNITS: dict[str, int] = {
    # No minor unit at all — the major unit is already the smallest.
    "BIF": 0,
    "CLP": 0,
    "DJF": 0,
    "GNF": 0,
    "ISK": 0,
    "JPY": 0,
    "KMF": 0,
    "KRW": 0,
    "PYG": 0,
    "RWF": 0,
    "UGX": 0,
    "UYI": 0,
    "VND": 0,
    "VUV": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
    # Three — the Gulf and North African dinars, plus the Iraqi one that CLDR
    # rounds away because fils are no longer spent in practice.
    "BHD": 3,
    "IQD": 3,
    "JOD": 3,
    "KWD": 3,
    "LYD": 3,
    "OMR": 3,
    "TND": 3,
    # Four — both are unit-of-account codes rather than notes and coins.
    "CLF": 4,
    "UYW": 4,
}

#: What a currency has unless the table above says otherwise.
DEFAULT_MINOR_UNITS = 2

#: Shape of a currency code on the way in. Deliberately not a membership test against
#: KNOWN_CURRENCIES — see that set's note on why an unrecognised code is accepted.
CURRENCY_CODE_PATTERN = r"^[A-Z]{3}$"

#: Codes in current use per ISO 4217. Only used to tell "a currency we don't
#: recognise" from "a currency with two decimals" — an unknown code is still
#: accepted everywhere, because rejecting one would strand anyone already storing
#: it. The CSV importer warns instead, where a human sees it before applying.
KNOWN_CURRENCIES = frozenset(
    {
        "AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG", "AZN", "BAM", "BBD", "BDT",
        "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BRL", "BSD", "BTN", "BWP", "BYN", "BZD", "CAD",
        "CDF", "CHF", "CLF", "CLP", "CNY", "COP", "CRC", "CUC", "CUP", "CVE", "CZK", "DJF", "DKK",
        "DOP", "DZD", "EGP", "ERN", "ETB", "EUR", "FJD", "FKP", "GBP", "GEL", "GHS", "GIP", "GMD",
        "GNF", "GTQ", "GYD", "HKD", "HNL", "HRK", "HTG", "HUF", "IDR", "ILS", "INR", "IQD", "IRR",
        "ISK", "JMD", "JOD", "JPY", "KES", "KGS", "KHR", "KMF", "KPW", "KRW", "KWD", "KYD", "KZT",
        "LAK", "LBP", "LKR", "LRD", "LSL", "LYD", "MAD", "MDL", "MGA", "MKD", "MMK", "MNT", "MOP",
        "MRU", "MUR", "MVR", "MWK", "MXN", "MYR", "MZN", "NAD", "NGN", "NIO", "NOK", "NPR", "NZD",
        "OMR", "PAB", "PEN", "PGK", "PHP", "PKR", "PLN", "PYG", "QAR", "RON", "RSD", "RUB", "RWF",
        "SAR", "SBD", "SCR", "SDG", "SEK", "SGD", "SHP", "SLE", "SLL", "SOS", "SRD", "SSP", "STN",
        "SVC", "SYP", "SZL", "THB", "TJS", "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS", "UAH",
        "UGX", "USD", "UYI", "UYU", "UYW", "UZS", "VES", "VND", "VUV", "WST", "XAF", "XCD", "XCG",
        "XDR", "XOF", "XPF", "XSU", "YER", "ZAR", "ZMW", "ZWG", "ZWL",
    }
)  # fmt: skip


def normalise_code(currency_code: str | None) -> str:
    return (currency_code or "").strip().upper()


def is_known_currency(currency_code: str | None) -> bool:
    return normalise_code(currency_code) in KNOWN_CURRENCIES


def minor_fraction_digits(currency_code: str | None) -> int:
    """How many decimal places separate the major unit from the stored integer.

    An unrecognised code gets the two-decimal default. That is a guess, and callers
    positioned to say so out loud should — see `is_known_currency`.
    """
    return MINOR_UNITS.get(normalise_code(currency_code), DEFAULT_MINOR_UNITS)


def major_to_minor(major: str | Decimal, currency_code: str | None) -> int:
    """ "49.99" + AUD -> 4999. Rounds half-up, like the money it represents."""
    value = major if isinstance(major, Decimal) else Decimal(strip_numeric_grouping(str(major)))
    scaled = value * (10 ** minor_fraction_digits(currency_code))
    return int(scaled.quantize(Decimal(1), rounding="ROUND_HALF_UP"))


def minor_to_major(minor: int, currency_code: str | None) -> str:
    digits = minor_fraction_digits(currency_code)
    if digits == 0:
        return str(minor)
    return f"{Decimal(minor) / (10**digits):.{digits}f}"
