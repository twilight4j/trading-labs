"""Access guard — every labs API request needs the trading-ui token.

trading-ui serves its screen through ngrok and its Vite proxy forwards `/api/labs` here, so requests arrive from
127.0.0.1 and the bind address cannot tell the outside from this Mac. The token is the same `UI_API_TOKEN` that
trading-engine's API server checks (one token for the whole screen). Without it the API stays closed (fail-closed).
"""

from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import Header

from valuation.errors import AUTH_NOT_CONFIGURED, UNAUTHORIZED, ApiError

TOKEN_ENV = "UI_API_TOKEN"
MIN_TOKEN_LENGTH = 16


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = os.environ.get(TOKEN_ENV) or ""
    if len(expected) < MIN_TOKEN_LENGTH:
        raise ApiError(
            503, AUTH_NOT_CONFIGURED,
            f"{TOKEN_ENV} 가 없거나 {MIN_TOKEN_LENGTH}자보다 짧아 API 를 열지 않습니다 — .env 에 추가하세요.",
        )
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.strip().encode(), expected.encode()):
        raise ApiError(
            401, UNAUTHORIZED, "인증 토큰이 없거나 틀립니다(Authorization: Bearer <토큰>).",
            headers={"WWW-Authenticate": "Bearer"},
        )
