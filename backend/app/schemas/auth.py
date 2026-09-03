"""Request and response shapes for the auth routes (§5.5 families 2–3; M6-3, #188)."""

from typing import Literal

from pydantic import BaseModel, Field


class SessionRead(BaseModel):
    """`GET /auth/session` — what a browser needs before it can show anything:
    whether the instance is claimed, whether this browser is the owner, and the
    instance's language and formatting locale so the setup and login screens
    render in the right language. No version, no collection data (§5.5, family
    2). `csrf_token` is present only for the owner and travels back in
    `X-CSRF-Token` on every unsafe request."""

    state: Literal["unclaimed", "anonymous", "owner"]
    interface_language: str
    formatting_locale: str
    csrf_token: str | None = None


class SetupRequest(BaseModel):
    """`POST /auth/setup`: the token from the API log and the owner's first password."""

    token: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=4096)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=4096)
