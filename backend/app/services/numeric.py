"""How numeric text is read, and what an integer column can hold.

Two rules that several layers need and none of them owns. They live here rather than
beside any one caller because the failure mode is not *missing* a check — input and
derivation boundaries are genuinely plural — but two boundaries growing slightly
different rules and disagreeing about what a cell means.

`frontend/src/lib/format.ts` mirrors the grouping rule, and
`__fixtures__/money-cases.json` is read by both suites so the two cannot drift.
"""

import re

#: PostgreSQL `integer`. Twelve columns in the schema are int4 and every one of them
#: can be reached from a CSV cell.
INT4_MIN, INT4_MAX = -2_147_483_648, 2_147_483_647

#: A digit run grouped in threes — the only reading of a comma this parser accepts:
#: "1,299" and "1,234,567", never "12,34".
_GROUPED_INTEGER = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+")


def require_int4(value: int, label: str) -> int:
    """`value`, or a ValueError naming the column it came from.

    One implementation with several callers, deliberately: `parse_int` guards the
    declared column and `_apply_money_alternates` guards the scaled product, and
    those are different boundaries rather than a duplicated check. What must not
    happen is each of them growing its own idea of the bound.
    """
    if not INT4_MIN <= value <= INT4_MAX:
        raise ValueError(
            f"{label} is out of range — whole numbers here go from {INT4_MIN:,} to {INT4_MAX:,}"
        )
    return value


def strip_numeric_grouping(raw: str) -> str:
    """Numeric text with thousands separators removed, or a ValueError saying why not.

    Two characters used to be read generously and both changed the number:

    * **A comma was stripped unconditionally**, so `12,34` — how much of the world
      writes 12.34 — became 1234 major units and stored a hundredfold error. A comma
      is accepted only where it cannot also be a decimal point: grouped in threes,
      with no comma after the decimal point.
    * **`Decimal()` honours Python's numeric-literal underscores**, so `1_000` parsed
      as 1000 — a number no spreadsheet wrote and no human typed.

    Valid grouping is not the whole test for a *major-unit amount*: see
    `is_lone_group`, which the currency then has to settle.
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


def is_lone_group(raw: str) -> bool:
    """Whether `raw` is grouped in a way a decimal separator could also explain.

    `1,234` is valid grouping *and* a valid European spelling of 1.234, and the two
    differ by a thousand. Nothing about the text settles it — only the currency can,
    because the decimal reading needs a subunit to land in (`§6`). `1,234.56` and
    `1,234,567` are not lone groups: a decimal point already present, or a second
    comma, rules the decimal reading out.

    Deliberately not folded into `strip_numeric_grouping`: that function is the
    grammar and knows nothing about currencies, and integer columns — where a
    fractional reading is invalid by definition — accept a lone group happily.
    """
    return raw.count(",") == 1 and "." not in raw
