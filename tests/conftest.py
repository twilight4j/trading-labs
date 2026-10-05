import pytest

from api_caller import TOKEN


@pytest.fixture
def api_token(monkeypatch):
    """API tests own the environment: skip the repo `.env` and use a test token."""
    monkeypatch.setattr("collector.config._ENV_LOADED", True)
    monkeypatch.setenv("UI_API_TOKEN", TOKEN)
