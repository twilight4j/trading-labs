from __future__ import annotations

import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI

from collector.config import Settings, load_environment
from collector.ingestion.jobs import CollectionJobs
from collector.ingestion.scheduler import build_scheduler
from valuation import collection, errors
from valuation.auth import require_token
from valuation.errors import CONFIG, UNAVAILABLE, ApiError
from valuation.per import PerConfig
from valuation.screener import FairValueUnavailable, load_fair_value_table

# trading-ui proxies everything under this prefix to labs (one rule; trading-engine's API is `/api/engine/v1`).
API_PREFIX = "/api/labs/v1"


def create_app(
    settings: Settings | None = None, per_config_path: Path | None = None, jobs: CollectionJobs | None = None
) -> FastAPI:
    """The labs API. Its lifespan also runs the collection scheduler — one process serves and collects.

    PER config is re-read per request so TOML edits apply without a restart.
    """
    load_environment()
    settings = settings or Settings()
    jobs = jobs or CollectionJobs(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.scheduler = build_scheduler(settings, jobs)
        app.state.scheduler.start()
        try:
            yield
        finally:
            app.state.scheduler.shutdown(wait=False)
            app.state.scheduler = None

    app = FastAPI(title="trading-labs API", lifespan=lifespan)
    app.state.scheduler = None
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

    router.include_router(collection.build_router(settings, jobs, lambda: app.state.scheduler is not None))
    app.include_router(router)
    return app
