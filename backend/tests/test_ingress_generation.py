"""The nginx `/api/` rejection list is generated from the registry (§5.5, rule 12;
#187).

Item 1 (#186) typed the four `/api/mcp`, `/api/.well-known`, `/api/openapi.json`
and `/api/readyz` rejections into the template by hand; M6-2 makes them a
generated artifact of `app/auth/registry.py` (`API_ALIAS_REJECTIONS`), rendered
by `scripts/render_ingress.py`. This holds the two ends together: the template's
generated region must equal what the registry renders (so an edit to the
declaration that is not re-rendered is red), and every root-canonical *live*
route must be covered by a rejection (so a new one cannot slip in unlisted). The
packaged-stack behaviour of these 404s is proven separately by
`ingress_matrix.py` (T2, CI Integration); the blocks are byte-for-byte what item
1 shipped, so that behaviour is unchanged.
"""

import re
from pathlib import Path

from app.auth.registry import (
    API_ALIAS_REJECTIONS,
    MCP_TRANSPORT_POLICY,
    NGINX_REJECTIONS_BEGIN,
    NGINX_REJECTIONS_END,
    build_route_index,
    render_api_alias_rejections,
)
from app.main import app

TEMPLATE = Path(__file__).resolve().parents[2] / "frontend/nginx/default.conf.template"
INDENT = "    "


def _generated_region() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    begin = f"{INDENT}{NGINX_REJECTIONS_BEGIN}"
    end = f"{INDENT}{NGINX_REJECTIONS_END}"
    assert begin in text and end in text, "the generation markers are missing from the template"
    inner = text.split(begin, 1)[1].split(end, 1)[0]
    # Between the marker lines, minus the surrounding blank lines, is exactly the
    # rendered block.
    return inner.strip("\n")


def test_the_template_region_equals_the_registry_render():
    """The generated region is byte-for-byte the registry's render — the drift
    guard. If this fails, run `uv run python scripts/render_ingress.py`."""
    assert _generated_region() == render_api_alias_rejections(INDENT)


def test_every_declared_rejection_appears_in_the_template():
    """A positive pin beside the equality: the four namespaces really are 404 in
    the template, so an empty or truncated render could not pass unnoticed."""
    region = _generated_region()
    for rejection in API_ALIAS_REJECTIONS:
        operator = "=" if rejection.exact else "^~"
        assert f"location {operator} /api{rejection.namespace} {{" in region
    # the whole rewrite family reaches these after normalisation; the four are all
    assert {r.namespace for r in API_ALIAS_REJECTIONS} == {
        "/mcp",
        "/.well-known",
        "/openapi.json",
        "/readyz",
    }


def test_every_root_canonical_live_route_is_covered_by_a_rejection():
    """The enumeration half: a route whose external spelling is a root path (not
    under `/api/`) is reachable under `/api/` by the generic rewrite, so it owes a
    rejection here. A new such route without one fails this — the registry, not a
    reviewer, is what notices (§5.5, one spelling per family)."""
    index = build_route_index(app)
    spellings = {spelling for policy in index.by_endpoint.values() for spelling in policy.spellings}
    spellings |= set(MCP_TRANSPORT_POLICY.spellings)

    def covered(spelling: str) -> bool:
        return any(
            spelling == r.namespace or spelling.startswith(r.namespace + "/")
            for r in API_ALIAS_REJECTIONS
        )

    for spelling in spellings:
        if not spelling.startswith("/") or spelling.startswith("/api/"):
            continue  # under /api/ (or the "internal" marker) — not a root alias
        assert covered(spelling), f"root-canonical spelling {spelling!r} has no /api rejection"


def test_the_render_is_deterministic():
    assert render_api_alias_rejections(INDENT) == render_api_alias_rejections(INDENT)


def test_the_four_declared_rate_limit_families_have_separate_keys_and_bursts():
    """M6-8 / T8: an empty map key exempts every other family; the server-level
    snapshot preserves nginx's normalised path before `/api/` is rewritten."""
    text = TEMPLATE.read_text(encoding="utf-8")
    expected_paths = {
        "$plamotrack_family_2_key": "/api/auth/session",
        "$plamotrack_family_3_key": "/api/auth/(setup|login|logout|oidc/start|oidc/callback)",
        "$plamotrack_family_8_key": "/mcp/(authorize|token|register|consent|auth/callback|revoke)",
        "$plamotrack_family_9_key": "/api/healthz",
    }
    assert "set $plamotrack_normalized_request_uri $uri;" in text
    for key, path in expected_paths.items():
        assert f"map $plamotrack_normalized_request_uri {key} {{" in text
        assert path in text
        zone = key.removeprefix("$").removesuffix("_key")
        assert f"limit_req_zone {key} zone={zone}:" in text
        assert f"limit_req zone={zone} burst=" in text
    assert "limit_req_status 429;" in text
    assert "real_ip_header X-Forwarded-For;" in text
    assert "real_ip_recursive on;" in text
    assert "map $request_uri $plamotrack_family_" not in text
    # Every path proxied to the unpublished API overwrites the internal address
    # header; a client-supplied value can never pass through nginx unchanged.
    proxy_blocks = re.findall(r"location [^{]+\{([^}]+)\}", text)
    proxy_blocks = [block for block in proxy_blocks if "proxy_pass " in block]
    assert len(proxy_blocks) == 7
    for block in proxy_blocks:
        assert "proxy_set_header X-Plamotrack-Client-Address $remote_addr;" in block
        assert "limit_req " not in block, "location limits replace the shared server limits"
    assert len(re.findall(r"^limit_req_zone ", text, re.M)) == 4


def test_the_two_mcp_spellings_share_one_family_configuration():
    """The bare `/mcp` block is the ingress-only alias of `/mcp/` (§5.5, family 7),
    and what an alias would shed is the family's per-location configuration —
    buffering, timeouts, the cleared hop-by-hop header. Claude web posts to the
    bare spelling (#190), so the two blocks must carry the same settings; only
    the rewrite that makes it an alias may differ. (The 1 h timeouts are the
    family's settings, not a measured need: the SDK's streams ping every 15 s.)"""
    text = TEMPLATE.read_text(encoding="utf-8")
    blocks = {
        match.group(1): match.group(2)
        for match in re.finditer(r"location (= /mcp|/mcp/) \{([^}]+)\}", text)
    }
    assert set(blocks) == {"= /mcp", "/mcp/"}
    family_settings = (
        "proxy_buffering off;",
        "proxy_cache off;",
        "proxy_read_timeout 1h;",
        "proxy_send_timeout 1h;",
        'proxy_set_header Connection "";',
        "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        "proxy_set_header X-Forwarded-Proto $scheme;",
    )
    for spelling, block in blocks.items():
        for setting in family_settings:
            assert setting in block, f"location {spelling} lacks {setting}"

    def directives(block: str) -> set[str]:
        lines = {line.strip() for line in block.splitlines()}
        return {line for line in lines if line and not line.startswith("#")}

    assert "rewrite ^ /mcp/ break;" in directives(blocks["= /mcp"])
    assert directives(blocks["= /mcp"]) - {"rewrite ^ /mcp/ break;"} == directives(blocks["/mcp/"])
