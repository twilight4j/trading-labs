from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_data_dir(data_dir: Path) -> Path:
    """Prefer cwd-relative data_dir; if missing, fall back to the repo root.

    Cursor notebooks use the `.ipynb` folder as cwd, so `data/market-data`
    would otherwise look under `notebooks/data/market-data`.
    """
    data_dir = Path(data_dir)
    if (data_dir / "curated" / "daily_prices").exists():
        return data_dir
    if not data_dir.is_absolute():
        candidate = _repo_root() / data_dir
        if (candidate / "curated" / "daily_prices").exists():
            return candidate
    return data_dir


def _prefer_price(frame: pd.DataFrame, adjusted_col: str, raw_col: str) -> pd.Series:
    if adjusted_col in frame.columns:
        adjusted = pd.to_numeric(frame[adjusted_col], errors="coerce")
        if adjusted.notna().any():
            raw = pd.to_numeric(frame[raw_col], errors="coerce") if raw_col in frame.columns else pd.Series(pd.NA, index=frame.index)
            return adjusted.fillna(raw)
    if raw_col in frame.columns:
        return pd.to_numeric(frame[raw_col], errors="coerce")
    if adjusted_col.replace("_adjusted", "") in frame.columns:
        return pd.to_numeric(frame[adjusted_col.replace("_adjusted", "")], errors="coerce")
    raise KeyError(f"price columns missing: {adjusted_col} / {raw_col}")


def _require_daily_prices(data_dir: Path) -> tuple[Path, str]:
    data_dir = _resolve_data_dir(Path(data_dir))
    curated = data_dir / "curated" / "daily_prices"
    if not curated.exists() or not any(curated.glob("trade_date=*")):
        raise FileNotFoundError(f"curated daily_prices not found under {curated}")
    return data_dir, str(curated / "**" / "*.parquet")


def _normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame({
        "trade_date": pd.to_datetime(frame["trade_date"]).dt.normalize(),
        "security_id": frame["security_id"].astype("string"),
        "open": _prefer_price(frame, "open_adjusted", "open_raw"),
        "high": _prefer_price(frame, "high_adjusted", "high_raw"),
        "low": _prefer_price(frame, "low_adjusted", "low_raw"),
        "close": _prefer_price(frame, "close_adjusted", "close_raw"),
        "volume": pd.to_numeric(frame["volume"], errors="coerce") if "volume" in frame.columns else pd.NA,
    })
    result = result.dropna(subset=["open", "close"])
    return result.loc[(result["open"] > 0) & (result["close"] > 0)].reset_index(drop=True)


def load_price_panel(
    data_dir: Path,
    security_ids: list[str] | tuple[str, ...],
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, pd.DataFrame]:
    """Load OHLCV for many securities in one parquet scan."""
    ids = [str(sid) for sid in security_ids]
    if not ids:
        return {}

    _, pattern = _require_daily_prices(data_dir)
    placeholders = ", ".join("?" for _ in ids)
    clauses = [f"security_id IN ({placeholders})"]
    params: list[object] = [pattern, *ids]
    if start is not None:
        clauses.append("trade_date >= ?")
        params.append(start.isoformat())
    if end is not None:
        clauses.append("trade_date <= ?")
        params.append(end.isoformat())
    where = " AND ".join(clauses)

    with duckdb.connect() as connection:
        frame = connection.execute(
            f"""
            SELECT *
            FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
            WHERE {where}
            ORDER BY security_id, trade_date
            """,
            params,
        ).fetchdf()

    if frame.empty:
        return {}

    normalized = _normalize_ohlcv(frame)
    if normalized.empty:
        return {}

    panel: dict[str, pd.DataFrame] = {}
    for security_id, chunk in normalized.groupby("security_id", sort=False):
        panel[str(security_id)] = chunk.reset_index(drop=True)
    return panel


def load_price_series(
    data_dir: Path,
    security_id: str,
    *,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Load a single-security OHLCV series from curated daily_prices parquet."""
    data_dir, _ = _require_daily_prices(data_dir)
    curated = data_dir / "curated" / "daily_prices"
    panel = load_price_panel(data_dir, [security_id], start=start, end=end)
    if security_id not in panel:
        raise ValueError(f"no prices for {security_id} in {curated}")
    return panel[security_id]
