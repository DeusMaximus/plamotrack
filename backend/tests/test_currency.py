"""ISO 4217 minor units (#6).

The exponent decides what a stored integer is worth, so these are value-meaning
tests, not formatting ones: a wrong answer here doesn't look wrong, it looks like
a different price.

The shared cases come from `frontend/src/lib/__fixtures__/money-cases.json`, which
`format.test.ts` reads as well — a currency that converts one way here and another
way in the browser fails on both sides rather than reaching the database. Add a
cross-layer case to that file; keep Python-only ones here.
"""

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import currency

_FRONTEND = Path(__file__).resolve().parents[2] / "frontend/src/lib"
_MIRROR = _FRONTEND / "currency.ts"
_CASES = json.loads((_FRONTEND / "__fixtures__/money-cases.json").read_text(encoding="utf-8"))


def _ids(cases: list[dict], *fields: str) -> list[str]:
    return [" ".join(str(case[field]) for field in fields) for case in cases]


@pytest.mark.parametrize(
    "case", _CASES["minor_fraction_digits"], ids=_ids(_CASES["minor_fraction_digits"], "currency")
)
def test_minor_fraction_digits(case):
    assert currency.minor_fraction_digits(case["currency"]) == case["digits"]


@pytest.mark.parametrize("code", ["", None])
def test_missing_currency_takes_the_default(code):
    """No frontend counterpart: its callers are typed to always pass a code."""
    assert currency.minor_fraction_digits(code) == currency.DEFAULT_MINOR_UNITS


@pytest.mark.parametrize(
    "case", _CASES["major_to_minor"], ids=_ids(_CASES["major_to_minor"], "major", "currency")
)
def test_major_to_minor(case):
    assert currency.major_to_minor(case["major"], case["currency"]) == case["minor"]


@pytest.mark.parametrize(
    "case", _CASES["minor_to_major"], ids=_ids(_CASES["minor_to_major"], "minor", "currency")
)
def test_minor_to_major(case):
    assert currency.minor_to_major(case["minor"], case["currency"]) == case["major"]


@pytest.mark.parametrize("code", _CASES["round_trips"]["currencies"])
@pytest.mark.parametrize("minor", _CASES["round_trips"]["minor_amounts"])
def test_round_trips_without_changing_value(minor, code):
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
