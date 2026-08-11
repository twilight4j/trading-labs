from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

import pandas as pd

from collector.config import Settings
from collector.models import IngestionRun
from collector.providers import FdrProvider, MarketDataProvider, PykrxProvider
from collector.quality import validate_prices
from collector.quality.quarantine import quarantine
from collector.storage import Lakehouse
from collector.transforms import build_universe, normalize_prices, normalize_security_master
from collector.transforms.prices import combine_raw_and_adjusted


class IngestionService:
    def __init__(self, settings: Settings, price_provider: MarketDataProvider | None = None, metadata_provider: MarketDataProvider | None = None):
        self.settings = settings
        self.price_provider = price_provider or PykrxProvider()
        self.metadata_provider = metadata_provider or FdrProvider()
        self.lakehouse = Lakehouse(settings)

    def refresh_security_master(self) -> pd.DataFrame:
        source = self.metadata_provider.get_security_master()
        normalized = normalize_security_master(source, self.metadata_provider.name)
        self.lakehouse.replace_curated_partition("security_master", normalized, "current")
        return normalized

    def ingest_day(self, trade_date: date) -> IngestionRun:
        run = IngestionRun.start("daily")
        try:
            master = self.lakehouse.read_curated("security_master")
            if master.empty:
                master = self.refresh_security_master()
            raw_frames = []
            for market in self.settings.markets:
                source_raw = self.price_provider.get_daily_prices(trade_date, market)
                self.lakehouse.write_raw("daily_prices", source_raw, run.run_id, f"trade_date={trade_date}/market={market}/adjusted=false")
                raw_frames.append(normalize_prices(source_raw, trade_date, market, self.price_provider.name, adjusted=False))
            raw_prices = pd.concat(raw_frames, ignore_index=True)
            valid_raw, issues = validate_prices(raw_prices)
            invalid = raw_prices.drop(valid_raw.index, errors="ignore")
            quarantine(self.lakehouse, invalid, run.run_id, trade_date.isoformat())
            prices = combine_raw_and_adjusted(valid_raw, None, trade_date)
            partition = f"trade_date={trade_date.isoformat()}"
            self.lakehouse.replace_curated_partition("daily_prices", prices, partition)
            universe = build_universe(prices, master, trade_date)
            self.lakehouse.replace_curated_partition("universe_snapshot", universe, f"as_of_date={trade_date.isoformat()}")
            self.lakehouse.write_metadata("ingestion_runs", run.run_id, {**run.as_dict(), "status": "completed", "rows_written": len(prices)})
            if issues:
                self.lakehouse.write_metadata("quality_results", run.run_id, {"trade_date": trade_date.isoformat(), "issues": [asdict(issue) for issue in issues]})
            return IngestionRun(**{**run.as_dict(), "status": "completed", "rows_written": len(prices)})
        except Exception as exc:
            self.lakehouse.write_metadata("ingestion_runs", run.run_id, {**run.as_dict(), "status": "failed", "message": str(exc)})
            raise

    def backfill(self, start: date, end: date) -> list[IngestionRun]:
        if end < start:
            raise ValueError("end는 start 이후여야 합니다.")
        runs = []
        day = start
        while day <= end:
            if day.weekday() < 5:
                runs.append(self.ingest_day(day))
            day += timedelta(days=1)
        return runs

    def update(self, today: date | None = None) -> IngestionRun | None:
        today = today or date.today()
        prices = self.lakehouse.read_curated("daily_prices")
        if prices.empty:
            return self.ingest_day(today)
        last = pd.to_datetime(prices["trade_date"]).dt.date.max()
        candidate = last + timedelta(days=1)
        while candidate <= today and candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return self.ingest_day(candidate) if candidate <= today else None
