"""The owner's browser session cookie (§5.6, session fixation and theft; M6-3, #188).

What the cookie is: the raw opaque session id (`credentials.new_token`), of
which the database holds only the digest. What the cookie carries:

- `HttpOnly` always, `SameSite=Lax` always (CSRF control 1), `Path=/`, no
  `Domain` — the cookie belongs to this host alone.
- `Secure` **and the `__Host-` prefix** when `PUBLIC_BASE_URL` is `https`: the
  browser then refuses to store it over plain http, and the prefix makes the
  Secure/Path/no-Domain attributes a condition of the name, not a convention.
- On plain http — the loopback and LAN installs — the cookie cannot be `Secure`
  (WebKit does not store a `Secure` cookie set over `http://localhost`, bug
  232088), so it is set under a **different name** without the flag. Its
  confidentiality then rests on the network being the owner's own, and the
  startup log says which mode the instance is in.

Lifetime: idle expiry (`SESSION_IDLE`, from `last_used_at`) and absolute expiry
(`SESSION_ABSOLUTE`, from `created_at`), both enforced by the resolver; the
cookie's `Max-Age` is the absolute lifetime. Logout and a credential change
revoke every session (`services/auth.py`).
"""

from __future__ import annotations

from datetime import timedelta

from starlette.responses import Response

from app.config import Settings

#: The cookie names — one per scheme, so an https instance never accepts a cookie
#: a plain-http one set (the `__Host-` prefix is enforced by the browser).
SECURE_COOKIE_NAME = "__Host-plamotrack_session"
PLAIN_COOKIE_NAME = "plamotrack_session"

#: The header a cookie-borne unsafe request carries the session-bound token in
#: (§5.6, CSRF control 3). Obtained from `GET /auth/session`.
CSRF_HEADER = "X-CSRF-Token"

#: A session not used for this long is expired, whatever its age.
SESSION_IDLE = timedelta(days=14)
#: A session this old is expired, however recently it was used.
SESSION_ABSOLUTE = timedelta(days=30)
#: `last_used_at` is written at most this often, so a busy page does not turn
#: every read into a session-table write.
LAST_USED_WRITE_INTERVAL = timedelta(minutes=5)


def cookie_is_secure(settings: Settings) -> bool:
    """The cookie mode follows `PUBLIC_BASE_URL`'s scheme — the instance's own
    identity, never the request's (§5.6, proxy trust)."""
    return settings.public_base_url.lower().startswith("https://")


def cookie_name(secure: bool) -> str:
    return SECURE_COOKIE_NAME if secure else PLAIN_COOKIE_NAME


def set_session_cookie(response: Response, raw_token: str, *, secure: bool) -> None:
    response.set_cookie(
        cookie_name(secure),
        raw_token,
        max_age=int(SESSION_ABSOLUTE.total_seconds()),
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        cookie_name(secure), path="/", secure=secure, httponly=True, samesite="lax"
    )
