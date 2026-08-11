from __future__ import annotations

from datetime import date

import pandas as pd

from collector.config import Settings
from collector.models import IngestionRun
from collector.providers.dart import DartProvider, DartQuotaExceeded
from collector.storage import Lakehouse
from collector.transforms.fundamentals import (
    attach_dart_corp_codes,
    normalize_fundamentals_accounts,
    prefer_cfs_accounts,
)


class FundamentalsService:
    """Collect OpenDART major accounts independently of daily price ingestion."""

    def __init__(self, settings: Settings, provider: DartProvider | None = None):
        self.settings = settings
        self.provider = provider or DartProvider(request_interval=settings.dart_request_interval)
        self.lakehouse = Lakehouse(settings)

    def sync_corp_codes(self) -> pd.DataFrame:
        master = self.lakehouse.read_curated("security_master")
        if master.empty:
            raise RuntimeError(
                "security_master가 비어 있습니다. 먼저 `market-data backfill` 또는 "
                "가격 수집으로 종목 마스터를 만든 뒤 다시 시도하세요."
            )
        corp_codes = self.provider.fetch_corp_codes()
        run = IngestionRun.start("corp_codes")
        self.lakehouse.write_raw("dart_corp_codes", corp_codes, run.run_id, "current")
        enriched = attach_dart_corp_codes(master, corp_codes)
        self.lakehouse.replace_curated_partition("security_master", enriched, "current")
        matched = int(enriched["dart_corp_code"].notna().sum())
        self.lakehouse.write_metadata(
            "ingestion_runs",
            run.run_id,
            {**run.as_dict(), "status": "completed", "rows_written": matched},
        )
        return enriched

    def _target_securities(self, limit: int | None = None) -> pd.DataFrame:
        master = self.lakehouse.read_curated("security_master")
        if master.empty:
            raise RuntimeError("security_master가 비어 있습니다. `fundamentals sync-corp-codes` 전에 가격 수집이 필요합니다.")
        if master["dart_corp_code"].isna().all():
            master = self.sync_corp_codes()
        targets = master.dropna(subset=["dart_corp_code"]).copy()
        if "security_type" in targets.columns:
            targets = targets.loc[targets["security_type"].astype(str) == "COMMON"]
        if "exclusion_reason" in targets.columns:
            reason = targets["exclusion_reason"]
            targets = targets.loc[reason.isna() | (reason.astype(str).str.len() == 0)]
        targets = targets.drop_duplicates("security_id").sort_values("security_id")
        if limit is not None:
            if limit < 1:
                raise ValueError("limit는 1 이상이어야 합니다.")
            targets = targets.head(limit)
        return targets

    def ingest_year_report(self, bsns_year: int, reprt_code: str, securities: pd.DataFrame | None = None) -> IngestionRun:
        run = IngestionRun.start("fundamentals")
        securities = securities if securities is not None else self._target_securities()
        raw_frames: list[pd.DataFrame] = []
        curated_frames: list[pd.DataFrame] = []
        try:
            for row in securities.itertuples(index=False):
                corp_code = str(getattr(row, "dart_corp_code"))
                security_id = str(getattr(row, "security_id"))
                source = self.provider.fetch_accounts_prefer_cfs(corp_code, bsns_year, reprt_code)
                if source.empty:
                    continue
                source = source.copy()
                source["security_id"] = security_id
                raw_frames.append(source)
                curated_frames.append(normalize_fundamentals_accounts(source, security_id=security_id, source=self.provider.name))
            if raw_frames:
                raw = pd.concat(raw_frames, ignore_index=True)
                self.lakehouse.write_raw(
                    "fundamentals_accounts",
                    raw,
                    run.run_id,
                    f"bsns_year={bsns_year}/reprt_code={reprt_code}",
                )
            curated = prefer_cfs_accounts(pd.concat(curated_frames, ignore_index=True)) if curated_frames else pd.DataFrame()
            self.lakehouse.replace_curated_partition(
                "fundamentals_accounts",
                curated,
                f"bsns_year={bsns_year}/reprt_code={reprt_code}",
            )
            completed = IngestionRun(
                **{
                    **run.as_dict(),
                    "status": "completed",
                    "rows_written": len(curated),
                    "message": f"bsns_year={bsns_year} reprt_code={reprt_code}",
                }
            )
            self.lakehouse.write_metadata("ingestion_runs", completed.run_id, completed.as_dict())
            return completed
        except DartQuotaExceeded as exc:
            self.lakehouse.write_metadata(
                "ingestion_runs",
                run.run_id,
                {
                    **run.as_dict(),
                    "status": "quota_exceeded",
                    "message": f"bsns_year={bsns_year} reprt_code={reprt_code}: {exc}",
                },
            )
            raise
        except Exception as exc:
            self.lakehouse.write_metadata(
                "ingestion_runs",
                run.run_id,
                {**run.as_dict(), "status": "failed", "message": str(exc)},
            )
            raise

    def backfill(
        self,
        start_year: int,
        end_year: int,
        reprt_codes: tuple[str, ...] | None = None,
        *,
        limit: int | None = None,
        skip_existing: bool = True,
    ) -> list[IngestionRun]:
        if end_year < start_year:
            raise ValueError("end_year는 start_year 이상이어야 합니다.")
        codes = reprt_codes or self.settings.dart_reprt_codes
        securities = self._target_securities(limit=limit)
        runs: list[IngestionRun] = []
        for year in range(start_year, end_year + 1):
            for reprt_code in codes:
                partition = f"bsns_year={year}/reprt_code={reprt_code}"
                if skip_existing and self.lakehouse.curated_partition_exists("fundamentals_accounts", partition):
                    continue
                try:
                    runs.append(self.ingest_year_report(year, reprt_code, securities))
                except DartQuotaExceeded as exc:
                    raise DartQuotaExceeded(str(exc), completed_runs=runs) from exc
        return runs

    def update(
        self,
        year: int | None = None,
        *,
        reprt_codes: tuple[str, ...] | None = None,
        limit: int | None = None,
        skip_existing: bool = False,
    ) -> list[IngestionRun]:
        year = year or date.today().year
        return self.backfill(
            year,
            year,
            reprt_codes or self.settings.dart_reprt_codes,
            limit=limit,
            skip_existing=skip_existing,
        )
