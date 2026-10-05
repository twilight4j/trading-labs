"""Screen permissions — each route opens only to its screen, by the name tags the gateway (trading-gateway) adds.

Which route belongs to which screen is the table below. A new route must be added to it — the test fails otherwise.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api_caller import AUTH, TOKEN_ONLY, caller
from collector.config import Settings
from collector.ingestion.jobs import CollectionJobs
from collector.storage import Lakehouse
from valuation.api import API_PREFIX, create_app
from wisereport_fakes import seed_market_data

pytestmark = pytest.mark.usefixtures("api_token")

# The screen a route needs → routes. Screen keys come from trading-ui's src/menu.js.
SCREENS = {
    "fair": ["GET /valuation/fair-value"],
    "collection": [
        "GET /collection/status",
        "POST /collection/jobs/{job}/run",
        "PUT /collection/jobs/{job}/schedule",
    ],
}
ROUTES = {route: screen for screen, routes in SCREENS.items() for route in routes}
# Screens labs does not serve (trading-engine's) are mixed in: another screen's permission must not open a route.
EVERY_SCREEN = frozenset({"dashboard", "evaluation", "strategy", "fair", "collection"})
FAIR_VALUE = f"{API_PREFIX}/valuation/fair-value"


class Started:
    """Collects what the API starts instead of running it."""

    def __init__(self) -> None:
        self.work: list = []

    def runners(self) -> dict:
        return {job: lambda _settings: None for job in ("daily", "consensus", "fundamentals")}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    settings = Settings(data_dir=tmp_path / "market-data")
    seed_market_data(Lakehouse(settings))
    return settings


@pytest.fixture
def started() -> Started:
    return Started()


@pytest.fixture
def client(settings, started) -> TestClient:
    return TestClient(create_app(settings, jobs=CollectionJobs(settings, started.runners(), started.work.append)))


def call(client, route, headers):
    method, path = route.split()
    body = {"enabled": False} if method == "PUT" else None
    return client.request(method, API_PREFIX + path.format(job="daily"), headers=headers, json=body)


def test_every_route_has_its_screen_written_down(client):
    served = {
        f"{method.upper()} {path.removeprefix(API_PREFIX)}"
        for path, methods in client.app.openapi()["paths"].items()
        for method in methods
    }
    assert served == set(ROUTES)


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_without_its_screen_the_route_is_forbidden(client, route):
    others = EVERY_SCREEN - {ROUTES[route]}

    response = call(client, route, caller(*others))

    assert response.status_code == 403, response.text
    body = response.json()
    assert body["code"] == "forbidden"
    assert body["errors"] == [{"field": None, "message": body["detail"]}]      # the shape trading-ui reads


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_its_screen_opens_the_route(client, route):
    assert call(client, route, caller(ROUTES[route])).status_code not in (401, 403)


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_the_admin_passes_without_any_screen(client, route):
    assert call(client, route, AUTH).status_code not in (401, 403)


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_the_token_alone_is_not_enough(client, route):
    """Closed even if the gateway forgot the name tags."""
    response = call(client, route, TOKEN_ONLY)

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert "이름표" in response.json()["detail"]


@pytest.mark.parametrize("tags", [
    {"X-User-Screens": "fair", "X-User-Admin": "true"},                                 # nobody
    {"X-User-Email": " ", "X-User-Screens": "fair", "X-User-Admin": "true"},            # an empty email
    {"X-User-Email": "user@example.com", "X-User-Screens": "fair"},                     # admin or not is unknown
    {"X-User-Email": "user@example.com", "X-User-Screens": "fair", "X-User-Admin": "yes"},
    {"X-User-Email": "user@example.com", "X-User-Screens": "fair", "X-User-Admin": "True"},
])
def test_incomplete_name_tags_are_refused(client, tags):
    response = client.get(FAIR_VALUE, headers={**TOKEN_ONLY, **tags})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_name_tags_do_not_replace_the_token(client):
    tags = {key: value for key, value in AUTH.items() if key != "Authorization"}

    for headers in (tags, {**tags, "Authorization": "Bearer wrong-token-0123456789"}):
        for route in ROUTES:
            response = call(client, route, headers)

            assert response.status_code == 401
            assert response.json()["code"] == "unauthorized"


def test_screens_may_come_with_spaces_and_missing_screens_mean_none(client):
    spaced = {**caller(), "X-User-Screens": " collection , fair "}
    without = {key: value for key, value in caller().items() if key != "X-User-Screens"}

    assert client.get(f"{API_PREFIX}/collection/status", headers=spaced).status_code == 200
    assert client.get(f"{API_PREFIX}/collection/status", headers=without).status_code == 403


def test_a_forbidden_request_changes_nothing(client, settings, started):
    viewer = caller("fair")

    assert call(client, "POST /collection/jobs/{job}/run", viewer).status_code == 403
    assert call(client, "PUT /collection/jobs/{job}/schedule", viewer).status_code == 403

    assert started.work == []                                                  # nothing was started
    assert not (settings.metadata_dir / "collection").exists()                 # no switch file, no note
    status = client.get(f"{API_PREFIX}/collection/status", headers=AUTH).json()
    daily = next(job for job in status["jobs"] if job["id"] == "daily")
    assert daily["running"] is None and daily["schedule"]["enabled"] is True
