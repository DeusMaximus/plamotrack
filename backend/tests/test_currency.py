"""ISO 4217 minor units (#6).

The exponent decides what a stored integer is worth, so these are value-meaning
tests, not formatting ones: a wrong answer here doesn't look wrong, it looks like
a different price.
"""

import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import currency

_MIRROR = Path(__file__).resolve().parents[2] / "frontend/src/lib/currency.ts"


@pytest.mark.parametrize(
    ("code", "digits"),
    [
        ("JPY", 0),  # zero-decimal: yen are already minor units
        ("AUD", 2),
        ("USD", 2),
        ("KWD", 3),  # 1000 fils
        ("CLF", 4),
        # The four where CLDR — and so `Intl` in the browser, which is where the
        # frontend used to read this — disagrees with ISO 4217. Pinned so nobody
        # "corrects" the table back to what a browser reports.
        ("IQD", 3),
        ("HUF", 2),
        ("COP", 2),
        ("MGA", 2),
        # Unknown codes take the documented default rather than erroring.
        ("ZZZ", 2),
        ("", 2),
        (None, 2),
    ],
)
def test_minor_fraction_digits(code, digits):
    assert currency.minor_fraction_digits(code) == digits


@pytest.mark.parametrize(
    ("major", "code", "expected"),
    [
        ("49.99", "AUD", 4999),
        ("1200", "JPY", 1200),
        ("1,299.50", "AUD", 129950),  # spreadsheets love a thousands separator
        ("0.5", "USD", 50),
        ("1.234", "KWD", 1234),  # the headline case: was 123
        ("1.2345", "CLF", 12345),
        ("0.001", "KWD", 1),
        ("38.50", "JPY", 39),  # no minor unit to hold the half
        ("1.005", "AUD", 101),  # half-up, away from zero
    ],
)
def test_major_to_minor(major, code, expected):
    assert currency.major_to_minor(major, code) == expected


@pytest.mark.parametrize(
    ("minor", "code", "expected"),
    [
        (4999, "AUD", "49.99"),
        (1200, "JPY", "1200"),
        (1234, "KWD", "1.234"),  # was "12.34"
        (12345, "CLF", "1.2345"),
        (1, "KWD", "0.001"),
    ],
)
def test_minor_to_major(minor, code, expected):
    assert currency.minor_to_major(minor, code) == expected


@pytest.mark.parametrize("code", ["JPY", "AUD", "KWD", "CLF", "IQD", "ZZZ"])
@pytest.mark.parametrize("minor", [0, 1, 7, 4999, 123456])
def test_round_trips_without_changing_value(code, minor):
    """Export then re-import has to land on the integer it started from."""
    assert currency.major_to_minor(currency.minor_to_major(minor, code), code) == minor


def test_decimal_input_is_not_routed_through_float():
    assert currency.major_to_minor(Decimal("8.115"), "AUD") == 812


def test_known_currencies_cover_every_code_in_the_exponent_table():
    """A code we bothered to give an exponent is one we recognise, by definition."""
    assert set(currency.MINOR_UNITS) <= currency.KNOWN_CURRENCIES


@pytest.mark.parametrize(
    ("code", "known"),
    [("AUD", True), ("kwd", True), ("CLF", True), ("ZZZ", False), ("AUS", False), (None, False)],
)
def test_is_known_currency(code, known):
    assert currency.is_known_currency(code) is known


def test_frontend_mirrors_the_same_table():
    """The two tables are hand-kept copies; this is what stops them drifting.

    Sourcing the exponent from the runtime is what #6 was, so "just ask Intl" is
    not available as a fix if this ever fails — update the copy instead.
    """
    text = _MIRROR.read_text(encoding="utf-8")
    body = re.search(r"MINOR_UNITS:\s*Record<string,\s*number>\s*=\s*\{(.*?)\n\};", text, re.S)
    assert body, f"no MINOR_UNITS table found in {_MIRROR}"

    mirrored = {code: int(digits) for code, digits in re.findall(r"(\w{3}):\s*(\d)", body.group(1))}
    assert mirrored == currency.MINOR_UNITS

    default = re.search(r"DEFAULT_MINOR_UNITS\s*=\s*(\d)", text)
    assert default and int(default.group(1)) == currency.DEFAULT_MINOR_UNITS
