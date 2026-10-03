from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd

from collector.config import Settings
from collector.models import IngestionRun, QualityIssue
from collector.providers.wisereport import WiseReportProvider
from collector.storage import Lakehouse
from collector.transforms.consensus import (
    CONSENSUS_COLUMNS,
    extract_profile_header,
    infer_base_year,
    parse_company_profile,
    parse_consensus,
)

CONSENSUS_DATASET = "consensus_estimates"
PROFILE_DATASET = "consensus_profiles"
SNAPSHOT_MANIFEST = "consensus_snapshots"
PROFILE_COLUMNS = ["security_id", "ticker", "sector", "dividend_yield", "profile_as_of", "profile_source"]
_PREFERRED_SUFFIX = re.compile(r"\s*\d?우[BC]?(?:\(전환\))?$")


@dataclass(frozen=True)
class ConsensusSnapshotResult:
    run_id: str
    snapshot_date: str
    base_year: int | None
    universe_size: int
    consensus_failed: int
    profile_failed: int
    failure_rate: float
    published: bool


def is_preferred_share(names: pd.Series, known_names: set[str]) -> pd.Series:
    """`security_master` tags 삼성전자우 as COMMON; treat `<base>우/우B/2우B/우(전환)` as preferred when `<base>` is listed."""
    stripped = names.astype(str).str.replace(_PREFERRED_SUFFIX, "", regex=True)
    return (stripped != names.astype(str)) & stripped.isin(known_names)


def read_latest_prices(lakehouse: Lakehouse) -> tuple[str | None, pd.DataFrame]:
    """Latest trading-day `daily_prices` partition as (trade_date, frame).

    pykrx returns every stock with a zero market cap on market holidays and those days are stored as partitions
    too (e.g. 2026-09-24·25 추석). A partition without a single positive market cap is skipped so valuation never
    divides by a holiday's zeros.
    """
    for partition in reversed(lakehouse.list_curated_partitions("daily_prices", prefix="trade_date=")):
        frame = lakehouse.read_curated_partition("daily_prices", partition)
        if not frame.empty and frame["market_cap"].fillna(0).gt(0).any():
            return partition.removeprefix("trade_date="), frame
    return None, pd.DataFrame()


def latest_published_snapshot(lakehouse: Lakehouse, before: str | None = None) -> str | None:
    """Most recent snapshot_date whose manifest is published (optionally strictly before `before`)."""
    manifest_dir = lakehouse.settings.metadata_dir / SNAPSHOT_MANIFEST
    if not manifest_dir.exists():
        return None
    published = []
    for file in manifest_dir.glob("*.json"):
        manifest = json.loads(file.read_text(encoding="utf-8"))
        snapshot = manifest.get("snapshot_date")
        if not manifest.get("published") or not snapshot or (before and snapshot >= before):
            continue
        if lakehouse.curated_partition_exists(CONSENSUS_DATASET, f"snapshot_date={snapshot}"):
            published.append(snapshot)
    return max(published) if published else None


