from __future__ import annotations

from datetime import date

import pandas as pd

from collector.config import Settings
from collector.models import IngestionRun
from collector.providers import MarketDataProvider, PykrxProvider
from collector.storage import Lakehouse
from collector.transforms.prices import normalize_adjusted_ohlcv, overlay_adjusted_prices


def security_id_to_ticker(security_id: str) -> str:
    value = security_id.strip()
    if value.startswith("KRX:"):
        value = value.split(":", 1)[1]
    return value.zfill(6)


class AdjustedPricesService:
    """Rebuild curated *_adjusted OHLC via per-ticker pykrx adjusted history."""

    def __init__(self, settings: Settings, price_provider: MarketDataProvider | None = None):
        self.settings = settings
        self.price_provider = price_provider or PykrxProvider()
        self.lakehouse = Lakehouse(settings)

    def _resolve_security_ids(self, security_ids: list[str] | None, limit: int | None) -> list[str]:
        if security_ids:
            resolved = [sid if sid.startswith("KRX:") else f"KRX:{sid.zfill(6)}" for sid in security_ids]
        else:
            master = self.lakehouse.read_curated("security_master")
            if master.empty:
                raise RuntimeError("security_master가 비어 있습니다. 먼저 일봉 수집으로 마스터를 만드세요.")
            frame = master
            if "eligible" in frame.columns:
                eligible = frame["eligible"]
                if eligible.dtype != bool:
                    eligible = eligible.astype("boolean").fillna(False)
                frame = frame.loc[eligible]
            resolved = sorted(frame["security_id"].astype("string").dropna().unique().tolist())
        if limit is not None:
            resolved = resolved[:limit]
        if not resolved:
            raise ValueError("재구축 대상 security_id가 없습니다.")
        return resolved

    def rebuild(
        self,
        start: date,
        end: date,
        *,
        security_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> IngestionRun:
        if end < start:
            raise ValueError("end는 start 이후여야 합니다.")

        run = IngestionRun.start("adjusted_prices")
        targets = self._resolve_security_ids(security_ids, limit)
        as_of = date.today()
        frames: list[pd.DataFrame] = []
        try:
            for security_id in targets:
                ticker = security_id_to_ticker(security_id)
                source = self.price_provider.get_adjusted_ohlcv(ticker, start, end)
                if source is None or source.empty:
                    continue
                frames.append(normalize_adjusted_ohlcv(source, ticker, self.price_provider.name))

            if not frames:
                payload = {**run.as_dict(), "status": "completed", "rows_written": 0, "securities": targets, "message": "no adjusted rows"}
                self.lakehouse.write_metadata("ingestion_runs", run.run_id, payload)
                return IngestionRun(**{**run.as_dict(), "status": "completed", "rows_written": 0})

            adjusted = pd.concat(frames, ignore_index=True)
            adjusted["trade_date"] = pd.to_datetime(adjusted["trade_date"]).dt.normalize()
            adjusted = adjusted.loc[
                (adjusted["trade_date"] >= pd.Timestamp(start))
                & (adjusted["trade_date"] <= pd.Timestamp(end))
            ]

            partitions_updated = 0
            rows_written = 0
            for trade_date, day_adj in adjusted.groupby(adjusted["trade_date"].dt.date, sort=True):
                partition = f"trade_date={trade_date.isoformat()}"
                if not self.lakehouse.curated_partition_exists("daily_prices", partition):
                    continue
                curated = self.lakehouse.read_curated_partition("daily_prices", partition)
                if curated.empty:
                    continue
                merged = overlay_adjusted_prices(curated, day_adj, as_of)
                self.lakehouse.replace_curated_partition("daily_prices", merged, partition)
                partitions_updated += 1
                rows_written += int(merged["close_adjusted"].notna().sum())

            payload = {
                **run.as_dict(),
                "status": "completed",
                "rows_written": rows_written,
                "partitions_updated": partitions_updated,
                "securities": targets,
                "adjustment_as_of": as_of.isoformat(),
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
            self.lakehouse.write_metadata("ingestion_runs", run.run_id, payload)
            return IngestionRun(**{**run.as_dict(), "status": "completed", "rows_written": rows_written})
        except Exception as exc:
            self.lakehouse.write_metadata(
                "ingestion_runs",
                run.run_id,
                {**run.as_dict(), "status": "failed", "message": str(exc), "securities": targets},
            )
            raise
