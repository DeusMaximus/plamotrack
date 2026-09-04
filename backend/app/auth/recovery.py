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
    python -m app.auth.recovery prune-audit --older-than-days 180

Every command prints what it did and appends an audit event.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime, timedelta

from app.db import get_sessionmaker
from app.exceptions import InvalidInputError
from app.services import audit as audit_service
from app.services import auth as auth_service


async def _reset_password(password: str) -> int:
    async with get_sessionmaker()() as session:
        return await auth_service.recovery_reset_password(session, password=password)


async def _revoke_sessions() -> int:
    async with get_sessionmaker()() as session:
        return await auth_service.recovery_revoke_sessions(session)


async def _prune_audit(older_than_days: int) -> int:
    before = datetime.now(UTC) - timedelta(days=older_than_days)
    async with get_sessionmaker()() as session:
        return await audit_service.prune_events(session, before=before)


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
    prune = sub.add_parser("prune-audit", help="delete old audit events and record the prune")
    prune.add_argument(
        "--older-than-days",
        type=int,
        default=180,
        help="delete events older than this many days (default: 180)",
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

    if args.command == "revoke-sessions":
        revoked = asyncio.run(_revoke_sessions())
        print(f"{revoked} session(s) revoked. Every browser must sign in again.")
        return 0

    if args.older_than_days < 1:
        parser.error("--older-than-days must be at least 1")
    deleted = asyncio.run(_prune_audit(args.older_than_days))
    print(f"Deleted {deleted} audit event(s) older than {args.older_than_days} days.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
