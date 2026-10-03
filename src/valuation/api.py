from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI

from collector.config import Settings, load_environment
from valuation import errors
from valuation.auth import require_token
from valuation.errors import CONFIG, UNAVAILABLE, ApiError
from valuation.per import PerConfig
from valuation.screener import FairValueUnavailable, load_fair_value_table

# trading-ui proxies everything under this prefix to labs (one rule; trading-engine's API is `/api/engine/v1`).
API_PREFIX = "/api/labs/v1"


def create_app(settings: Settings | None = None, per_config_path: Path | None = None) -> FastAPI:
    """PER config is re-read per request so TOML edits apply without a restart."""
    load_environment()
    settings = settings or Settings()
    app = FastAPI(title="trading-labs API")
    errors.install(app)
    router = APIRouter(prefix=API_PREFIX, dependencies=[Depends(require_token)])

    @router.get("/valuation/fair-value")
    def fair_value() -> dict:
        try:
            per_config = PerConfig.load(per_config_path)
        except (tomllib.TOMLDecodeError, ValueError) as exc:
            raise ApiError(503, CONFIG, f"기준PER 설정 오류({per_config_path}): {exc}") from exc
        try:
            table = load_fair_value_table(settings, per_config)
        except FairValueUnavailable as exc:
            raise ApiError(503, UNAVAILABLE, str(exc)) from exc
        return table.as_payload()

    app.include_router(router)
    return app
