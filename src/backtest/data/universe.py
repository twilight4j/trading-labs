from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from backtest.data.prices import _resolve_data_dir


def _has_trades(partition: Path) -> bool:
    """False for a market holiday stored as a partition: every market cap is zero.

    The collector no longer stores holidays, but 248 such partitions were written before that
    (docs/collection.md). Picking one as "the last session" would filter out every stock.
    """
    pattern = str(partition / "**" / "*.parquet")
    try:
        with duckdb.connect() as connection:
            row = connection.execute("SELECT max(market_cap) FROM read_parquet(?, union_by_name=true)", [pattern]).fetchone()
    except duckdb.Error:
        return True
    return bool(row and row[0] is not None and row[0] > 0)


def _latest_trade_date_on_or_before(prices_dir: Path, as_of: date) -> date | None:
    found: list[date] = []
    for entry in prices_dir.iterdir():
        if not entry.is_dir() or not entry.name.startswith("trade_date="):
            continue
        try:
            day = date.fromisoformat(entry.name.split("=", 1)[1])
        except ValueError:
            continue
        if day <= as_of:
            found.append(day)
    for day in sorted(found, reverse=True):
        if _has_trades(prices_dir / f"trade_date={day.isoformat()}"):
            return day
    return None


def list_universe(
    data_dir: Path = Path("data/market-data"),
    *,
    as_of: date,
    min_market_cap: float = 100_000_000_000,
    markets: tuple[str, ...] = ("KOSPI", "KOSDAQ"),
    eligible_only: bool = True,
) -> pd.DataFrame:
    """List securities with market_cap >= threshold on as_of (KRW).

    Joins universe_snapshot (eligible) and security_master (name) when present.
    If as_of is not a trading day, uses the last curated session on or before it.
    """
    if min_market_cap < 0:
        raise ValueError("min_market_cap must be >= 0")
    if not markets:
        raise ValueError("markets must not be empty")

    data_dir = _resolve_data_dir(Path(data_dir))
    prices_dir = data_dir / "curated" / "daily_prices"
    if not prices_dir.exists():
        raise FileNotFoundError(f"curated daily_prices not found under {prices_dir}")

    session = _latest_trade_date_on_or_before(prices_dir, as_of)
    if session is None:
        return pd.DataFrame(columns=["security_id", "name", "market", "market_cap", "as_of"])

    day = session.isoformat()
    market_placeholders = ", ".join("?" for _ in markets)
    prices_pattern = str(prices_dir / "**" / "*.parquet")
    sql = f"""
        SELECT
            CAST(security_id AS VARCHAR) AS security_id,
            CAST(market AS VARCHAR) AS market,
            CAST(market_cap AS DOUBLE) AS market_cap
        FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
        WHERE trade_date = DATE '{day}'
          AND market_cap >= ?
          AND market IN ({market_placeholders})
        ORDER BY market_cap DESC
    """
    params: list[object] = [prices_pattern, float(min_market_cap), *markets]

    with duckdb.connect() as connection:
        frame = connection.execute(sql, params).fetchdf()

    if frame.empty:
        return pd.DataFrame(columns=["security_id", "name", "market", "market_cap", "as_of"])

    frame["security_id"] = frame["security_id"].astype("string")
    frame["market"] = frame["market"].astype("string")
    frame["as_of"] = pd.Timestamp(session)

    snapshot_dir = data_dir / "curated" / "universe_snapshot"
    snapshot_part = snapshot_dir / f"as_of_date={day}"
    if eligible_only and snapshot_part.exists():
        snap_pattern = str(snapshot_dir / "**" / "*.parquet")
        with duckdb.connect() as connection:
            eligible = connection.execute(
                f"""
                SELECT CAST(security_id AS VARCHAR) AS security_id
                FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
                WHERE as_of_date = DATE '{day}'
                  AND eligible = TRUE
                """,
                [snap_pattern],
            ).fetchdf()
        frame = frame.merge(eligible, on="security_id", how="inner")

    master_dir = data_dir / "curated" / "security_master"
    if master_dir.exists() and any(master_dir.rglob("*.parquet")):
        master_pattern = str(master_dir / "**" / "*.parquet")
        with duckdb.connect() as connection:
            master = connection.execute(
                """
                SELECT CAST(security_id AS VARCHAR) AS security_id,
                       CAST(name AS VARCHAR) AS name
                FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
                """,
                [master_pattern],
            ).fetchdf()
        frame = frame.merge(master.drop_duplicates("security_id"), on="security_id", how="left")
    else:
        frame["name"] = pd.Series(pd.NA, index=frame.index, dtype="string")

    frame["name"] = frame["name"].astype("string")
    return frame[["security_id", "name", "market", "market_cap", "as_of"]].reset_index(drop=True)
