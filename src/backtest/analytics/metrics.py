from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.core.types import BacktestResult

_TRADING_DAYS_PER_YEAR = 252.0


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    return float(drawdown.min())


def cagr(total_return: float, bars: int, *, trading_days_per_year: float = _TRADING_DAYS_PER_YEAR) -> float:
    if bars <= 0 or trading_days_per_year <= 0:
        return 0.0
    years = bars / trading_days_per_year
    if years <= 0:
        return 0.0
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


def is_effective(
    excess_return: float,
    max_drawdown_value: float,
    *,
    mdd_limit: float = -0.30,
) -> bool:
    return excess_return > 0.0 and max_drawdown_value >= mdd_limit


def realized_vol(close: pd.Series) -> float:
    prices = pd.to_numeric(close, errors="coerce").replace(0, np.nan).dropna()
    if len(prices) < 2:
        return 0.0
    log_ret = np.log(prices).diff().dropna()
    if log_ret.empty:
        return 0.0
    return float(log_ret.std(ddof=1)) if len(log_ret) > 1 else 0.0


def period_returns(equity: pd.DataFrame, *, freq: str) -> pd.DataFrame:
    """Per-period strategy / buy-hold / excess returns from an equity curve.

    freq: ``YE`` (calendar year) or ``ME`` (calendar month).
    """
    if freq not in {"YE", "ME"}:
        raise ValueError("freq must be 'YE' or 'ME'")
    columns = ["period", "freq", "strategy_return", "buy_hold_return", "excess_return"]
    if equity.empty or "equity" not in equity.columns or "close" not in equity.columns:
        return pd.DataFrame(columns=columns)

    frame = equity.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.sort_values("trade_date")
    code = "Y" if freq == "YE" else "M"
    grouped = frame.groupby(frame["trade_date"].dt.to_period(code), sort=True)

    rows: list[dict[str, object]] = []
    for period, chunk in grouped:
        first_equity = float(chunk["equity"].iloc[0])
        last_equity = float(chunk["equity"].iloc[-1])
        first_close = float(chunk["close"].iloc[0])
        last_close = float(chunk["close"].iloc[-1])
        strategy_return = last_equity / first_equity - 1.0 if first_equity > 0 else 0.0
        buy_hold_return = last_close / first_close - 1.0 if first_close > 0 else 0.0
        label = f"{period.year:04d}" if freq == "YE" else f"{period.year:04d}-{period.month:02d}"
        rows.append({
            "period": label,
            "freq": freq,
            "strategy_return": float(strategy_return),
            "buy_hold_return": float(buy_hold_return),
            "excess_return": float(strategy_return - buy_hold_return),
        })
    return pd.DataFrame(rows, columns=columns)


def summarize(result: BacktestResult) -> dict[str, float | int]:
    equity = result.equity
    if equity.empty:
        return {
            "initial_cash": result.initial_cash,
            "final_equity": result.initial_cash,
            "total_return": 0.0,
            "buy_hold_return": 0.0,
            "max_drawdown": 0.0,
            "trade_count": 0,
            "bars": 0,
        }

    final_equity = float(equity["equity"].iloc[-1])
    total_return = final_equity / result.initial_cash - 1.0

    first_close = float(equity["close"].iloc[0])
    last_close = float(equity["close"].iloc[-1])
    buy_hold_final = result.initial_cash * (last_close / first_close) if first_close > 0 else result.initial_cash
    buy_hold_return = buy_hold_final / result.initial_cash - 1.0

    return {
        "initial_cash": float(result.initial_cash),
        "final_equity": final_equity,
        "total_return": float(total_return),
        "buy_hold_return": float(buy_hold_return),
        "max_drawdown": max_drawdown(equity["equity"]),
        "trade_count": int(len(result.trades)),
        "bars": int(len(equity)),
    }


def summarize_run(result: BacktestResult) -> dict[str, float | int | bool]:
    """summarize() plus excess, CAGR, buy-hold MDD, and realized vol."""
    base = summarize(result)
    excess = float(base["total_return"]) - float(base["buy_hold_return"])
    close = result.equity["close"] if not result.equity.empty else pd.Series(dtype=float)
    if result.equity.empty:
        buy_hold_mdd = 0.0
    else:
        first_close = float(result.equity["close"].iloc[0])
        if first_close > 0:
            buy_hold_equity = result.initial_cash * (pd.to_numeric(close, errors="coerce") / first_close)
            buy_hold_mdd = max_drawdown(buy_hold_equity)
        else:
            buy_hold_mdd = 0.0
    return {
        **base,
        "excess_return": excess,
        "cagr": cagr(float(base["total_return"]), int(base["bars"])),
        "buy_hold_mdd": buy_hold_mdd,
        "realized_vol": realized_vol(close),
    }
