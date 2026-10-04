from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from collector.config import Settings
from collector.models import IngestionRun
from collector.providers import FdrProvider, MarketDataProvider, PykrxProvider
from collector.quality import validate_prices
from collector.quality.quarantine import quarantine
from collector.storage import Lakehouse
from collector.transforms import build_universe, normalize_prices, normalize_security_master
from collector.transforms.prices import combine_raw_and_adjusted

from .consensus import read_latest_prices

SKIPPED = "skipped"


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
        """Store one trading day. A market holiday is not stored: the run comes back as `skipped`.

        pykrx answers a holiday with every stock at zero volume and market cap. Storing that made 248 all-zero
        partitions since 2010 (e.g. 2026-09-24·25 추석), so a day without a single trade is treated as closed.
        """
        run = IngestionRun.start("daily")
        record = {**run.as_dict(), "trade_date": trade_date.isoformat()}
        try:
            master = self.lakehouse.read_curated("security_master")
            if master.empty:
                master = self.refresh_security_master()
            sources = {market: self.price_provider.get_daily_prices(trade_date, market) for market in self.settings.markets}
            raw_frames = [
                normalize_prices(source_raw, trade_date, market, self.price_provider.name, adjusted=False)
                for market, source_raw in sources.items()
            ]
            raw_prices = pd.concat(raw_frames, ignore_index=True)
            if not raw_prices["volume"].fillna(0).gt(0).any():
                return IngestionRun(**{**run.as_dict(), "status": SKIPPED, "message": f"휴장일(거래 없음): {trade_date.isoformat()}"})
            for market, source_raw in sources.items():
                self.lakehouse.write_raw("daily_prices", source_raw, run.run_id, f"trade_date={trade_date}/market={market}/adjusted=false")
            valid_raw, issues = validate_prices(raw_prices)
            invalid = raw_prices.drop(valid_raw.index, errors="ignore")
            quarantine(self.lakehouse, invalid, run.run_id, trade_date.isoformat())
            prices = combine_raw_and_adjusted(valid_raw, None, trade_date)
            partition = f"trade_date={trade_date.isoformat()}"
            self.lakehouse.replace_curated_partition("daily_prices", prices, partition)
            universe = build_universe(prices, master, trade_date)
            self.lakehouse.replace_curated_partition("universe_snapshot", universe, f"as_of_date={trade_date.isoformat()}")
            self.lakehouse.write_metadata("ingestion_runs", run.run_id, {**record, "status": "completed", "rows_written": len(prices)})
            if issues:
                self.lakehouse.write_metadata("quality_results", run.run_id, {"trade_date": trade_date.isoformat(), "issues": [asdict(issue) for issue in issues]})
            return IngestionRun(**{**run.as_dict(), "status": "completed", "rows_written": len(prices)})
        except Exception as exc:
            self.lakehouse.write_metadata("ingestion_runs", run.run_id, {**record, "status": "failed", "message": str(exc)})
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

    def settled_date(self, now: datetime | None = None) -> date:
        """The last date whose prices are final: today once the daily schedule time has passed, else yesterday.

        Before the close pykrx returns intraday values, and a stored day is never fetched again.
        """
        now = now or datetime.now(ZoneInfo(self.settings.timezone))
        closed = (now.hour, now.minute) >= (self.settings.schedule_hour, self.settings.schedule_minute)
        return now.date() if closed else now.date() - timedelta(days=1)

    def catch_up(self, end: date | None = None) -> list[IngestionRun]:
        """Store every missing weekday after the last trading-day partition up to `end` (default: `settled_date`).

        Returns the stored days. Holidays in between are skipped; when holidays were all there was, one `skipped`
        run is recorded so the screen shows why nothing came in.
        """
        end = end or self.settled_date()
        latest, _ = read_latest_prices(self.lakehouse)
        if latest is None:
            return [self.ingest_day(end)]
        day = date.fromisoformat(latest) + timedelta(days=1)
        stored, closed = [], []
        while day <= end:
            if day.weekday() < 5:
                run = self.ingest_day(day)
                (closed if run.status == SKIPPED else stored).append((day, run))
            day += timedelta(days=1)
        if closed and not stored:
            run = closed[-1][1]
            days = ", ".join(day.isoformat() for day, _ in closed)
            self.lakehouse.write_metadata("ingestion_runs", run.run_id, {**run.as_dict(), "message": f"휴장일(거래 없음): {days}"})
        return [run for _, run in stored]

    def update(self, today: date | None = None) -> IngestionRun | None:
        """Catch up to `today` (default: `settled_date`) and return the last stored run, or None when up to date."""
        runs = self.catch_up(today)
        return runs[-1] if runs else None
