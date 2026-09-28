from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi import FastAPI, HTTPException

from collector.config import Settings
from valuation.per import PerConfig
from valuation.screener import FairValueUnavailable, load_fair_value_table


def create_app(settings: Settings | None = None, per_config_path: Path | None = None) -> FastAPI:
    """PER config is re-read per request so TOML edits apply without a restart."""
    settings = settings or Settings()
    app = FastAPI(title="trading-labs valuation API")

    @app.get("/api/v1/valuation/fair-value")
    def fair_value() -> dict:
        try:
            per_config = PerConfig.load(per_config_path)
        except (tomllib.TOMLDecodeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=f"기준PER 설정 오류({per_config_path}): {exc}") from exc
        try:
            table = load_fair_value_table(settings, per_config)
        except FairValueUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return table.as_payload()

    return app
