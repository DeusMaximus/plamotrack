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

from app.services.numeric import is_lone_group, strip_numeric_grouping

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


#: ASCII on purpose — `[A-Za-z]` in `re`, never `str.isalpha()`, which is
#: Unicode-wide: 'ÅUD' is three "letters" to isalpha and no currency to ISO 4217.
_CODE_SHAPE = re.compile(r"[A-Za-z]{3}")


def require_currency_code(raw: str) -> str:
    """Three ASCII letters, uppercased — the §6 shape, or a ValueError naming it.

    The one shape test every writer shares. It lives here because the CSV
    importer once judged "three letters" with `isalpha()` while `PATCH /settings`
    used an ASCII regex, and the code the REST surface refused imported cleanly
    and was stamped into new conversion snapshots (PR #159 review, P2).
    Deliberately not a membership test against KNOWN_CURRENCIES — see that set's
    note on why an unrecognised code is accepted everywhere.
    """
    value = raw.strip()
    if not _CODE_SHAPE.fullmatch(value):
        raise ValueError(f"'{raw}' is not a 3-letter ISO 4217 currency code")
    return value.upper()


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
    """ "49.99" + AUD -> 4999. Rounds half-up, like the money it represents.

    A **lone grouped** amount is refused unless the currency has no minor unit.
    `1,234` is valid grouping and an equally valid European spelling of `1.234`, and
    in KWD those are 1,234,000 fils and the 1234 fils §6 exists over. The text cannot
    settle it; only the exponent can, and only in one direction — with no subunit
    there is nowhere for a decimal reading to land, so `1,234` JPY is plainly ¥1234.

    A `Decimal` argument has already lost the comma, so its caller is the one holding
    the raw cell and has to make this call itself. `importing._apply_money_alternates`
    does, through the same `is_lone_group` predicate.
    """
    if (
        not isinstance(major, Decimal)
        and is_lone_group(str(major))
        and minor_fraction_digits(currency_code) != 0
    ):
        raise ValueError(
            f"a comma is ambiguous in {normalise_code(currency_code) or 'this currency'} — "
            f"'{major}' reads as a thousands separator here and a decimal point to much "
            "of the world. Write it with a decimal point, or with no separator at all."
        )
    value = major if isinstance(major, Decimal) else Decimal(strip_numeric_grouping(str(major)))
    scaled = value * (10 ** minor_fraction_digits(currency_code))
    return int(scaled.quantize(Decimal(1), rounding="ROUND_HALF_UP"))


def minor_to_major(minor: int, currency_code: str | None) -> str:
    digits = minor_fraction_digits(currency_code)
    if digits == 0:
        return str(minor)
    return f"{Decimal(minor) / (10**digits):.{digits}f}"
