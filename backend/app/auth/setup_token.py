"""The setup token: how an unclaimed instance meets its owner (§5.6, safe failure;
§5.7; M6-3, #188).

A fresh install and an upgrade onto M6 both start **unclaimed** — the owner row's
`claimed_at` is null, so no credential exists and every collection route fails
closed. The way in is a high-entropy, single-use token the API **prints to its
own log at every start while the instance is unclaimed**, and nowhere else: the
log stream is the host operator's (§5.3), so whoever can read it is whoever
should own the instance, and an operator who missed it restarts the container
rather than editing the database. `POST /auth/setup` presents it with the first
password; it is consumed by a successful claim and answers 410 afterwards.

The token lives in the process — its digest on `app.state` — never in the
database: a database backup must not carry a way in, and a claim is an UPDATE of
the owner row, so a second process's token is simply refused by the 410.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import FastAPI

from app.auth import credentials

STATE_ATTR = "setup_token"

log = logging.getLogger("plamotrack.auth")


@dataclass
class SetupToken:
    """The digest of the token this process announced, or None once consumed or
    never issued (a claimed instance issues none)."""

    digest: str | None = None

    def issue(self) -> str:
        raw = credentials.new_token()
        self.digest = credentials.digest(raw)
        return raw

    def matches(self, presented: str) -> bool:
        if self.digest is None:
            return False
        return credentials.tokens_match(presented, self.digest)

    def consume(self) -> None:
        self.digest = None


def setup_token_state(app: FastAPI) -> SetupToken:
    state = getattr(app.state, STATE_ATTR, None)
    if state is None:
        state = SetupToken()
        setattr(app.state, STATE_ATTR, state)
    return state


def announce(app: FastAPI, *, setup_url: str) -> str:
    """Issue this process's token and print it. Called from the lifespan while the
    instance is unclaimed; the return value is for tests, the log line is the
    product."""
    raw = setup_token_state(app).issue()
    log.warning(
        "\n"
        "============================================================\n"
        "  This plamotrack instance has no owner yet.\n"
        "  Open %s and enter this setup token with your new password:\n"
        "\n"
        "      %s\n"
        "\n"
        "  The token works once. A new one is printed at every start\n"
        "  until the instance is claimed.\n"
        "============================================================",
        setup_url,
        raw,
    )
    return raw
