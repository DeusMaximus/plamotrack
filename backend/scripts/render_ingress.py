#!/usr/bin/env python
"""Regenerate the generated regions of the nginx ingress template from the route
policy registry (§5.5, rule 12).

    uv run python scripts/render_ingress.py           # write the template
    uv run python scripts/render_ingress.py --check    # exit 1 if it would change

The `/api/` alias rejection list (`API_ALIAS_REJECTIONS`) and the body budgets
(`max_body_bytes` on the anonymous routes; #221 item 1) live in
`app/auth/registry.py`; this writes each into
`frontend/nginx/default.conf.template` between the registry's markers, so the
template is a generated artifact and a change to a declaration that is not
re-rendered fails `tests/test_ingress_generation.py`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.auth.registry import (
    NGINX_BODY_LIMITS_BEGIN,
    NGINX_BODY_LIMITS_END,
    NGINX_REJECTIONS_BEGIN,
    NGINX_REJECTIONS_END,
    render_api_alias_rejections,
    render_body_limits,
)

TEMPLATE = Path(__file__).resolve().parents[2] / "frontend/nginx/default.conf.template"
INDENT = "    "


#: The generated regions, each (begin marker, end marker, renderer).
REGIONS = (
    (NGINX_REJECTIONS_BEGIN, NGINX_REJECTIONS_END, render_api_alias_rejections),
    (NGINX_BODY_LIMITS_BEGIN, NGINX_BODY_LIMITS_END, render_body_limits),
)


def render_region(current: str, begin_marker: str, end_marker: str, render) -> str:
    begin = f"{INDENT}{begin_marker}"
    end = f"{INDENT}{end_marker}"
    if begin not in current or end not in current:
        raise SystemExit(
            f"markers not found in {TEMPLATE}; add:\n{begin}\n    …\n{end}\naround the block"
        )
    head, rest = current.split(begin, 1)
    _, tail = rest.split(end, 1)
    block = f"{begin}\n{render(INDENT)}\n{end}"
    return f"{head}{block}{tail}"


def render_template(current: str) -> str:
    for begin_marker, end_marker, render in REGIONS:
        current = render_region(current, begin_marker, end_marker, render)
    return current


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if regeneration would change it"
    )
    args = parser.parse_args(argv)
    current = TEMPLATE.read_text(encoding="utf-8")
    rendered = render_template(current)
    if args.check:
        if rendered != current:
            print(f"{TEMPLATE} is stale — run: uv run python scripts/render_ingress.py")
            return 1
        print("nginx template is up to date")
        return 0
    TEMPLATE.write_text(rendered, encoding="utf-8")
    print(f"wrote {TEMPLATE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
