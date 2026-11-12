"""A settings refusal names the setting, and never echoes a secret (#301, rule 14).

pydantic's `ValidationError` text carries `input_value=`: for a model-level
validator the whole settings input, truncated to its head and tail, so whichever
secrets sat at either end were printed, and for a field validator that field's own
value. `Settings` is built by the API, `alembic` and the recovery commands, so that
text is the container log. Each refusal is driven with every secret the instance
holds set in the environment, as `.env` sets them.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

DB_PASSWORD = "pw-4e1b-9c77-db"
CLIENT_SECRET = "cs-8d20-a5f3-oidc"
SIGNING_KEY = "5f3a" * 16

#: Every secret a refusal could echo, set the way `.env` sets it. DATABASE_URL is
#: blanked so the assembled URL, which carries the password, is in play.
SECRETS = {
    "DATABASE_URL": "",
    "POSTGRES_PASSWORD": DB_PASSWORD,
    "OIDC_CLIENT_SECRET": CLIENT_SECRET,
    "MCP_OAUTH_SIGNING_KEY": SIGNING_KEY,
}

#: (label, settings that make it refuse, the setting its message must name). Two
#: model-level refusals, whose echo was the whole input dict, and the field-level
#: one on a secret, whose echo was the malformed value itself.
REFUSALS = [
    (
        "oidc-missing",
        {"AUTH_MODE": "oidc", "PUBLIC_BASE_URL": "https://plamotrack.example"},
        "OIDC_ISSUER",
    ),
    (
        "oidc-plain-http",
        {
            "AUTH_MODE": "oidc",
            "OIDC_ISSUER": "https://id.example.com",
            "OIDC_CLIENT_ID": "plamotrack",
            "PUBLIC_BASE_URL": "http://nas.lan:8080",
        },
        "PUBLIC_BASE_URL",
    ),
    ("postgres-host-port", {"POSTGRES_HOST": "db:5433"}, "POSTGRES_HOST"),
    (
        "signing-key-malformed",
        {"MCP_OAUTH_SIGNING_KEY": SIGNING_KEY[:-1]},
        "MCP_OAUTH_SIGNING_KEY",
    ),
]


@pytest.mark.parametrize(("label", "overrides", "named"), REFUSALS, ids=[r[0] for r in REFUSALS])
def test_a_refusal_names_its_setting_and_echoes_no_secret(monkeypatch, label, overrides, named):
    for key, value in {**SECRETS, **overrides}.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError) as refused:
        Settings(_env_file=None)
    text = str(refused.value)

    assert named in text  # the refusal under test spoke, not some other one
    assert "input_value" not in text
    for secret in (DB_PASSWORD, CLIENT_SECRET, SIGNING_KEY, SIGNING_KEY[:-1]):
        # pydantic truncates what it echoes, so any stretch of a secret counts.
        assert secret[:2] + "..." not in text
        assert secret[-8:] not in text
