"""Request headers the API tests share — the service token and the name tags the gateway (trading-gateway) adds."""

from fastapi.testclient import TestClient

TOKEN = "test-token-0123456789"

# The token without name tags — a request that did not come through the gateway. Refused.
TOKEN_ONLY = {"Authorization": f"Bearer {TOKEN}"}


def caller(*screens: str, email: str = "user@example.com", admin: bool = False) -> dict[str, str]:
    """Headers of a request the gateway forwards for a user who has those screens."""
    return {
        **TOKEN_ONLY,
        "X-User-Email": email,
        "X-User-Screens": ",".join(screens),
        "X-User-Admin": "true" if admin else "false",
    }


# The admin — every screen is open. Tests that are not about permissions call as the admin.
AUTH = caller(email="admin@example.com", admin=True)


def authed(app, headers: dict[str, str] = AUTH) -> TestClient:
    return TestClient(app, headers=headers)
