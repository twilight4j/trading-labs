from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from backtest.analytics.metrics import is_effective, period_returns, summarize_run
from backtest.core.types import BacktestResult, RunPanel
from backtest.data import load_price_panel, load_price_series
from backtest.strategies import get_strategy

_SUMMARY_COLUMNS = [
    "security_id",
    "name",
    "market",
    "market_cap",
    "total_return",
    "buy_hold_return",
    "excess_return",
    "max_drawdown",
    "buy_hold_mdd",
    "cagr",
    "realized_vol",
    "trade_count",
    "bars",
    "effective",
    "error",
]

_PERIOD_COLUMNS = [
    "security_id",
    "period",
    "freq",
    "strategy_return",
    "buy_hold_return",
    "excess_return",
]


def run_backtest(
    strategy: str,
    security_id: str,
    *,
    data_dir: Path = Path("data/market-data"),
    start: date | None = None,
    end: date | None = None,
    initial_cash: float = 10_000_000.0,
    fee_rate: float = 0.0015,
    **strategy_params: object,
) -> BacktestResult:
    """Load curated prices and run a registered strategy."""
    prices = load_price_series(data_dir, security_id, start=start, end=end)
    return get_strategy(strategy, **strategy_params).run(
        prices,
        initial_cash=initial_cash,
        fee_rate=fee_rate,
    )


def run_universe_backtest(
    strategy: str,
    universe: pd.DataFrame,
    *,
    data_dir: Path = Path("data/market-data"),
    start: date | None = None,
    end: date | None = None,
    initial_cash: float = 10_000_000.0,
    fee_rate: float = 0.0015,
    mdd_limit: float = -0.30,
    **strategy_params: object,
) -> RunPanel:
    """Run one strategy over a universe DataFrame (expects security_id)."""
    if "security_id" not in universe.columns:
        raise KeyError("universe must include a security_id column")

    ids = [str(sid) for sid in universe["security_id"].tolist()]
    meta = universe.drop_duplicates("security_id").set_index("security_id")
    panel = load_price_panel(data_dir, ids, start=start, end=end) if ids else {}
    strat = get_strategy(strategy, **strategy_params)

    summary_rows: list[dict[str, object]] = []
    period_rows: list[pd.DataFrame] = []

    for security_id in ids:
        row_meta = _universe_meta(meta, security_id)
        prices = panel.get(security_id)
        if prices is None or prices.empty:
            summary_rows.append(_error_row(security_id, row_meta, "no prices"))
            continue
        try:
            result = strat.run(prices, initial_cash=initial_cash, fee_rate=fee_rate)
            metrics = summarize_run(result)
            effective = is_effective(
                float(metrics["excess_return"]),
                float(metrics["max_drawdown"]),
                mdd_limit=mdd_limit,
            )
            summary_rows.append({
                "security_id": security_id,
                **row_meta,
                "total_return": metrics["total_return"],
                "buy_hold_return": metrics["buy_hold_return"],
                "excess_return": metrics["excess_return"],
                "max_drawdown": metrics["max_drawdown"],
                "buy_hold_mdd": metrics["buy_hold_mdd"],
                "cagr": metrics["cagr"],
                "realized_vol": metrics["realized_vol"],
                "trade_count": metrics["trade_count"],
                "bars": metrics["bars"],
                "effective": effective,
                "error": "",
            })
            for freq in ("YE", "ME"):
                periods = period_returns(result.equity, freq=freq)
                if periods.empty:
                    continue
                periods = periods.copy()
                periods.insert(0, "security_id", security_id)
                period_rows.append(periods)
        except (KeyError, ValueError) as exc:
            summary_rows.append(_error_row(security_id, row_meta, str(exc)))

    summaries = pd.DataFrame(summary_rows, columns=_SUMMARY_COLUMNS)
    if period_rows:
        periods_out = pd.concat(period_rows, ignore_index=True)
    else:
        periods_out = pd.DataFrame(columns=_PERIOD_COLUMNS)
    return RunPanel(summaries=summaries, period_returns=periods_out)


def save_run_panel(panel: RunPanel, path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    panel.summaries.to_parquet(path / "summaries.parquet", index=False)
    panel.period_returns.to_parquet(path / "period_returns.parquet", index=False)
    return path


def load_run_panel(path: Path) -> RunPanel:
    path = Path(path)
    summaries = pd.read_parquet(path / "summaries.parquet")
    period_file = path / "period_returns.parquet"
    periods = pd.read_parquet(period_file) if period_file.exists() else pd.DataFrame(columns=_PERIOD_COLUMNS)
    return RunPanel(summaries=summaries, period_returns=periods)


def _universe_meta(meta: pd.DataFrame, security_id: str) -> dict[str, object]:
    if security_id not in meta.index:
        return {"name": pd.NA, "market": pd.NA, "market_cap": pd.NA}
    row = meta.loc[security_id]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    return {
        "name": row["name"] if "name" in meta.columns else pd.NA,
        "market": row["market"] if "market" in meta.columns else pd.NA,
        "market_cap": row["market_cap"] if "market_cap" in meta.columns else pd.NA,
    }


def _error_row(security_id: str, row_meta: dict[str, object], error: str) -> dict[str, object]:
    return {
        "security_id": security_id,
        **row_meta,
        "total_return": pd.NA,
        "buy_hold_return": pd.NA,
        "excess_return": pd.NA,
        "max_drawdown": pd.NA,
        "buy_hold_mdd": pd.NA,
        "cagr": pd.NA,
        "realized_vol": pd.NA,
        "trade_count": pd.NA,
        "bars": pd.NA,
        "effective": False,
        "error": error,
    }