def read_snapshot(lakehouse: Lakehouse, snapshot_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    partition = f"snapshot_date={snapshot_date}"
    return (
        lakehouse.read_curated_partition(CONSENSUS_DATASET, partition),
        lakehouse.read_curated_partition(PROFILE_DATASET, partition),
    )


class ConsensusService:
    """Weekly consensus crawl: estimates for the universe, WICS/dividend for table candidates."""

    def __init__(self, settings: Settings, provider: WiseReportProvider | None = None):
        self.settings = settings
        self.provider = provider or WiseReportProvider(
            request_interval=settings.consensus_request_interval,
            max_retries=settings.consensus_max_retries,
        )
        self.lakehouse = Lakehouse(settings)

    def select_universe(self, limit: int | None = None) -> pd.DataFrame:
        _, prices = read_latest_prices(self.lakehouse)
        if prices.empty:
            raise RuntimeError("daily_prices가 비어 있습니다. 먼저 `market-data backfill`/`update`로 일봉을 수집하세요.")
        master = self.lakehouse.read_curated("security_master")
        if master.empty:
            raise RuntimeError("security_master가 비어 있습니다. 먼저 가격 수집으로 종목 마스터를 만드세요.")
        master = master[["security_id", "ticker", "name", "security_type"]]
        frame = prices[["security_id", "market", "market_cap"]].merge(master, on="security_id", how="inner")
        # Market comes from daily_prices: the master tags KOSDAQ GLOBAL (에코프로비엠 등) as outside_target_market.
        frame = frame.loc[
            (frame["security_type"].astype(str) == "COMMON")
            & ~is_preferred_share(frame["name"], set(master["name"].astype(str)))
            & frame["market"].isin(self.settings.markets)
            & (frame["market_cap"] >= self.settings.consensus_min_market_cap)
        ]
        frame = frame.sort_values("market_cap", ascending=False).drop_duplicates("security_id")
        if limit is not None:
            if limit < 1:
                raise ValueError("limit는 1 이상이어야 합니다.")
            frame = frame.head(limit)
        return frame[["security_id", "ticker", "name", "market", "market_cap"]].reset_index(drop=True)

    def update(self, snapshot_date: date | None = None, *, limit: int | None = None) -> ConsensusSnapshotResult:
        run = IngestionRun.start("consensus")
        snapshot = (snapshot_date or date.today()).isoformat()
        try:
            return self._collect(run, snapshot, limit)
        except Exception as exc:
            self.lakehouse.write_metadata(
                "ingestion_runs",
                run.run_id,
                {**run.as_dict(), "status": "failed", "message": f"snapshot_date={snapshot}: {exc}"},
            )
            raise

    def _collect(self, run: IngestionRun, snapshot: str, limit: int | None) -> ConsensusSnapshotResult:
        universe = self.select_universe(limit)
        if universe.empty:
            raise RuntimeError("시총 조건을 만족하는 대상 종목이 없습니다. daily_prices/security_master를 확인하세요.")
        issues: list[QualityIssue] = []

        estimate_frames: list[pd.DataFrame] = []
        raw_estimates: list[dict] = []
        for row in universe.itertuples(index=False):
            try:
                payload = self.provider.fetch_consensus(row.ticker)
                estimate_frames.append(parse_consensus(payload, security_id=row.security_id, ticker=row.ticker))
            except Exception as exc:
                issues.append(QualityIssue("consensus_fetch", "error", f"{row.ticker}: {exc}"))
                continue
            raw_estimates.append({"ticker": row.ticker, "payload": json.dumps(payload, ensure_ascii=False)})
        estimates = (
            pd.concat(estimate_frames, ignore_index=True)
            if estimate_frames
            else pd.DataFrame(columns=CONSENSUS_COLUMNS)
        )
        consensus_failed = len(issues)

        base_year = infer_base_year(estimates)
        profiles, raw_profiles, profile_issues = self._collect_profiles(universe, estimates, base_year, snapshot)
        issues.extend(profile_issues)

        failure_rate = consensus_failed / len(universe)
        # A snapshot with no parsable estimate (e.g. a changed YYMM format) must not shadow the last good one.
        published = base_year is not None and failure_rate <= self.settings.consensus_max_failure_rate
        partition = f"snapshot_date={snapshot}"
        if raw_estimates:
            self.lakehouse.write_raw(CONSENSUS_DATASET, pd.DataFrame(raw_estimates), run.run_id, partition)
        if raw_profiles:
            self.lakehouse.write_raw(PROFILE_DATASET, pd.DataFrame(raw_profiles), run.run_id, partition)
        # A failed re-run on the same date keeps that date's published snapshot (raw above still records the run).
        keep_published = not published and self._is_published(snapshot)
        if not keep_published:
            self.lakehouse.replace_curated_partition(CONSENSUS_DATASET, estimates, partition)
            self.lakehouse.replace_curated_partition(PROFILE_DATASET, profiles, partition)

        result = ConsensusSnapshotResult(
            run_id=run.run_id,
            snapshot_date=snapshot,
            base_year=base_year,
            universe_size=len(universe),
            consensus_failed=consensus_failed,
            profile_failed=len(profile_issues),
            failure_rate=round(failure_rate, 4),
            published=published,
        )
        if not keep_published:
            self.lakehouse.write_metadata(SNAPSHOT_MANIFEST, snapshot, asdict(result))
        self.lakehouse.write_metadata(
            "ingestion_runs",
            run.run_id,
            {
                **run.as_dict(),
                **asdict(result),
                "status": "withheld" if keep_published else "completed",
                "rows_written": 0 if keep_published else len(estimates),
                "message": f"snapshot_date={snapshot} published={published}",
                "issues": [asdict(issue) for issue in issues],
            },
        )
        return result

    def _is_published(self, snapshot: str) -> bool:
        manifest = self.lakehouse.settings.metadata_dir / SNAPSHOT_MANIFEST / f"{snapshot}.json"
        return manifest.exists() and bool(json.loads(manifest.read_text(encoding="utf-8")).get("published"))

    def _collect_profiles(
        self,
        universe: pd.DataFrame,
        estimates: pd.DataFrame,
        base_year: int | None,
        snapshot: str,
    ) -> tuple[pd.DataFrame, list[dict], list[QualityIssue]]:
        """WICS sector and dividend only for stocks that can reach the table (base year + 2 estimate present)."""
        if base_year is None or estimates.empty:
            return pd.DataFrame(columns=PROFILE_COLUMNS), [], []
        target_year = estimates["is_estimate"].astype(bool) & (estimates["fiscal_year"] == base_year + 2)
        candidates = set(estimates.loc[target_year & estimates["net_income_controlling"].notna(), "ticker"])

        previous = self._previous_profiles(snapshot)
        rows: list[dict] = []
        raw: list[dict] = []
        issues: list[QualityIssue] = []
        for row in universe.loc[universe["ticker"].isin(candidates)].itertuples(index=False):
            try:
                page = self.provider.fetch_company_page(row.ticker)
                header = extract_profile_header(page)
                sector, dividend = parse_company_profile(page)
                if sector is None:
                    raise ValueError("WICS 헤더를 찾지 못했습니다.")
            except Exception as exc:
                issues.append(QualityIssue("profile_fetch", "warning", f"{row.ticker}: {exc}"))
                prior = previous.get(row.ticker)
                if prior is not None:
                    rows.append({**prior, "security_id": row.security_id, "profile_source": "carried_forward"})
                else:
                    rows.append({"security_id": row.security_id, "ticker": row.ticker, "profile_source": "missing"})
                continue
            raw.append({"ticker": row.ticker, "header": header})
            rows.append(
                {
                    "security_id": row.security_id,
                    "ticker": row.ticker,
                    "sector": sector,
                    "dividend_yield": dividend,
                    "profile_as_of": snapshot,
                    "profile_source": "crawled",
                }
            )
        frame = pd.DataFrame(rows, columns=PROFILE_COLUMNS)
        frame["dividend_yield"] = frame["dividend_yield"].astype("float64")
        return frame, raw, issues

    def _previous_profiles(self, snapshot: str) -> dict[str, dict]:
        previous = latest_published_snapshot(self.lakehouse, before=snapshot)
        if previous is None:
            return {}
        _, profiles = read_snapshot(self.lakehouse, previous)
        if profiles.empty:
            return {}
        usable = profiles.loc[profiles["sector"].notna()]
        return {str(item["ticker"]): item for item in usable[PROFILE_COLUMNS].to_dict("records")}
