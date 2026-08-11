from __future__ import annotations

import pandas as pd

from backtest.core.types import BacktestResult


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    return float(drawdown.min())


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
