"""Personal access token management (§5.5 family 6; §5.6; M6-4, #189).

Thin over `services/tokens.py` (rule 1). Every route here is `instance:admin`
in the registry (the `auth-tokens` tag), so only the owner's browser session
reaches it — a token cannot mint, list or revoke tokens — and every response is
`no-store`: the mint response is the one place the secret ever appears.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response

from app.auth.dependency import REQUEST_PRINCIPAL_ATTR
from app.db import SessionDep
from app.schemas.auth import TokenCreate, TokenMinted, TokenRead
from app.services import tokens as token_service

router = APIRouter(prefix="/auth/tokens", tags=["auth-tokens"])


@router.get("", response_model=list[TokenRead])
async def list_tokens(session: SessionDep) -> list[TokenRead]:
    """Every token, newest first, revoked ones included. Never the secret."""
    return [TokenRead.model_validate(row) for row in await token_service.list_tokens(session)]


@router.post("", response_model=TokenMinted, status_code=201)
async def mint_token(request: Request, session: SessionDep, payload: TokenCreate) -> TokenMinted:
    """Mint a token. The response carries the raw token once; only its digest is
    stored, so it cannot be shown again — revoke and mint another instead."""
    raw, row = await token_service.mint_token(
        session,
        name=payload.name,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
        principal=getattr(request.state, REQUEST_PRINCIPAL_ATTR, None),
        request=request,
    )
    return TokenMinted.model_validate({**TokenRead.model_validate(row).model_dump(), "token": raw})


@router.delete("/{token_id}", status_code=204)
async def revoke_token(request: Request, session: SessionDep, token_id: uuid.UUID) -> Response:
    """Revoke a token: it stops authenticating immediately; the row stays for
    the list and the audit trail. Idempotent. 404 for an unknown id."""
    await token_service.revoke_token(
        session,
        token_id,
        principal=getattr(request.state, REQUEST_PRINCIPAL_ATTR, None),
        request=request,
    )
    return Response(status_code=204)
