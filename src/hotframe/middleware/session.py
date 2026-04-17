# SPDX-License-Identifier: Apache-2.0
"""
Signed cookie session middleware using itsdangerous.

Cookie name is configurable via ``settings.SESSION_COOKIE_NAME``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from itsdangerous import BadSignature, TimestampSigner, URLSafeSerializer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class SessionMiddleware(BaseHTTPMiddleware):
    """Signed cookie session middleware."""

    def __init__(
        self,
        app: Any,
        secret_key: str,
        max_age: int = 86400 * 30,
        cookie_name: str = "session",
    ) -> None:
        super().__init__(app)
        self._serializer = URLSafeSerializer(secret_key, signer_kwargs={"key_derivation": "hmac"})
        self._signer = TimestampSigner(secret_key)
        self._max_age = max_age
        self._cookie_name = cookie_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        session_data = self._load_session(request)
        snapshot = json.dumps(session_data, sort_keys=True)
        request.state.session = session_data

        response = await call_next(request)

        current = json.dumps(request.state.session, sort_keys=True)
        if current != snapshot:
            self._save_session(response, request.state.session, request)

        return response

    def _load_session(self, request: Request) -> dict[str, Any]:
        raw = request.cookies.get(self._cookie_name)
        if not raw:
            return {}
        try:
            unsigned = self._signer.unsign(raw, max_age=self._max_age)
            data = self._serializer.loads(unsigned)
            if isinstance(data, dict):
                return data
        except (BadSignature, Exception):
            logger.debug("Invalid or expired session cookie — starting fresh session")
        return {}

    def _save_session(self, response: Response, session: dict[str, Any], request: Request) -> None:
        if not session:
            response.delete_cookie(
                self._cookie_name,
                path="/",
                httponly=True,
                samesite="strict",
            )
            return

        payload = self._serializer.dumps(session)
        signed = self._signer.sign(payload).decode("utf-8")

        is_secure = request.url.scheme == "https"
        response.set_cookie(
            key=self._cookie_name,
            value=signed,
            max_age=self._max_age,
            path="/",
            httponly=True,
            samesite="strict",
            secure=is_secure,
        )


def get_session_data(scope_or_request) -> dict[str, Any]:
    """Parse session cookie from any scope (Request, WebSocket, etc).

    Useful for WebSocket authentication where session middleware doesn't run.
    """
    from hotframe.config.settings import get_settings

    settings = get_settings()
    serializer = URLSafeSerializer(settings.SECRET_KEY, signer_kwargs={"key_derivation": "hmac"})
    signer = TimestampSigner(settings.SECRET_KEY)

    raw = scope_or_request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not raw:
        return {}
    try:
        unsigned = signer.unsign(raw, max_age=settings.SESSION_MAX_AGE)
        data = serializer.loads(unsigned)
        if isinstance(data, dict):
            return data
    except (BadSignature, Exception):
        pass
    return {}
