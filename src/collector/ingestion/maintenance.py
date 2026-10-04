"""Upkeep of data that is already stored.

`ingest_day` used to store market holidays: pykrx answers a holiday with every stock at zero, so a partition of
zeros was written for each (248 of them from 2010 to 2026-09-25). New runs skip holidays; this removes the old ones.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

from collector.storage import Lakehouse


@dataclass(frozen=True)
class ClosedDays:
    days: list[str]
    paths: list[Path]
    removed: bool


def closed_days(lakehouse: Lakehouse) -> list[str]:
    """`daily_prices` dates without a single trade — every row has zero volume."""
    directory = lakehouse.settings.curated_dir / "daily_prices"
    if not directory.exists() or not any(directory.glob("trade_date=*")):
        return []
    pattern = str(directory / "**" / "*.parquet")
    with duckdb.connect() as connection:
        rows = connection.execute(
            """
            SELECT CAST(trade_date AS VARCHAR)
            FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
            GROUP BY trade_date
            HAVING coalesce(sum(CASE WHEN volume > 0 THEN 1 ELSE 0 END), 0) = 0
            ORDER BY 1
            """,
            [pattern],
        ).fetchall()
    return [str(row[0])[:10] for row in rows]


def _paths(lakehouse: Lakehouse, day: str) -> list[Path]:
    """Everything stored for that date: the curated prices, the universe built from them, and the raw source."""
    settings = lakehouse.settings
    candidates = [
        settings.curated_dir / "daily_prices" / f"trade_date={day}",
        settings.curated_dir / "universe_snapshot" / f"as_of_date={day}",
        settings.raw_dir / "daily_prices" / f"trade_date={day}",
    ]
    return [path for path in candidates if path.exists()]


def _still_closed(lakehouse: Lakehouse, day: str) -> bool:
    """Checked again right before removing — a partition may have been rewritten since the scan."""
    frame = lakehouse.read_curated_partition("daily_prices", f"trade_date={day}")
    return frame.empty or not pd.to_numeric(frame["volume"], errors="coerce").fillna(0).gt(0).any()


def prune_closed_days(lakehouse: Lakehouse, *, apply: bool = False) -> ClosedDays:
    """List the stored holidays and, with `apply`, remove them. Removal cannot be undone.

    Fetching those dates again stores nothing, so nothing is lost that could be had back.
    """
    days = closed_days(lakehouse)
    paths = [path for day in days for path in _paths(lakehouse, day)]
    if not apply or not days:
        return ClosedDays(days, paths, removed=False)
    removed_days, removed_paths = [], []
    for day in days:
        if not _still_closed(lakehouse, day):
            continue
        for path in _paths(lakehouse, day):
            shutil.rmtree(path)
            removed_paths.append(path)
        removed_days.append(day)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lakehouse.write_metadata(
        "maintenance",
        f"closed-days-{stamp}",
        {"kind": "prune_closed_days", "at": stamp, "days": removed_days, "paths_removed": len(removed_paths)},
    )
    return ClosedDays(removed_days, removed_paths, removed=True)
