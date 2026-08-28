"""Readers for the #26 diagnostic shape, shared by every suite that inspects a
preview.

Since #26 a planned row's problems, a plan's warnings and blocking errors, and
the stock note are `{code, params, detail}` diagnostics rather than bare
strings. The suites' assertions are about the *English* — which row was
refused, what the operator is told — so these helpers read the `detail` back
out, in both the wire shape (dicts, from a JSON response) and the model shape
(`Diagnostic` instances, from the service layer). `row_error` reconstructs the
pre-#26 single string exactly ("; "-joined), so an assertion written against
the old field keeps its meaning verbatim. Code/params behaviour has its own
suite (`test_import_diagnostics.py`); nothing here should be used to assert a
code.
"""

from typing import Any


def detail(diagnostic: Any) -> str:
    return diagnostic["detail"] if isinstance(diagnostic, dict) else diagnostic.detail


def code(diagnostic: Any) -> str:
    return diagnostic["code"] if isinstance(diagnostic, dict) else diagnostic.code


def details(diagnostics: Any) -> list[str]:
    return [detail(entry) for entry in diagnostics]


def codes(diagnostics: Any) -> list[str]:
    return [code(entry) for entry in diagnostics]


def _field(row: Any, name: str) -> Any:
    return row[name] if isinstance(row, dict) else getattr(row, name)


def row_error(row: Any) -> str | None:
    """The pre-#26 `error` string: every diagnostic's detail, "; "-joined, or
    None for a clean row — byte-identical to what the old field held."""
    errors = _field(row, "errors")
    return "; ".join(details(errors)) if errors else None


def row_messages(row: Any) -> list[str]:
    """The pre-#26 `messages` list: each diagnostic's detail, in order."""
    return details(_field(row, "messages"))
