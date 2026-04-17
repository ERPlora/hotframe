"""
JWT utilities for Cloud <-> Hub secure communication.

Uses RS256 (asymmetric) for cross-service token verification.
The Cloud signs tokens with its private key; the Hub verifies
with the Cloud's public key.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import jwt as pyjwt

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)

ALGORITHM = "RS256"


class JWTError(Exception):
    """Raised when JWT verification fails."""


def create_jwt(
    payload: dict,
    private_key: str,
    expiry: timedelta = timedelta(minutes=15),
) -> str:
    """
    Create a signed JWT token.

    Args:
        payload: Claims to include in the token.
        private_key: RSA private key (PEM format).
        expiry: Token lifetime (default 15 minutes).

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(UTC)
    claims = {
        **payload,
        "iat": now,
        "exp": now + expiry,
    }
    return pyjwt.encode(claims, private_key, algorithm=ALGORITHM)


def verify_jwt(token: str, public_key: str) -> dict:
    """
    Verify and decode a JWT token.

    Args:
        token: The encoded JWT string.
        public_key: RSA public key (PEM format) for verification.

    Returns:
        Decoded payload dictionary.

    Raises:
        JWTError: If the token is invalid, expired, or verification fails.
    """
    try:
        return pyjwt.decode(
            token,
            public_key,
            algorithms=[ALGORITHM],
            options={
                "require": ["exp", "iat"],
                "verify_exp": True,
                "verify_iat": True,
            },
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise JWTError("Token has expired") from exc
    except pyjwt.InvalidTokenError as exc:
        raise JWTError(f"Invalid token: {exc}") from exc


class JWTDependency:
    """
    FastAPI dependency for JWT-authenticated Cloud-to-Hub requests.

    Usage::

        cloud_jwt = JWTDependency(public_key=settings.CLOUD_PUBLIC_KEY)

        @router.post("/api/v1/sync", dependencies=[Depends(cloud_jwt)])
        async def sync_endpoint(request: Request):
            claims = request.state.jwt_claims
            ...
    """

    def __init__(self, public_key: str) -> None:
        self._public_key = public_key

    async def __call__(self, request: Request) -> dict:
        from fastapi import HTTPException, status

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header[7:]
        try:
            claims = verify_jwt(token, self._public_key)
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        request.state.jwt_claims = claims
        return claims
