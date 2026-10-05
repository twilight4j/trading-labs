"""Access guard — the service token, then the screen permission of the user the gateway names.

The screen is open through ngrok and the gateway (trading-gateway) forwards `/api/labs` here, so requests arrive from
127.0.0.1 and the bind address cannot tell the outside from this Mac.

1. `require_token` — the service token, the same `UI_API_TOKEN` trading-engine's API server checks. Only the gateway
   holds it; without it the API stays closed (fail-closed).
2. `require_screen` — the gateway signs users in and adds name tags to each request (`X-User-Email`, `X-User-Screens`,
   `X-User-Admin`). A route opens only to a user who has its screen; the admin has every screen. A request without name
   tags is refused even with the right token.

Screen keys come from trading-ui's `src/menu.js`. labs only reads the tags — it does not know users or sessions.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header

from valuation.errors import AUTH_NOT_CONFIGURED, FORBIDDEN, UNAUTHORIZED, ApiError

TOKEN_ENV = "UI_API_TOKEN"
MIN_TOKEN_LENGTH = 16

# The screens labs serves.
FAIR = "fair"
COLLECTION = "collection"


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


@dataclass(frozen=True)
class Caller:
    """The signed-in user, as the gateway's name tags say."""

    email: str
    admin: bool
    screens: frozenset[str]


def caller(
    x_user_email: Annotated[str | None, Header()] = None,
    x_user_screens: Annotated[str | None, Header()] = None,
    x_user_admin: Annotated[str | None, Header()] = None,
) -> Caller:
    email = (x_user_email or "").strip()
    if not email or x_user_admin not in ("true", "false"):
        raise ApiError(
            403, FORBIDDEN, "사용자 이름표가 없는 요청입니다 — 화면은 게이트웨이(trading-gateway)를 거쳐 부릅니다."
        )
    screens = frozenset(key.strip() for key in (x_user_screens or "").split(",") if key.strip())
    return Caller(email=email, admin=x_user_admin == "true", screens=screens)


# For handlers that record who did it.
By = Annotated[Caller, Depends(caller)]


def require_screen(*screens: str) -> Callable[[Caller], Caller]:
    """A dependency that lets through a user who has any one of `screens` (or the admin)."""
    allowed = frozenset(screens)

    def check(who: Annotated[Caller, Depends(caller)]) -> Caller:
        if not (who.admin or who.screens & allowed):
            raise ApiError(403, FORBIDDEN, "이 화면을 볼 권한이 없습니다.")
        return who

    return check
