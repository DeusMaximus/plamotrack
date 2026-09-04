"""The host-side break-glass recovery command (§5.6, credentials lost; §5.7; #188).

**Never an HTTP endpoint.** The operator runs it inside the API container (or from
source) when the owner is locked out — a forgotten password, a lost second factor.
It resets the local credential and revokes every session, or just revokes sessions,
straight against the database. Being host-only is the point: the ability to
overwrite the owner credential must require shell access to the host, not a
request, so no network path can reach it (§5.6, route bypass).

    python -m app.auth.recovery reset-password        # prompts for a new password
    python -m app.auth.recovery reset-password --password-stdin < secret
    python -m app.auth.recovery revoke-sessions       # sign every browser out
    python -m app.auth.recovery rebind-oidc           # OIDC mode: forget the bound identity

All print what they did and append an audit event (`auth.recovery_run`).
`rebind-oidc` (#191) clears the owner's `(issuer, subject)` and revokes every
session; the instance then prints a setup token at its next start, and the next
provider login that presents it becomes the owner — the operator never types a
subject. It is how a lost identity-provider account, or a change of provider,
is recovered from.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from app.db import get_sessionmaker
from app.exceptions import InvalidInputError
from app.services import auth as auth_service
from app.services import oidc as oidc_service


async def _rebind_oidc() -> int:
    async with get_sessionmaker()() as session:
        return await oidc_service.recovery_rebind_oidc(session)


async def _reset_password(password: str) -> int:
    async with get_sessionmaker()() as session:
        return await auth_service.recovery_reset_password(session, password=password)


async def _revoke_sessions() -> int:
    async with get_sessionmaker()() as session:
        return await auth_service.recovery_revoke_sessions(session)


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("New owner password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("The passwords did not match.")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.auth.recovery",
        description="Host-side recovery for a locked-out owner (never an HTTP endpoint).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    reset = sub.add_parser("reset-password", help="set a new owner password and revoke sessions")
    reset.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the new password from stdin instead of prompting",
    )
    sub.add_parser(
        "revoke-sessions", help="revoke every browser session without changing the password"
    )
    sub.add_parser(
        "rebind-oidc",
        help="OIDC mode: clear the bound identity and revoke sessions; the next start "
        "prints a setup token and the next provider login binds",
    )

    args = parser.parse_args(argv)

    if args.command == "reset-password":
        password = _read_password(args.password_stdin)
        try:
            revoked = asyncio.run(_reset_password(password))
        except InvalidInputError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"Owner password reset. {revoked} session(s) revoked. Sign in with the new password.")
        return 0

    if args.command == "rebind-oidc":
        revoked = asyncio.run(_rebind_oidc())
        print(
            f"OIDC binding cleared. {revoked} session(s) revoked. Restart the API to get a "
            "setup token, then sign in at the identity provider with it — that identity "
            "becomes the owner."
        )
        return 0

    revoked = asyncio.run(_revoke_sessions())
    print(f"{revoked} session(s) revoked. Every browser must sign in again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
