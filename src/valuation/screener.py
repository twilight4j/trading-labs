from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from collector.config import Settings
from collector.ingestion.consensus import latest_published_snapshot, read_latest_prices, read_snapshot
from collector.storage import Lakehouse
from collector.transforms.consensus import infer_base_year
from valuation.per import PerConfig

EOK = 100_000_000
ROW_COLUMNS = [
    "stock_name",
    "market",
    "ticker",
    "market_cap_eok",
    "net_income_y0",
    "fair_cap_y0",
    "upside_y0",
    "net_income_y2",
    "fair_cap_y2",
    "upside_y2",
    "dividend_yield",
    "sector",
    "base_per",
]


class FairValueUnavailable(RuntimeError):
    """No published consensus snapshot or no price data to value against."""


def fair_value(net_income: float | None, market_cap_eok: float, per: float) -> tuple[float | None, float | None]:
    """K = E × PER (억), D = (K / P − 1) × 100. A negative E is valued as-is."""
    if net_income is None or math.isnan(net_income) or market_cap_eok <= 0:
        return None, None
    fair_cap = net_income * per
    return fair_cap, (fair_cap / market_cap_eok - 1) * 100


def build_fair_value_rows(
    estimates: pd.DataFrame,
    profiles: pd.DataFrame,
    prices: pd.DataFrame,
    master: pd.DataFrame,
    per_config: PerConfig,
    min_market_cap: int,
) -> tuple[int | None, pd.DataFrame]:
    """Rows for stocks with a base-year+2 estimate, valued against the latest market cap."""
    base_year = infer_base_year(estimates)
    if base_year is None:
        return None, pd.DataFrame(columns=ROW_COLUMNS)
    projected = estimates.loc[estimates["is_estimate"].astype(bool)]
    by_year = (
        projected.drop_duplicates(["ticker", "fiscal_year"])
        .set_index(["ticker", "fiscal_year"])["net_income_controlling"]
        .unstack()
    )
    y0 = by_year.get(base_year, pd.Series(dtype="float64", index=by_year.index))
    y2 = by_year.get(base_year + 2, pd.Series(dtype="float64", index=by_year.index))

    frame = pd.DataFrame({"net_income_y0": y0, "net_income_y2": y2}).loc[y2.notna()]
    frame = frame.join(estimates.drop_duplicates("ticker").set_index("ticker")["security_id"])
    frame = frame.reset_index(names="ticker").merge(
        prices[["security_id", "market", "market_cap"]], on="security_id", how="inner"
    )
    frame = frame.loc[frame["market_cap"] >= min_market_cap]
    frame = frame.merge(master[["security_id", "name"]].drop_duplicates("security_id"), on="security_id", how="left")
    if profiles.empty:
        frame["sector"], frame["dividend_yield"] = None, float("nan")
    else:
        frame = frame.merge(profiles[["ticker", "sector", "dividend_yield"]], on="ticker", how="left")

    rows = []
    for item in frame.itertuples(index=False):
        sector = item.sector if isinstance(item.sector, str) else None
        per = per_config.resolve(item.ticker, sector)
        market_cap_eok = item.market_cap / EOK
        fair_cap_y0, upside_y0 = fair_value(item.net_income_y0, market_cap_eok, per)
        fair_cap_y2, upside_y2 = fair_value(item.net_income_y2, market_cap_eok, per)
        rows.append(
            {
                "stock_name": item.name,
                "market": item.market,
                "ticker": item.ticker,
                "market_cap_eok": market_cap_eok,
                "net_income_y0": item.net_income_y0,
                "fair_cap_y0": fair_cap_y0,
                "upside_y0": upside_y0,
                "net_income_y2": item.net_income_y2,
                "fair_cap_y2": fair_cap_y2,
                "upside_y2": upside_y2,
                "dividend_yield": item.dividend_yield,
                "sector": sector,
                "base_per": per,
            }
        )
    result = pd.DataFrame(rows, columns=ROW_COLUMNS)
    return base_year, result.sort_values("upside_y2", ascending=False, na_position="last").reset_index(drop=True)


def _json_value(value: object) -> object:
    if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
        return None
    return value.item() if hasattr(value, "item") else value


@dataclass(frozen=True)
class FairValueTable:
    base_year: int
    snapshot_date: str
    price_date: str
    rows: pd.DataFrame

    def as_payload(self) -> dict:
        return {
            "base_year": self.base_year,
            "snapshot_date": self.snapshot_date,
            "price_date": self.price_date,
            "rows": [{key: _json_value(value) for key, value in row.items()} for row in self.rows.to_dict("records")],
        }


def load_fair_value_table(settings: Settings, per_config: PerConfig) -> FairValueTable:
    lakehouse = Lakehouse(settings)
    snapshot = latest_published_snapshot(lakehouse)
    if snapshot is None:
        raise FairValueUnavailable("게시된 컨센서스 스냅샷이 없습니다. `market-data consensus update`를 먼저 실행하세요.")
    price_date, prices = read_latest_prices(lakehouse)
    if price_date is None or prices.empty:
        raise FairValueUnavailable("daily_prices가 비어 있습니다. 일봉 수집 상태를 확인하세요.")
    estimates, profiles = read_snapshot(lakehouse, snapshot)
    master = lakehouse.read_curated("security_master")
    base_year, rows = build_fair_value_rows(
        estimates, profiles, prices, master, per_config, settings.consensus_min_market_cap
    )
    if base_year is None:
        raise FairValueUnavailable(f"스냅샷 {snapshot}에 추정치(E)가 없습니다.")
    return FairValueTable(base_year=base_year, snapshot_date=snapshot, price_date=price_date, rows=rows)
